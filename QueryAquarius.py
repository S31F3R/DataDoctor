import requests
import json
import keyring
import os
from datetime import datetime, timedelta
import Logic  # For globals like debug and utcOffset
import threading
import queue

queryLimit = 500 # Configurable max points per API call
maxThreads = 10 # Configurable max number of threads

def apiRead(dataIDs, startDate, endDate, interval):
    if Logic.debug: print("[DEBUG] QueryAquarius.apiRead called with dataIDs: {}, interval: {}, start: {}, end: {}".format(dataIDs, interval, startDate, endDate))

    # Parse start
    startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
    startYear = startDateTime.year
    startMonth = f'{startDateTime.month:02d}'
    startDay = f'{startDateTime.day:02d}'
    startHour = f'{startDateTime.hour:02d}'
    startMinute = f'{startDateTime.minute:02d}'

    # Parse end
    endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
    endYear = endDateTime.year
    endMonth = f'{endDateTime.month:02d}'
    endDay = f'{endDateTime.day:02d}'
    endHour = f'{endDateTime.hour:02d}'
    endMinute = f'{endDateTime.minute:02d}'

    # Build start and end date in ISO format (keep exact)
    startDate = f'{startYear}-{startMonth}-{startDay} {startHour}:{startMinute}'
    endDate = f'{endYear}-{endMonth}-{endDay} {endHour}:{endMinute}'

    # Apply utc offset for Aquarius query
    offsetHours = Logic.getUtcOffsetInt(Logic.utcOffset) # Parse float offset
    startDateTime = startDateTime - timedelta(hours=offsetHours)
    endDateTime = endDateTime - timedelta(hours=offsetHours)
    startDateTime = startDateTime - timedelta(hours=1)
    endDateTime = endDateTime + timedelta(minutes=1)

    # Re-pad after offset
    startMonth = f'{startDateTime.month:02d}'
    startDay = f'{startDateTime.day:02d}'
    startHour = f'{startDateTime.hour:02d}'
    startMinute = f'{startDateTime.minute:02d}'
    endMonth = f'{endDateTime.month:02d}'
    endDay = f'{endDateTime.day:02d}'
    endHour = f'{endDateTime.hour:02d}'
    endMinute = f'{endDateTime.minute:02d}'

    # Build offset ISO
    startDate = f'{startDateTime.year}-{startMonth}-{startDay} {startHour}:{startMinute}'
    endDate = f'{endDateTime.year}-{endMonth}-{endDay} {endHour}:{endMinute}'

    # Fetch creds right before auth, use, then clear
    server = keyring.get_password("DataDoctor", "aqServer") or ''
    user = keyring.get_password("DataDoctor", "aqUser") or ''
    password = keyring.get_password("DataDoctor", "aqPassword") or ''

    if not server or not user or not password:
        print("[ERROR] Missing Aquarius credentials.")
        return {uid: {'data': [], 'label': uid} for uid in dataIDs}

    # Authenticate session with fallback for SSL verification
    authData = {'Username': user, 'EncryptedPassword': password}
    certPath = Logic.resourcePath('certs/aquarius.pem')
    verify_mode = True # Start with system trust store

    for attempt in ['system', 'custom_cert', 'unverified']:
        try:
            if attempt == 'custom_cert' and not os.path.exists(certPath):
                if Logic.debug: print("[DEBUG] No certificate found at '{}', skipping to unverified.".format(certPath))
                continue

            verify_mode = certPath if attempt == 'custom_cert' else False if attempt == 'unverified' else True
            authResponse = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=authData, verify=verify_mode)
            authResponse.raise_for_status()

            if Logic.debug: print(f"[DEBUG] Authentication succeeded with verify={verify_mode}")
            if attempt == 'unverified' and Logic.debug:
                print("[WARN] SSL verification disabled due to cert issues. Add 'aquarius.pem' to 'certs' folder or system trust store for secure connection.")
            break

        except requests.exceptions.SSLError as e:
            if Logic.debug: print(f"[DEBUG] SSL error with verify={verify_mode}: {e}")
            continue
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Authentication failed: {e}")
            return {uid: {'data': [], 'label': uid} for uid in dataIDs}
    else:
        print("[ERROR] Aquarius authentication failed after all attempts.")
        return {uid: {'data': [], 'label': uid} for uid in dataIDs}

    token = authResponse.text.strip('"') # Strip quotes if present
    headers = {'X-Authentication-Token': token}

    # Clear creds immediately after use
    user = None
    password = None

    # Calculate total points (approximate to avoid full list for large ranges)
    totalDuration = endDateTime - startDateTime

    if interval == 'HOUR':
        delta = timedelta(hours=1)
    elif interval.startswith('INSTANT:'):
        minutes = int(interval.split(':')[1])
        delta = timedelta(minutes=minutes)
    elif interval == 'DAY':
        delta = timedelta(days=1)
    else:
        print(f"[ERROR] Unsupported interval: {interval}")
        return {uid: {'data': [], 'label': uid} for uid in dataIDs}
    totalPoints = int(totalDuration.total_seconds() / delta.total_seconds()) + 1

    numChunks = (totalPoints + queryLimit - 1) // queryLimit  # Ceiling division
    if Logic.debug: print(f"[DEBUG] Estimated {totalPoints} points, splitting into {numChunks} chunks of ~{queryLimit} points each")

    # Generate sub-ranges
    subRanges = []
    chunkDuration = totalDuration / numChunks

    for i in range(numChunks):
        subStart = startDateTime + i * chunkDuration
        subEnd = subStart + chunkDuration if i < numChunks - 1 else endDateTime

        # Format for API
        subStartStr = subStart.strftime('%Y-%m-%d %H:%M')
        subEndStr = subEnd.strftime('%Y-%m-%d %H:%M')
        subRanges.append((subStartStr, subEndStr))

    if Logic.debug: print(f"[DEBUG] Generated {len(subRanges)} sub-ranges: {[(s, e) for s, e in subRanges[:3]]}")

    # Threading setup
    resultQueue = queue.Queue() # Thread-safe queue for results

    # Create tasks: (uid, subStart, subEnd) for each UID and sub-range
    tasks = [(uid, subStart, subEnd) for uid in dataIDs for subStart, subEnd in subRanges]
    numTasks = len(tasks)
    numThreads = min(maxThreads, numTasks)  # Use fewer threads if fewer tasks
    if Logic.debug: print(f"[DEBUG] Created {numTasks} tasks for {len(dataIDs)} UIDs across {len(subRanges)} sub-ranges, using {numThreads} threads")

    def queryTask(uid, subStart, subEnd, threadId):
        """Process a single (UID, sub-range) task."""
        if Logic.debug: print(f"[DEBUG] Thread {threadId} processing task for UID {uid}, range {subStart} to {subEnd}")

        # Parse sub-range for API
        subStartDt = datetime.strptime(subStart, '%Y-%m-%d %H:%M')
        subEndDt = datetime.strptime(subEnd, '%Y-%m-%d %H:%M')
        subStartYear = subStartDt.year
        subStartMonth = f'{subStartDt.month:02d}'
        subStartDay = f'{subStartDt.day:02d}'
        subStartHour = f'{subStartDt.hour:02d}'
        subStartMinute = f'{subStartDt.minute:02d}'
        subEndYear = subEndDt.year
        subEndMonth = f'{subEndDt.month:02d}'
        subEndDay = f'{subEndDt.day:02d}'
        subEndHour = f'{subEndDt.hour:02d}'
        subEndMinute = f'{subEndDt.minute:02d}'
        subStartStr = f'{subStartYear}-{subStartMonth}-{subStartDay} {subStartHour}:{subStartMinute}'
        subEndStr = f'{subEndYear}-{subEndMonth}-{subEndDay} {subEndHour}:{subEndMinute}'

        # Query the data
        response = requests.get(
            f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={subStartStr}&QueryTo={subEndStr}&utcOffset={offsetHours}&GetParts=PointsOnly&format=json',
            headers=headers, verify=verify_mode
        )
        try:
            readFile = json.loads(response.content)
        except Exception as e:
            print(f"[WARN] Aquarius fetch failed for UID '{uid}' in thread {threadId}, range {subStart} to {subEnd}: {e}")
            resultQueue.put((uid, {'data': [], 'label': uid}))  # Fallback label
            return

        # Build label from response
        location = readFile.get('LocationIdentifier', uid)
        label = readFile.get('Label', '')
        fullLabel = f'{label} \n{location}'
        points = readFile['Points']
        if Logic.debug: print(f"[DEBUG] Thread {threadId} fetched {len(points)} points for UID '{uid}', range {subStart} to {subEnd}")
        outputData = []

        for point in points:
            # Pull date timestamp
            date = point['Timestamp']
            parseDate = date.split('T')
            parseDate[1] = parseDate[1].split('.')[0]

            # Format to standard
            dateTime = datetime.fromisoformat(f'{parseDate[0]} {parseDate[1]}')
            formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
            value = point['Value'].get('Numeric', None)
            if value is not None:
                outputData.append(f'{formattedTs},{value}')
        resultQueue.put((uid, {'data': outputData, 'label': fullLabel}))
        if Logic.debug: print(f"[DEBUG] Thread {threadId} completed task for UID {uid} with {len(outputData)} points")

    # Start threads
    taskQueue = queue.Queue()
    for task in tasks:
        taskQueue.put(task)

    threads = []

    def worker(threadId):
        while True:
            try:
                uid, subStart, subEnd = taskQueue.get_nowait()
                queryTask(uid, subStart, subEnd, threadId)
                taskQueue.task_done()  # Only call task_done after successful task retrieval and processing
            except queue.Empty:
                if Logic.debug: print(f"[DEBUG] Thread {threadId} found no more tasks")
                break

    for i in range(numThreads):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        if Logic.debug: print(f"[DEBUG] Started thread {i} for task processing")

    # Wait for all threads to complete
    for t in threads:
        t.join()
        if Logic.debug: print(f"[DEBUG] Thread {threads.index(t)} joined")

    # Combine results from queue
    result = {}

    while not resultQueue.empty():
        uid, data = resultQueue.get()

        if uid in result:
            result[uid]['data'].extend(data['data'])
            result[uid]['label'] = data['label']  # Keep latest label
        else:
            result[uid] = data

    # Sort data by timestamp for each UID
    for uid in result:
        result[uid]['data'].sort(key=lambda x: datetime.strptime(x.split(',')[0], '%m/%d/%y %H:%M:00'))
    if Logic.debug: print(f"[DEBUG] Combined results from {numTasks} tasks with {len(result)} UIDs")

    # Ensure all UIDs are in result (add empty for any missed)
    for uid in dataIDs:
        if uid not in result:
            result[uid] = {'data': [], 'label': uid}
            if Logic.debug: print(f"[DEBUG] Added empty result for UID {uid}")

    # Clear server variable
    server = None
    if Logic.debug: print(f"[DEBUG] Returning result dict with {len(result)} UIDs")

    return result