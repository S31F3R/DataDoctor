# Aquarius.py

import ssl
import requests
import json
import keyring
import os
import threading
import queue
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from core import Logic, Config, Query

queryLimit = 30000 # Configurable max points per API call
maxThreads = 50 # Configurable max number of threads

# Aquarius is internal (VPN). Do not spam this if several queries fall back.
_unverifiedWarned = False


class _SslAdapter(HTTPAdapter):
    """urllib3 uses this SSLContext (OS trust store), not certifi."""

    def __init__(self, ssl_context=None, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        if self._ssl_context is not None:
            pool_kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        if self._ssl_context is not None:
            proxy_kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _httpsSession(ssl_context=None, verify=True):
    session = requests.Session()
    if ssl_context is not None:
        session.mount("https://", _SslAdapter(ssl_context=ssl_context))
    session.verify = verify
    return session


def _verifiedSslContext(certPath):
    """
    Windows/macOS/Linux OS CA store (not Mozilla certifi).
    Optional certs/aquarius.pem is extra CAs — prefer the issuing CA, not the
    yearly server leaf, so machines do not need a new file each rotation.
    """
    ctx = ssl.create_default_context()
    if certPath and os.path.isfile(certPath):
        try:
            ctx.load_verify_locations(cafile=certPath)
        except Exception as e:
            Logic.logMessage("WARN", f"Aquarius: could not load {certPath}: {e}")
    return ctx


def _warnUnverified():
    global _unverifiedWarned
    if _unverifiedWarned:
        return
    _unverifiedWarned = True
    Logic.logMessage(
        "WARN",
        "Aquarius TLS: OS trust store and certs/ failed; connecting without "
        "certificate verification. Traffic is still HTTPS. Aquarius is "
        "internal-only (VPN). To verify without a yearly file on every PC, "
        "put the issuing CA in the Windows certificate store (Group Policy) "
        "or as certs/aquarius.pem (the CA, not the server leaf).",
    )


def _httpsServer(server: str) -> str:
    """Force https:// on the Aquarius base URL. Empty if nothing usable."""
    s = (server or "").strip().rstrip("/")
    if not s:
        return ""
    low = s.lower()
    if low.startswith("http://"):
        s = "https://" + s[7:]
    elif not low.startswith("https://"):
        s = "https://" + s
    return s


def authenticate():
    """
    Log in with keyring credentials and the same TLS policy as queries.
    Returns {server, headers, sslContext, verifyMode} or None.
    """
    server = _httpsServer(keyring.get_password("DataDoctor", "aqServer") or '')
    user = keyring.get_password("DataDoctor", "aqUser") or ''
    password = keyring.get_password("DataDoctor", "aqPassword") or ''

    if not server or not user or not password:
        Logic.logMessage("ERROR", "Missing Aquarius credentials.")
        return None

    authData = {'Username': user, 'EncryptedPassword': password}
    certPath = Logic.ensureAquariusPem()
    sslContext = None
    verifyMode = True
    authSession = None
    authResponse = None

    for attempt in ('verified', 'unverified'):
        session = None
        try:
            if attempt == 'verified':
                sslContext = _verifiedSslContext(certPath)
                verifyMode = True
                session = _httpsSession(ssl_context=sslContext, verify=True)
            else:
                sslContext = None
                verifyMode = False
                session = _httpsSession(ssl_context=None, verify=False)
            authResponse = session.post(
                f'{server}/AQUARIUS/Provisioning/v1/session',
                data=authData,
                timeout=30,
            )
            authResponse.raise_for_status()
            if attempt == 'unverified':
                _warnUnverified()
            elif Config.debug:
                Logic.logMessage("DEBUG", "Aquarius authentication succeeded with OS/certs TLS")
            authSession = session
            break
        except requests.exceptions.SSLError as e:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            if Config.debug:
                Logic.logMessage("DEBUG", f"SSL error on Aquarius {attempt}: {e}")
            continue
        except requests.exceptions.RequestException as e:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            Logic.logMessage("ERROR", f"Authentication failed: {e}")
            return None
    else:
        Logic.logMessage("ERROR", "Aquarius TLS failed (OS store, certs/, and unverified).")
        return None
    token = authResponse.text.strip('"')
    headers = {'X-Authentication-Token': token}
    if authSession is not None:
        try:
            authSession.close()
        except Exception:
            pass
    return {
        'server': server,
        'headers': headers,
        'sslContext': sslContext,
        'verifyMode': verifyMode,
    }


def publishGet(auth, route, params=None, timeout=60):
    """GET /AQUARIUS/Publish/v2{route}. Raises on HTTP errors."""
    if not route.startswith('/'):
        route = '/' + route
    http = _httpsSession(ssl_context=auth['sslContext'], verify=auth['verifyMode'])
    try:
        response = http.get(
            f"{auth['server']}/AQUARIUS/Publish/v2{route}",
            headers=auth['headers'],
            params=params or {},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    finally:
        try:
            http.close()
        except Exception:
            pass


def isLocationUniqueId(text):
    s = (text or '').strip().replace('-', '')
    return len(s) == 32 and all(c in '0123456789abcdefABCDEF' for c in s)


def isPublishedSeries(series):
    value = (series or {}).get('Publish')
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ('true', 'yes', '1'):
        return True
    return False


def locationIdentifierOf(location):
    if not isinstance(location, dict):
        return ''
    return str(
        location.get('Identifier')
        or location.get('LocationIdentifier')
        or ''
    ).strip()


def locationNameOf(location):
    if not isinstance(location, dict):
        return ''
    return str(
        location.get('LocationName')
        or location.get('Name')
        or locationIdentifierOf(location)
    ).strip()


def seriesLabelOf(series):
    """Time-series Label (dictionary commonName). Falls back to Identifier's Label part."""
    if not isinstance(series, dict):
        return ''
    label = str(series.get('Label') or '').strip()
    if label:
        return label
    ident = str(series.get('Identifier') or '').strip()
    if '@' in ident:
        left = ident.rsplit('@', 1)[0]
        if '.' in left:
            return left.split('.', 1)[1].strip()
    return ''


def locationDescriptionList(auth):
    data = publishGet(auth, '/GetLocationDescriptionList', timeout=120)
    return [d for d in (data.get('LocationDescriptions') or []) if isinstance(d, dict)]


def locationLookup(auth):
    """Identifier → stub dict with Identifier / LocationName."""
    out = {}
    for desc in locationDescriptionList(auth):
        ident = locationIdentifierOf(desc)
        if ident:
            out[ident] = desc
    return out


def publishedSeriesAll(auth):
    """
    All published time-series. Prefer one Publish=true list; if that call
    fails, walk every location (slower).
    """
    try:
        data = publishGet(
            auth,
            '/GetTimeSeriesDescriptionList',
            {'Publish': True},
            timeout=180,
        )
        series = data.get('TimeSeriesDescriptions') or []
        return [s for s in series if isinstance(s, dict) and isPublishedSeries(s)]
    except requests.exceptions.RequestException as e:
        Logic.logMessage(
            "WARN",
            f"GetTimeSeriesDescriptionList without location failed ({e}); "
            "walking locations",
        )
    rows = []
    for desc in locationDescriptionList(auth):
        ident = locationIdentifierOf(desc)
        if not ident:
            continue
        try:
            rows.extend(publishedSeriesAtLocation(auth, ident))
        except requests.exceptions.RequestException as e:
            Logic.logMessage("WARN", f"published series at {ident!r} failed: {e}")
    return rows


def resolveLocation(auth, location):
    """
    Resolve a location identifier or 32-char UniqueId to GetLocationData.
    """
    loc = (location or '').strip()
    if not loc:
        return None
    try:
        data = publishGet(auth, '/GetLocationData', {'LocationIdentifier': loc})
        if isinstance(data, dict) and (locationIdentifierOf(data) or data.get('UniqueId')):
            return data
    except requests.exceptions.RequestException as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"GetLocationData({loc!r}) failed: {e}")
    if not isLocationUniqueId(loc):
        return None
    needle = loc.replace('-', '').lower()
    try:
        listing = publishGet(auth, '/GetLocationDescriptionList', timeout=120)
    except requests.exceptions.RequestException as e:
        Logic.logMessage("ERROR", f"GetLocationDescriptionList failed: {e}")
        return None
    for desc in listing.get('LocationDescriptions') or []:
        uid = str(desc.get('UniqueId') or '').replace('-', '').lower()
        if uid != needle:
            continue
        ident = locationIdentifierOf(desc)
        if not ident:
            return desc
        try:
            return publishGet(auth, '/GetLocationData', {'LocationIdentifier': ident})
        except requests.exceptions.RequestException:
            return desc
    return None


def publishedSeriesAtLocation(auth, locationIdentifier):
    """Time-series at a location with Publish checked (API filter + client check)."""
    ident = (locationIdentifier or '').strip()
    if not ident:
        return []
    data = publishGet(
        auth,
        '/GetTimeSeriesDescriptionList',
        {'LocationIdentifier': ident, 'Publish': True},
    )
    series = data.get('TimeSeriesDescriptions') or []
    return [s for s in series if isinstance(s, dict) and isPublishedSeries(s)]


def matchValuePrecision(parameter):
    """Exact Identifier match in valuePrecision.json (case-insensitive). Else ''."""
    ident = (parameter or '').strip()
    if not ident:
        return ''
    _ordered, byId = Logic.loadAquariusRoundingSpecs()
    if ident in byId:
        return ident
    for key in byId:
        if key.lower() == ident.lower():
            return key
    return ''


def apiRead(dataIDs, startDate, endDate, interval):
    if Config.debug:
        Logic.logMessage("DEBUG", "Aquarius.apiRead called with dataIDs: {}, interval: {}, start: {}, end: {}".format(dataIDs, interval, startDate, endDate))

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

    # Apply utc offset for Aquarius query (keep exact)
    offsetHours = Logic.getUtcOffsetInt(Config.utcOffset)
    startDateTime = startDateTime - timedelta(hours=offsetHours)
    endDateTime = endDateTime - timedelta(hours=offsetHours) + timedelta(minutes=1)

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

    auth = authenticate()
    if not auth:
        return {uid: {'data': [], 'label': uid, 'rawResponse': {}} for uid in dataIDs}
    server = auth['server']
    headers = auth['headers']
    sslContext = auth['sslContext']
    verifyMode = auth['verifyMode']

    # Calculate total points
    totalDuration = endDateTime - startDateTime
    
    if interval == 'HOUR':
        delta = timedelta(hours=1)
    elif interval.startswith('INSTANT:'):
        minutes = int(interval.split(':')[1])
        delta = timedelta(minutes=minutes)
    elif interval == 'DAY':
        delta = timedelta(days=1)
    else:
        Logic.logMessage("ERROR", f"Unsupported interval: {interval}")
        return {uid: {'data': [], 'label': uid, 'rawResponse': {}} for uid in dataIDs}
    totalPoints = int(totalDuration.total_seconds() / delta.total_seconds()) + 1
    numChunks = (totalPoints + queryLimit - 1) // queryLimit

    if Config.debug:
        Logic.logMessage("DEBUG", f"Estimated {totalPoints} points, splitting into {numChunks} chunks of ~{queryLimit} points each")

    # Generate sub-ranges
    subRanges = []
    chunkDuration = totalDuration / numChunks

    for i in range(numChunks):
        subStart = startDateTime + i * chunkDuration
        subEnd = subStart + chunkDuration if i < numChunks - 1 else endDateTime
        subStartStr = subStart.strftime('%Y-%m-%d %H:%M')
        subEndStr = subEnd.strftime('%Y-%m-%d %H:%M')
        subRanges.append((subStartStr, subEndStr))

    if Config.debug:
        Logic.logMessage("DEBUG", f"Generated {len(subRanges)} sub-ranges: {[(s, e) for s, e in subRanges[:3]]}")

    # Threading setup
    resultQueue = queue.Queue()
    tasks = [(uid, subStart, subEnd) for uid in dataIDs for subStart, subEnd in subRanges]
    numTasks = len(tasks)
    numThreads = min(maxThreads, numTasks)

    if Config.debug:
        Logic.logMessage("DEBUG", f"Created {numTasks} tasks for {len(dataIDs)} UIDs across {len(subRanges)} sub-ranges, using {numThreads} threads")

    def queryTask(uid, subStart, subEnd, threadId, http):
        if Config.debug:
            Logic.logMessage("DEBUG", f"Thread {threadId} processing task for UID {uid}, range {subStart} to {subEnd}")
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
        response = http.get(
            f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid}&QueryFrom={subStartStr}&QueryTo={subEndStr}&utcOffset={offsetHours}&GetParts=All&format=json',
            headers=headers, timeout=60,
        )

        try:
            readFile = json.loads(response.content)
        except Exception as e:
            Logic.logMessage("WARN", f"Aquarius fetch failed for UID '{uid}' in thread {threadId}, range {subStart} to {subEnd}: {e}")
            resultQueue.put((uid, {'data': [], 'label': uid, 'rawResponse': {}}))
            return
        location = readFile.get('LocationIdentifier', uid)
        label = readFile.get('Label', '')
        fullLabel = f'{label} \n{location}'
        points = readFile['Points']

        if Config.debug:
            Logic.logMessage("DEBUG", f"Thread {threadId} fetched {len(points)} points for UID '{uid}', range {subStart} to {subEnd}")
        outputData = []

        for point in points:
            date = point['Timestamp']
            parseDate = date.split('T')
            parseDate[1] = parseDate[1].split('.')[0]
            dateTime = datetime.fromisoformat(f'{parseDate[0]} {parseDate[1]}')
            formattedTs = Query.formatTimestamp(dateTime, interval)
            value = point['Value'].get('Numeric', None)

            if value is not None:
                outputData.append(f'{formattedTs},{value}')
        resultQueue.put((uid, {'data': outputData, 'label': fullLabel, 'rawResponse': readFile}))

        if Config.debug:
            Logic.logMessage("DEBUG", f"Thread {threadId} completed task for UID {uid} with {len(outputData)} points")
            
    # Start threads
    taskQueue = queue.Queue()
    for task in tasks: taskQueue.put(task)
    threads = []

    def worker(threadId):
        http = _httpsSession(ssl_context=sslContext, verify=verifyMode)
        try:
            while True:
                try:
                    uid, subStart, subEnd = taskQueue.get_nowait()
                    queryTask(uid, subStart, subEnd, threadId, http)
                    taskQueue.task_done()
                except queue.Empty:
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"Thread {threadId} found no more tasks")
                    break
        finally:
            try:
                http.close()
            except Exception:
                pass
    for i in range(numThreads):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

        if Config.debug:
            Logic.logMessage("DEBUG", f"Started thread {i} for task processing")
    for t in threads:
        t.join()

        if Config.debug:
            Logic.logMessage("DEBUG", f"Thread {threads.index(t)} joined")
    result = {}

    while not resultQueue.empty():
        uid, data = resultQueue.get()
        if uid in result:
            result[uid]['data'].extend(data['data'])
            if 'rawResponse' not in result[uid] and 'rawResponse' in data:
                result[uid]['rawResponse'] = data['rawResponse']
        else:
            result[uid] = data
    for uid in result:
        result[uid]['data'].sort(
            key=lambda x: Query.parseDisplayTimestamp(x.split(',')[0]) or datetime.min
        )
    if Config.debug:
        Logic.logMessage("DEBUG", f"Combined results from {numTasks} tasks with {len(result)} UIDs")
    for uid in dataIDs:
        if uid not in result:
            result[uid] = {'data': [], 'label': uid, 'rawResponse': {}}

            if Config.debug:
                Logic.logMessage("DEBUG", f"Added empty result for UID {uid}")
    server = None
    
    if Config.debug:
        Logic.logMessage("DEBUG", f"Returning result dict with {len(result)} UIDs")
    return result