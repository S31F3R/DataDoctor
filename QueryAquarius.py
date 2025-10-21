import requests
import json
import keyring
from datetime import datetime, timedelta
import Logic # For globals like debug and utcOffset
import threading
import queue

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
    offsetHours = Logic.getUtcOffsetInt(Logic.utcOffset)  # Parse float offset
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
    verify_mode = True  # Start with system trust store
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
    token = authResponse.text.strip('"')  # Strip quotes if present
    headers = {'X-Authentication-Token': token}
    # Clear creds immediately after use
    user = None
    password = None
    # Threading setup
    maxThreads = 5  # Configurable number of threads
    numThreads = min(maxThreads, len(dataIDs))  # Use fewer threads if fewer UIDs
    resultQueue = queue.Queue()  # Thread-safe queue for results
    uids = dataIDs
    # Split UIDs into groups
    groupSize = (len(uids) + numThreads - 1) // numThreads  # Ceiling division
    uidGroups = [uids[i:i + groupSize] for i in range(0, len(uids), groupSize)]
    if Logic.debug: print(f"[DEBUG] Split {len(uids)} UIDs into {numThreads} groups: {[len(group) for group in uidGroups]}")

    def queryGroup(groupUids, threadId):
        """Process a group of UIDs in a single thread."""
        if Logic.debug: print(f"[DEBUG] Thread {threadId} processing {len(groupUids)} UIDs: {groupUids[:3] if groupUids else []}")
        groupResult = {}
        for uid in groupUids:
            # Query the data
            response = requests.get(
                f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={startDate}&QueryTo={endDate}&utcOffset={offsetHours}&GetParts=PointsOnly&format=json',
                headers=headers, verify=verify_mode
            )
            try:
                readFile = json.loads(response.content)
            except Exception as e:
                print(f"[WARN] Aquarius fetch failed for uid '{uid}' in thread {threadId}: {e}")
                groupResult[uid] = {'data': [], 'label': uid}  # Fallback label
                continue
            # Build label from response
            location = readFile.get('LocationIdentifier', uid)
            label = readFile.get('Label', '')
            fullLabel = f'{label} \n{location}'
            points = readFile['Points']
            if Logic.debug: print(f"[DEBUG] Thread {threadId} fetched {len(points)} points for uid '{uid}'")
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
            groupResult[uid] = {'data': outputData, 'label': fullLabel}
        resultQueue.put(groupResult)  # Store thread results in queue
        if Logic.debug: print(f"[DEBUG] Thread {threadId} completed with {len(groupResult)} UIDs")

    # Start threads
    threads = []
    for i, group in enumerate(uidGroups):
        if group:  # Only start thread for non-empty groups
            t = threading.Thread(target=queryGroup, args=(group, i))
            threads.append(t)
            t.start()
            if Logic.debug: print(f"[DEBUG] Started thread {i} for group of {len(group)} UIDs")

    # Wait for all threads to complete
    for t in threads:
        t.join()
        if Logic.debug: print(f"[DEBUG] Thread {threads.index(t)} joined")

    # Combine results from queue
    result = {}
    while not resultQueue.empty():
        result.update(resultQueue.get())
    if Logic.debug: print(f"[DEBUG] Combined results from {len(threads)} threads with {len(result)} UIDs")

    # Ensure all UIDs are in result (add empty for any missed)
    for uid in uids:
        if uid not in result:
            result[uid] = {'data': [], 'label': uid}
            if Logic.debug: print(f"[DEBUG] Added empty result for UID {uid}")

    # Clear server variable
    server = None
    if Logic.debug: print(f"[DEBUG] Returning result dict with {len(result)} UIDs")
    return result