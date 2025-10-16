import requests
import json
import keyring
from datetime import datetime, timedelta
import Logic # For globals like debug and utcOffset
import platform # For OS check
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# Module-level cache (secure in-memory only, no disk)
cachedSession = None
cachedToken = None
cachedServer = None
cacheExpiry = None # datetime for TTL (1hr)

def getAdSession(server):
    """Fetch AD auth session via headless Edge, cache cookies in keyring."""
    if Logic.debug == True: print("[DEBUG] Initiating AD auth session probe.")
    if platform.system() != 'Windows':
        if Logic.debug == True: print("[DEBUG] AD auth skipped on non-Windows.")
        return None

    try:
        # Setup headless Edge
        edgeOptions = EdgeOptions()
        edgeOptions.add_argument("--headless")
        edgeOptions.add_argument("--disable-gpu") # Stability on headless
        edgeOptions.add_argument("--no-sandbox") # Safe for Manjaro/Win
        driver = webdriver.Edge(EdgeChromiumDriverManager().install(), options=edgeOptions)

        # Navigate to login page
        loginUrl = f'{server}/AQUARIUS'
        driver.get(loginUrl)

        # Find and click the Windows Button (by name, direct body input)
        button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@name='Windows Button']"))
        )
        button.click() # Submit triggers AD auth

        # Wait for redirect to Springboard dashboard (success check)
        WebDriverWait(driver, 10).until(
            EC.url_contains('/AQUARIUS/apps/springboard/app/#/locations')
        )

        # Extract all cookies
        cookies = driver.get_cookies()
        cookieDict = {c['name']: c['value'] for c in cookies}
        expiry = datetime.now() + timedelta(hours=1) # 1hr TTL

        # Cache in keyring (secure JSON, same as creds)
        keyring.set_password("DataDoctor", "aqAdCookies", json.dumps({'cookies': cookieDict, 'expiry': expiry.isoformat()}))
        if Logic.debug == True: print("[DEBUG] AD auth success, cookies cached.")

        driver.quit()
        return cookieDict

    except Exception as e:
        if Logic.debug == True: print("[WARN] AD auth failed: {}, falling to creds.".format(e))
        if 'driver' in locals():
            driver.quit()
        return None

def apiRead(dataIDs, startDate, endDate, interval):
    global cachedSession, cachedToken, cachedServer, cacheExpiry # For secure reuse/clear
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
    startDateIso = f'{startYear}-{startMonth}-{startDay} {startHour}:{startMinute}'
    endDateIso = f'{endYear}-{endMonth}-{endDay} {endHour}:{endMinute}'

    # Apply utc offset for Aquarius query
    startDateTimeOffset = startDateTime - timedelta(hours=Logic.utcOffset)
    endDateTimeOffset = endDateTime - timedelta(hours=Logic.utcOffset)

    startDateTimeOffset = startDateTimeOffset - timedelta(hours=1)
    endDateTimeOffset = endDateTimeOffset + timedelta(minutes=1)

    # Re-pad after offset
    startMonth = f'{startDateTimeOffset.month:02d}'
    startDay = f'{startDateTimeOffset.day:02d}'
    startHour = f'{startDateTimeOffset.hour:02d}'
    startMinute = f'{startDateTimeOffset.minute:02d}'
    endMonth = f'{endDateTimeOffset.month:02d}'
    endDay = f'{endDateTimeOffset.day:02d}'
    endHour = f'{endDateTimeOffset.hour:02d}'
    endMinute = f'{endDateTimeOffset.minute:02d}'

    # Build offset ISO
    startDate = f'{startDateTimeOffset.year}-{startMonth}-{startDay} {startHour}:{startMinute}'
    endDate = f'{endDateTimeOffset.year}-{endMonth}-{endDay} {endHour}:{endMinute}'

    # Check cache validity (1hr TTL, secure expiry)
    now = datetime.now()
    if cachedSession and cachedServer and cacheExpiry and now < cacheExpiry:
        if Logic.debug == True: print("[DEBUG] Using cached session/server.")
        session = cachedSession
        if cachedToken: # Creds mode
            headers = {'X-Authentication-Token': cachedToken}
        else: # AD mode
            headers = None
    else:
        # Clear expired cache
        cachedSession = None
        cachedToken = None
        cachedServer = None
        cacheExpiry = None
        session = None
        headers = None

        # Load server
        server = keyring.get_password("DataDoctor", "aqServer") or ''
        if not server:
            print("[ERROR] Missing Aquarius server.")
            return {uid: {'data': [], 'label': uid} for uid in dataIDs}

        # Try AD auth first (Windows only)
        if platform.system() == 'Windows' and dataIDs:
            if Logic.debug == True: print("[DEBUG] Probing AD auth via headless Edge.")
            cachedCookies = getAdSession(server)
            if cachedCookies:
                session = requests.Session()
                for name, value in cachedCookies.items():
                    session.cookies.set(name, value)
                cachedSession = session
                cachedServer = server
                cacheExpiry = datetime.fromisoformat(cachedCookies.get('expiry', (now + timedelta(hours=1)).isoformat()))
                headers = None # Cookies handle auth
                if Logic.debug == True: print("[DEBUG] AD auth success, caching session.")

        if not session: # Creds fallback (or AD fail/non-Win/empty dataIDs)
            user = keyring.get_password("DataDoctor", "aqUser") or ''
            password = keyring.get_password("DataDoctor", "aqPassword") or ''

            if not user or not password:
                print("[ERROR] Missing Aquarius credentials for fallback.")
                return {uid: {'data': [], 'label': uid} for uid in dataIDs}

            # Authenticate session
            authData = {'Username': user, 'EncryptedPassword': password}
            authResponse = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=authData, verify=False)

            if authResponse.status_code != 200:
                print("[ERROR] Aquarius authentication failed.")
                # Clear creds post-fail
                user = None
                password = None
                return {uid: {'data': [], 'label': uid} for uid in dataIDs}

            token = authResponse.text.strip('"') # Strip quotes if present
            headers = {'X-Authentication-Token': token}

            # Cache creds session/token
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
            # Query the data (use cached server/session, conditional headers for creds/AD)
            getUrl = f'{cachedServer}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={startDate}&QueryTo={endDate}&utcOffset={Logic.utcOffset}&GetParts=PointsOnly&format=json'
            if headers:
                response = session.get(getUrl, headers=headers, verify=False)
            else:
                response = session.get(getUrl, verify=False)

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