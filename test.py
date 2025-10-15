import requests
import json
import keyring
from datetime import datetime, timedelta
import Logic # For globals like debug and utcOffset
import platform  # For OS check
from requests_ntlm import HttpNtlmAuth # Windows Auth probe

# Module-level cache (secure in-memory only, no disk)
cachedSession = None
cachedToken = None
cachedServer = None
cacheExpiry = None # datetime for TTL (1hr)

def apiRead(dataIDs, startDate, endDate, interval):
    global cachedSession, cachedToken, cachedServer, cacheExpiry # For secure resuse/clear
    if Logic.debug == True: print("[DEBUG] QueryAquarius.apiRead called with dataIDs: {}, interval: {}, start: {}, end: {}, type: {}".format(dataIDs, interval, startDate, endDate, type(dataIDs)))
      
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
    startDateTime = startDateTime - timedelta(hours=Logic.utcOffset)
    endDateTime = endDateTime - timedelta(hours=Logic.utcOffset)

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

    # Set now to current time
    now = datetime.now()

    # Check cache validity (1hr TTL, secure expiry)
    if cachedSession and cachedServer and cachedToken and cacheExpiry and now < cacheExpiry:
        if Logic.debug == True: print("[DEBUG] Using cached session/token.")
        session = cachedSession

        if cachedToken: # Creds mode
            headers = {'X-Authentication-Token': cachedToken}
        else: # NTLM mode
            headers = None
    else:
        # Clear expired cache
        cachedSession = None
        cachedToken = None
        cachedServer = None
        cacheExpiry = None
        session = None
        headers = None

        # Load config for toggle
        config = Logic.loadConfig()
        #useWindowsAuth = config.get('useWindowsAuth', False)
        useWindowsAuth = True

        server = keyring.get_password("DataDoctor", "aqServer") or ''

        if not server:
            print("[ERROR] Missing Aquairus server.")
            return {uid: {'data': [], 'label': uid} for uid in dataIDs}
        
        if useWindowsAuth and platform.system() == 'Windows':
            if Logic.debug == True: print ("[DEBUG] Probing Windows Auth (NTLM).")

            try:
                ntlmSession = requests.Session()
                ntlmSession.auth = HttpNtlmAuth('','') # Auto current user creds
                probeUid = dataIDs[0]
                probeUrl = f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={probeUid}&QueryFrom={startDate}&QueryTo={endDate}&utcOffset={Logic.utcOffset}&GetParts=PointsOnly&Format=json'
                probeResponse = ntlmSession.get(probeUrl, verify=False, timeout=10)
                
                if probeResponse.status_code == 200:
                    # Cache NTLM session (cookies auto-handled)
                    cachedSession = ntlmSession
                    cachedServer = server
                    cacheExpiry = now + timedelta(hours=1)
                    if Logic.debug == True: print("[DEBUG] NTLM auth success, caching session.")
                    session = ntlmSession
                    headers = None # Cookies suffice
                else:
                    if Logic.debug == True: print("[DEBUG] NTLM failed ({}), falling to creds.".format(probeResponse.status_code))
                    raise requests.exceptions.HTTPError("NTLM auth failed")
            except Exception as e:
                if Logic.debug == True: print ("[WARN] NTLM probe error: {}, falling to creds.".format(e))
                useWindowsAuth = False # Force fallback

        if not session: # Creds fallback (or NTLM fail/toggle off/non-Windows)
            user = keyring.get_password("DataDoctor", "aqUser") or ''
            password = keyring.get_password("DataDoctor", "aqPassword") or ''

            if not server or not user or not password:
                print("[ERROR] Missing Aquarius credentials for fallback.")
                return {uid: {'data': [], 'label': uid} for uid in dataIDs}
            
            # Authenticate session
            authData = {'Username': user, 'EncryptedPassword': password}
            authResponse = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=authData, verify=False)

            if authResponse.status_code != 200:
                print("[ERROR] Aquarius authentication failed.")

                # Clear creds post-fall
                user = None
                password = None

                return {uid: {'data': [], 'label': uid} for uid in dataIDs}            

            token = authResponse.text.strip('"') # Strip quotes if present
            headers = {'X-Authentication-Token': token}

            # Cache creds token/session
            cachedSession = requests.Session()
            cachedSession.headers.update(headers)           
            cachedToken = token
            cachedServer = server
            cacheExpiry = now + timedelta(hours=1)
            session = cachedSession
            if Logic.debug == True: print("[DEBUG] Creds auth success, caching token.")

            # Clear creds immediately after use   
            user = None
            password = None
    
        # Clear server post-auth (but cached)
        server = None

    result = {}
    uids = dataIDs
    queryLimit = 100
    
    # Batch uids into groups of queryLimit (serial fetch per uid in group)
    for groupStart in range(0, len(uids), queryLimit):
        groupUids = uids[groupStart:groupStart + queryLimit]

        if Logic.debug == True: print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))

        for uid in groupUids:
            # Query the data (user cached server/session, explicit headers if creds)
            getUrl = f'{cachedServer}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={startDate}&QueryTo={endDate}&utcOffset={Logic.utcOffset}&GetParts=PointsOnly&format=json'
            if Logic.debug == True: print(f"[DEBUG] GET uid={uid}, url={getUrl[:50]}...,headers={headers if headers else 'None (NTLM)'}")
            
            if headers:
                response = session.get(getUrl, headers=headers, verify=False)
            else:
                response = session.get(getUrl, verify=False)
            if Logic.debug == True: print("[DEBUG] GET prep: url='{}', headers type={}, headers val={}".format(getUrl, type(headers), headers))

            try:
                readFile = json.loads(response.content)
            except Exception as e:
                print("[WARN] Aquarius fetch failed for uid '{}': {}".format(uid, e))
                result[uid] = {'data': [], 'label': uid} # Fallback label
                continue
            
            # Build label from response
            location = readFile.get('LocationIdentifier', uid)
            label = readFile.get('Label', '')
            fullLabel = f'{location} \n{label}'

            points = readFile['Points']

            if Logic.debug == True: print("[DEBUG] Fetched {} points for uid '{}'.".format(len(points), uid))

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

    if Logic.debug == True: print("[DEBUG] Returning result dict with {} UIDs.".format(len(result)))

    return result