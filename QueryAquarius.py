import requests
import json
import keyring
from datetime import datetime, timedelta
import Logic # For globals like debug and utcOffset

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

    # Authenticate session
    authData = {'Username': user, 'EncryptedPassword': password}
    authResponse = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=authData, verify=False)

    if authResponse.status_code != 200:
        print("[ERROR] Aquarius authentication failed.")
        return {uid: {'data': [], 'label': uid} for uid in dataIDs}

    token = authResponse.text.strip('"') # Strip quotes if present
    headers = {'X-Authentication-Token': token}

    # Clear creds immediately after use
    user = None
    password = None
    result = {}
    uids = dataIDs
    queryLimit = 100

    # Batch uids into groups of queryLimit (serial fetch per uid in group)
    for groupStart in range(0, len(uids), queryLimit):
        groupUids = uids[groupStart:groupStart + queryLimit]
        if Logic.debug: print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))

        for uid in groupUids:
            # Query the data
            response = requests.get(f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={startDate}&QueryTo={endDate}&utcOffset={offsetHours}&GetParts=PointsOnly&format=json', headers=headers, verify=False)
            
            try:
                readFile = json.loads(response.content)
            except Exception as e:
                print("[WARN] Aquarius fetch failed for uid '{}': {}".format(uid, e))
                result[uid] = {'data': [], 'label': uid} # Fallback label
                continue

            # Build label from response
            location = readFile.get('LocationIdentifier', uid)
            label = readFile.get('Label', '')
            fullLabel = f'{label} \n{location}'
            points = readFile['Points']
            if Logic.debug: print("[DEBUG] Fetched {} points for uid '{}'.".format(len(points), uid))
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
            result[uid] = {'data': outputData, 'label': fullLabel}
            
    # Clear server variable
    server = None
    if Logic.debug: print("[DEBUG] Returning result dict with {} UIDs.".format(len(result)))

    return result