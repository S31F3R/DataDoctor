import requests
import json
import keyring
from datetime import datetime, timedelta
import Logic  # For buildTimestamps, gapCheck, combineParameters

def apiRead(dataID, startDate, endDate, interval):
    if Logic.debug == True: print("[DEBUG] QueryAquarius.apiRead called with dataID: {}, interval: {}, start: {}, end: {}".format(dataID, interval, startDate, endDate))
        
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
    
    # Build timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, interval)
    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return []
    
    # Apply utc offset for Aquarius query
    startDateTime = startDateTime - timedelta(hours=Logic.utcOffset)
    endDateTime = endDateTime - timedelta(hours=Logic.utcOffset)
    
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
    
    # Authenticate session
    data = {'Username':f'{user}','EncryptedPassword':f'{password}'}
    url = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=data, verify=False)
    headers = {'X-Authentication-Token':url.text}

    # Clear creds immediately after use   
    user = None
    password = None
    
    uids = dataID.split(',')
    queryLimit = 50
    output = []
    buildHeader = []
    
    # Batch uids into groups of queryLimit (serial fetch per uid in group)
    for groupStart in range(0, len(uids), queryLimit):
        groupUids = uids[groupStart:groupStart + queryLimit]

        if Logic.debug == True: print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))        
        groupOutputData = [] # List of outputData lists, one per uid

        for uid in groupUids:
            # Query the data
            url = requests.get(f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={startDate}&QueryTo={endDate}&Logic.utcOffset={Logic.utcOffset}&GetParts=PointsOnly&format=json', headers=headers, verify=False)
            
            try:
                readFile = json.loads(url.content)
            except Exception as e:
                print("[WARN] Aquarius fetch failed for uid '{}': {}".format(uid, e))
                groupOutputData.append([]) # Pad blanks
                continue
            
            # Create arrays
            outputData = []
            header = []

            # Add label to header
            header.append(readFile['LocationIdentifier'])
            header.append(readFile['Label'])
            buildHeader.append(f'{header[0]} \n{header[1]}')            
            points = readFile['Points']

            if Logic.debug == True: print("[DEBUG] Fetched {} points for uid '{}'.".format(len(points), uid))

            for point in points:
                # Pull date timestamp
                date = point['Timestamp']
                parseDate = date.split('T')
                parseDate[1] = parseDate[1].split('.')[0]
                
                # Format to standard
                dateTime = datetime.fromisoformat(f'{parseDate[0]} {parseDate[1]}')
                formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
                value = point['Value']['Numeric']
                outputData.append(f'{formattedTs},{value}')
            
            # Check for gaps
            outputData = Logic.gapCheck(timestamps, outputData, uid)
            groupOutputData.append(outputData)
        
        # Combine group outputs
        if groupOutputData:
            combined = groupOutputData[0]

            for nextData in groupOutputData[1:]:
                combined = Logic.combineParameters(combined, nextData)
            if output:
                output = Logic.combineParameters(output, combined)
            else:
                output = combined
                
    # Clear server variable
    server = None

    if not output:
        print("[WARN] No data after processing all batches.")
        return []
    
    # Prepend header
    output.insert(0, buildHeader)
    if Logic.debug == True: print("[DEBUG] Final output len={} (incl header), sample row: {}".format(len(output), output[1] if len(output) > 1 else 'empty'))
    return output