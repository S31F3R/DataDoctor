# USBR.py

import requests
import json
import threading
import queue
from core import Oracle, Query, Config, Logic
from datetime import datetime, timedelta
from collections import defaultdict

primaryDsn = None
queryLimit = 500
maxThreads = 15

# Internal queries may use @dblink among these (verified UC/LC/YAO family).
_LINKED_HDB_ALIASES = frozenset({"lchdb", "yaohdb", "uchdb2", "uchdb"})
# No usable links from that family — always a direct session on its own worker.
_ISOLATED_HDB_ALIASES = frozenset({"kbohdb", "cuhdb", "lbohdb", "ecohdb"})


def hdbAlias(svr) -> str:
    """USBR-LCHDB|LCHDBA or USBR-LCHDB or lchdb → lchdb."""
    s = str(svr or "").strip()
    if "|" in s:
        s = s.split("|", 1)[0].strip()
    if "-" in s:
        s = s.split("-", 1)[1].strip()
    return s.lower()


def hdbAllowsDbLink(svr) -> bool:
    """True when this HDB is in the UC/LC/YAO family that shares database links."""
    return hdbAlias(svr) in _LINKED_HDB_ALIASES


def hdbIsolatedDirect(svr) -> bool:
    """True when internal queries must connect to this HDB directly (no @link)."""
    alias = hdbAlias(svr)
    if alias in _ISOLATED_HDB_ALIASES:
        return True
    if not alias:
        return False
    return alias not in _LINKED_HDB_ALIASES

def fetchAgenMap(oracleConn, schema):
    # Fetch agen map from primary dsn's hdb tables (local, no link)
    agenMap = {}
    agenQuery = f"""
        SELECT agen_id, agen_name
        FROM {schema}.hdb_agen
        ORDER BY agen_id
    """

    try:
        results = oracleConn.executeCustomQuery(agenQuery)
        agenMap = {row['AGEN_ID']: row['AGEN_NAME'] for row in results}

        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(agenMap)} agen mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch agenMap: {e}")
    return agenMap

def fetchCollectionMap(oracleConn, schema):
    # Fetch collection map from primary dsn's hdb tables (local, no link)
    collectionMap = {}
    collectionQuery = f"""
        SELECT collection_system_id, collection_system_name
        FROM {schema}.hdb_collection_system
        ORDER BY collection_system_id
    """

    try:
        results = oracleConn.executeCustomQuery(collectionQuery)
        collectionMap = {row['COLLECTION_SYSTEM_ID']: row['COLLECTION_SYSTEM_NAME'] for row in results}

        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(collectionMap)} collection mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch collectionMap: {e}")
    return collectionMap

def fetchLoadingMap(oracleConn, schema):
    # Fetch loading map from primary dsn's hdb tables (local, no link)
    loadingMap = {}
    loadingQuery = f"""
        SELECT loading_application_id, loading_application_name
        FROM {schema}.hdb_loading_application
        ORDER BY loading_application_id
    """

    try:
        results = oracleConn.executeCustomQuery(loadingQuery)
        loadingMap = {row['LOADING_APPLICATION_ID']: row['LOADING_APPLICATION_NAME'] for row in results}

        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(loadingMap)} loading mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch loadingMap: {e}")
    return loadingMap

def fetchMethodMap(oracleConn, schema):
    # Fetch method map from primary dsn's hdb tables (local, no link)
    methodMap = {}
    methodQuery = f"""
        SELECT method_id, method_name
        FROM {schema}.hdb_method
        ORDER BY method_id
    """

    try:
        results = oracleConn.executeCustomQuery(methodQuery)
        methodMap = {row['METHOD_ID']: row['METHOD_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(methodMap)} method mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch methodMap: {e}")
    return methodMap

def fetchComputationMap(oracleConn, schema, link):
    # Fetch computation map from target svr (local if svr == primary, else with link)
    computationMap = {}
    computationQuery = f"""
        SELECT computation_id, computation_name
        FROM {schema}.cp_computation{link}
        ORDER BY computation_id
    """

    try:
        results = oracleConn.executeCustomQuery(computationQuery)
        computationMap = {row['COMPUTATION_ID']: row['COMPUTATION_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(computationMap)} computation mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch computationMap: {e}")
    return computationMap

def apiRead(svr, SDIDs, startDate, endDate, interval, mrid='0', table='R'):
    if Config.debug:
        Logic.logMessage("DEBUG", f"USBR.apiRead called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, start: {startDate}, end: {endDate}, mrid: {mrid}, table='R'")

    # Map for URL only
    if interval == 'HOUR':
        tstp = 'HR'
    elif interval.startswith('INSTANT'):
        tstp = 'IN'
    elif interval == 'DAY':
        tstp = 'DY'
    elif interval == 'MONTH':
        tstp = 'MN'
    else:
        Logic.logMessage("ERROR", "Unsupported interval: {}".format(interval))
        return {}

    # Use original interval for timestamps
    timestamps = Query.buildTimestamps(startDate, endDate, interval)

    if not timestamps:
        Logic.logMessage("ERROR", "No timestamps generated - invalid dates or interval.")
        return {}

    # Parse start (with pad if periodOffset and HOUR)
    startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')

    if Config.periodOffset and interval == 'HOUR':
        startDateTime = startDateTime - timedelta(hours=1)     
    startYear = startDateTime.year
    startMonth = f'{startDateTime.month:02d}'
    startDay = f'{startDateTime.day:02d}'
    startHour = f'{startDateTime.hour:02d}'
    startMinute = f'{startDateTime.minute:02d}'

    # Parse end (no pad needed, as offset is on points)
    endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
    endYear = endDateTime.year
    endMonth = f'{endDateTime.month:02d}'
    endDay = f'{endDateTime.day:02d}'
    endHour = f'{endDateTime.hour:02d}'
    endMinute = f'{endDateTime.minute:02d}'
    queryLimit = 50
    resultDict = {}

    for groupStart in range(0, len(SDIDs), queryLimit):
        groupSDIDs = SDIDs[groupStart:groupStart + queryLimit]
        groupSDIDStr = ','.join(groupSDIDs)
        url = f'https://www.usbr.gov/pn-bin/hdb/hdb.pl?svr={svr}&SDI={groupSDIDStr}&tstp={tstp}&t1={startYear}-{startMonth}-{startDay}T{startHour}:{startMinute}&t2={endYear}-{endMonth}-{endDay}T{endHour}:{endMinute}&table={table}&mrid={mrid}&format=json'
        
        if Config.debug:
            Logic.logMessage("DEBUG", "Fetching USBR URL: {}".format(url))
        try:
            response = requests.get(url)
            response.raise_for_status()
            readFile = json.loads(response.content)
            seriesList = readFile['Series']

            if Config.debug:
                Logic.logMessage("DEBUG", "Fetched {} series entries.".format(len(seriesList)))
        except Exception as e:
            Logic.logMessage("ERROR", "USBR fetch failed: {}".format(e))
            continue
        for SDID in groupSDIDs:
            matchingSeries = None

            for series in seriesList:
                jsonSDID = series['SDI']

                if isinstance(jsonSDID, list):
                    jsonSDID = jsonSDID[0] if jsonSDID else ''
                if str(jsonSDID) == SDID:
                    matchingSeries = series
                    break
            if not matchingSeries:
                Logic.logMessage("WARN", f"No matching series for SDID '{SDID}'.")
                resultDict[SDID] = []
                continue
            dataPoints = matchingSeries['Data']

            if Config.debug:
                Logic.logMessage("DEBUG", f"Found series for '{SDID}': {len(dataPoints)} points.")
            outputData = []

            for point in dataPoints:
                value = point['v']
                dateTime = point['t']
                dateTimeParts = dateTime.split(' ')
                dateParts = dateTimeParts[0].split('/')
                hourMinuteSecond = dateTimeParts[1].split(':')
                amPm = dateTimeParts[2] if len(dateTimeParts) > 2 else ''
                year = int(dateParts[2])
                month = int(dateParts[0])
                day = int(dateParts[1])
                hour = int(hourMinuteSecond[0])
                minute = int(hourMinuteSecond[1])
                second = int(hourMinuteSecond[2]) if len(hourMinuteSecond) > 2 else 0
                dateTime = datetime(year, month, day, hour, minute, second)
                
                if Config.periodOffset and interval == 'HOUR':
                    dateTime = dateTime + timedelta(hours=1)
                if amPm == 'AM' and hour == 12:
                    dateTime = dateTime - timedelta(hours=12)
                elif amPm == 'PM' and hour < 12:
                    dateTime = dateTime + timedelta(hours=12)
                formattedTs = Query.formatTimestamp(dateTime, interval)
                outputData.append(f'{formattedTs},{value}')
            resultDict[SDID] = outputData
    if not resultDict:
        Logic.logMessage("WARN", "No data after processing all batches.")
    return resultDict

def isDbLinkError(exc):
    """True if this looks like a failed Oracle database link (not auth)."""
    if exc is None:
        return False
    markers = (
        'ORA-02019',  # connection description for remote database not found
        'ORA-02068',  # following severe error from...
        'ORA-02063',  # preceding line from...
        'ORA-02070',
        'ORA-02082',
        'ORA-02085',  # database link ... connects to ...
        'ORA-04052',
        'ORA-04054',
        'ORA-12154',  # TNS could not resolve (sometimes via link)
        'ORA-12514',
        'ORA-12541',
        'ORA-12545',
        'DATABASE LINK',
        'DBLINK',
    )
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        try:
            if Oracle.isAuthError(cur):
                return False
        except Exception:
            pass
        text = str(cur).upper() if cur is not None else ""
        if any(m in text for m in markers):
            return True
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return False


def sqlRead(svr, SDIDs, startDate, endDate, interval, mrid='0', table='R', forceDirect=False):
    """
    Read HDB data. When querying a non-primary DB, uses database link @dsn
    from the primary connection. If the link fails, retries with a direct
    connection to the target DSN (forceDirect).
    """
    global primaryDsn
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"USBR.sqlRead called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, "
            f"start: {startDate}, end: {endDate}, mrid: {mrid}, table: {table}, "
            f"forceDirect={forceDirect}",
        )

    # Parse svr to short lower if full format
    svr = hdbAlias(svr)

    isolated = hdbIsolatedDirect(svr)
    if isolated:
        forceDirect = True

    # Set primary dsn on first *linked* HDB only. Isolated HDBs never become
    # the primary (that used to make later UC/LC/YAO queries go through @link
    # from KBO/CU/LBO/ECO).
    if primaryDsn is None and not isolated:
        primaryDsn = svr

        if Config.debug:
            Logic.logMessage("DEBUG", f"Set primaryDsn to first svr: {primaryDsn}")

    # Schema from Config.hdbOracleDatabases (|SCHEMA) when present; else legacy derivation
    from core.Utils import hdbSchemaForDatabase
    targetSchema = hdbSchemaForDatabase(f'USBR-{svr.upper()}')

    # Direct connect: forced, isolated HDB, this IS the primary, or no primary yet
    useDirect = forceDirect or isolated or (primaryDsn is None) or (svr == primaryDsn)
    if useDirect:
        dsn = svr
        link = ''
        # Maps live on the same DB we're reading
        schema = targetSchema
    else:
        dsn = primaryDsn
        link = f'@{svr}'
        schema = hdbSchemaForDatabase(f'USBR-{primaryDsn.upper()}')

    # Map interval to table suffix (consistent with apiRead)
    intervalMap = {
        'HOUR': 'HOUR',
        'INSTANT:1': 'INSTANT',
        'INSTANT:15': 'INSTANT',
        'INSTANT:60': 'INSTANT',
        'DAY': 'DAY',
        'MONTH': 'MONTH',
        'YEAR': 'YEAR',
        'WATER YEAR': 'WY'
    }

    tableSuffix = intervalMap.get(interval, 'HOUR') # Default to HOUR if unknown

    # Table names
    baseTable = f'{targetSchema}.r_base{link}'  # Always r_base for metadata
    dataTable = f'{targetSchema}.{table.lower()}_{tableSuffix.lower()}{link}' # r_hour or m_hour, etc.

    # Parse dates with offset handling
    try:
        startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
        endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')

        if Config.periodOffset and interval == 'HOUR':
            startDateTime = startDateTime - timedelta(hours=1)
    except ValueError as e:
        Logic.logMessage("ERROR", f"sqlRead: Date parse failed: {e}")
        return {}

    # Calculate delta for points estimation
    if 'INSTANT:' in interval:
        minutes = int(interval.split(':')[1])
        deltaSec = minutes * 60
    elif interval == 'HOUR':
        deltaSec = 3600
    elif interval == 'DAY':
        deltaSec = 86400
    elif interval == 'MONTH':
        deltaSec = 86400 * 30.437 # Average days per month
    elif interval == 'YEAR' or interval == 'WATER YEAR':
        deltaSec = 86400 * 365.25 # Average days per year
    else:
        Logic.logMessage("WARN", f"Unsupported interval for points estimation: {interval}. Defaulting to single chunk.")
        deltaSec = (endDateTime - startDateTime).total_seconds() + 1 # Treat as one chunk
    totalSec = (endDateTime - startDateTime).total_seconds()
    totalPoints = int(totalSec / deltaSec) + 1
    numChunks = (totalPoints + queryLimit - 1) // queryLimit

    if Config.debug:
        Logic.logMessage("DEBUG", f"Estimated {totalPoints} points, splitting into {numChunks} chunks")

    # Generate sub-ranges
    subRanges = []
    chunkDurationSec = totalSec / numChunks

    for i in range(numChunks):
        subStart = startDateTime + timedelta(seconds=i * chunkDurationSec)
        subEnd = subStart + timedelta(seconds=chunkDurationSec) if i < numChunks - 1 else endDateTime
        subStartStr = subStart.strftime('%Y-%m-%d %H:%M:%S')
        subEndStr = subEnd.strftime('%Y-%m-%d %H:%M:%S')
        subRanges.append((subStartStr, subEndStr))

    if Config.debug:
        Logic.logMessage("DEBUG", f"Generated {len(subRanges)} sub-ranges")

    # R path needs agency/method/etc. name maps for Show details.
    # M / MRID path is values-only — no r_base join, no flag columns, no maps
    # (same idea as USGS legacy methodIDs: details menu works, metadata blocked).
    isMrid = table == 'M' and str(mrid) not in ('', '0', 'None')
    agenMap = {}
    collectionMap = {}
    loadingMap = {}
    methodMap = {}
    computationMap = {}
    if not isMrid:
        mapConn = Oracle.oracleConnection(dsn)
        mapConn.connect()
        agenMap = fetchAgenMap(mapConn, schema)
        collectionMap = fetchCollectionMap(mapConn, schema)
        loadingMap = fetchLoadingMap(mapConn, schema)
        methodMap = fetchMethodMap(mapConn, schema)
        computationMap = fetchComputationMap(mapConn, targetSchema, link)
        mapConn.close()

    # Determine timeCol for BETWEEN and matching
    if interval == 'HOUR' and Config.periodOffset:
        timeCol = 'end_date_time'
        timeAlias = 'END_DATE_TIME'
    else:
        timeCol = 'start_date_time'
        timeAlias = 'START_DATE_TIME'

    # Interval query template (for single SDID).
    # M_* tables lack R_* metadata columns (ORA-00904 DERIVATION_FLAGS etc.).
    # Values only + model_run_id filter; rawResponse is a no-meta sentinel.
    if isMrid:
        dataQuery = f"""
        SELECT 
          site_datatype_id AS SDID, 
          TO_CHAR(end_date_time, 'YYYY-MM-DD HH24:MI:SS') AS END_DATE_TIME,
          TO_CHAR(start_date_time, 'YYYY-MM-DD HH24:MI:SS') AS START_DATE_TIME,
          value
        FROM {dataTable}
        WHERE site_datatype_id = :1
          AND {timeCol} BETWEEN TO_DATE(:2, 'YYYY-MM-DD HH24:MI:SS') 
          AND TO_DATE(:3, 'YYYY-MM-DD HH24:MI:SS')
          AND model_run_id = :4
        ORDER BY {timeCol} ASC
        """
    else:
        dataQuery = f"""
        SELECT 
          site_datatype_id AS SDID, 
          TO_CHAR(end_date_time, 'YYYY-MM-DD HH24:MI:SS') AS END_DATE_TIME,
          TO_CHAR(start_date_time, 'YYYY-MM-DD HH24:MI:SS') AS START_DATE_TIME,
          TO_CHAR(date_time_loaded, 'YYYY-MM-DD HH24:MI:SS') AS DATE_TIME_LOADED,
          value,
          validation,
          overwrite_flag,
          method_id,
          derivation_flags
        FROM {dataTable}
        WHERE site_datatype_id = :1
          AND {timeCol} BETWEEN TO_DATE(:2, 'YYYY-MM-DD HH24:MI:SS') 
          AND TO_DATE(:3, 'YYYY-MM-DD HH24:MI:SS')
        ORDER BY {timeCol} ASC
        """

    # Base query template (metadata, only for 'R', single SDID)
    metaQuery = None

    if table == 'R':
        metaQuery = f"""
            SELECT 
              site_datatype_id AS SDID, 
              TO_CHAR(start_date_time, 'YYYY-MM-DD HH24:MI:SS') AS START_DATE_TIME,
              TO_CHAR(end_date_time, 'YYYY-MM-DD HH24:MI:SS') AS END_DATE_TIME,
              TO_CHAR(date_time_loaded, 'YYYY-MM-DD HH24:MI:SS') AS DATE_TIME_LOADED,
              value AS RBASE_VALUE,
              validation,
              overwrite_flag,
              method_id,
              agen_id,
              collection_system_id,
              loading_application_id,
              computation_id,
              data_flags
            FROM {baseTable}
            WHERE site_datatype_id = :1
              AND {timeCol} BETWEEN TO_DATE(:2, 'YYYY-MM-DD HH24:MI:SS') 
              AND TO_DATE(:3, 'YYYY-MM-DD HH24:MI:SS') 
              AND interval = '{tableSuffix.lower()}'
            ORDER BY {timeCol} ASC
        """

    # Threading setup
    resultQueue = queue.Queue()
    tasks = [(SDID, subStartStr, subEndStr) for SDID in SDIDs for subStartStr, subEndStr in subRanges]
    numTasks = len(tasks)
    numThreads = min(maxThreads, numTasks)

    if Config.debug:
        Logic.logMessage("DEBUG", f"Created {numTasks} tasks for {len(SDIDs)} SDIDs across {len(subRanges)} sub-ranges, using {numThreads} threads")

    def queryTask(SDID, subStartStr, subEndStr, threadId, oracleConn):
        """Run one (SDID, date-chunk) pair on an existing connection (no connect/close)."""
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Thread {threadId} processing task for SDID {SDID}, range {subStartStr} to {subEndStr}",
            )
        if getattr(Oracle, 'authFailureMessage', None):
            raise Oracle.OracleAuthError(Oracle.authFailureMessage)

        # Data params
        dataParams = [SDID, subStartStr, subEndStr]
        if isMrid:
            dataParams.append(mrid)

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"sqlRead thread {threadId}: Executing interval query with params {dataParams}",
            )
        # Reuse session across tasks; retry once if the network dropped the connection
        dataResults = oracleConn.executeCustomQueryWithRetry(dataQuery, params=dataParams)

        # --- MRID / model: values only, no metadata list ---
        if isMrid:
            outputData = []
            for row in dataResults or []:
                timeKey = row.get(timeAlias)
                value = row.get('VALUE')
                if value is None or not timeKey:
                    continue
                try:
                    dateTime = datetime.strptime(str(timeKey), '%Y-%m-%d %H:%M:%S')
                    formattedTs = Query.formatTimestamp(dateTime, interval)
                    outputData.append(f'{formattedTs},{value}')
                except ValueError as e:
                    Logic.logMessage(
                        "WARN",
                        f"sqlRead thread {threadId}: Invalid timeKey skipped for "
                        f"SDID {SDID}: {timeKey} ({e})",
                    )
            # Sentinel for Show details (mirrors USGS legacy "no metadata" UX)
            resultQueue.put((
                SDID,
                {
                    'data': outputData,
                    'rawResponse': {
                        'kind': 'mrid',
                        'mrid': str(mrid),
                        'sdid': str(SDID),
                    },
                },
            ))
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"sqlRead thread {threadId}: MRID values-only "
                    f"{len(outputData)} points for SDID {SDID} mrid={mrid}",
                )
            return

        # Group interval data by timeKey
        dataByTime = {row[timeAlias]: row for row in dataResults}

        # Fetch base metadata if applicable
        metaResults = []
        metaByTime = {}

        if table == 'R':
            metaParams = [SDID, subStartStr, subEndStr]

            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"sqlRead thread {threadId}: Executing base query with params {metaParams}",
                )
            metaResults = oracleConn.executeCustomQueryWithRetry(metaQuery, params=metaParams)
            metaByTime = {row[timeAlias]: row for row in metaResults}

        # Process for this SDID and sub-range
        outputData = []
        mergedMeta = []

        allTimes = sorted(set(list(dataByTime.keys()) + list(metaByTime.keys())))

        for timeKey in allTimes:
            intRow = dataByTime.get(timeKey, {})
            baseRow = metaByTime.get(timeKey, {})

            # Value for table: interval if present, else base (but prefer interval per request)
            value = intRow.get('VALUE') if intRow else baseRow.get('RBASE_VALUE') if baseRow else None

            if value is None:
                continue  # Skip if no value

            # Format timestamp from timeKey (interval-aware display: day/month/year)
            try:
                dateTime = datetime.strptime(timeKey, '%Y-%m-%d %H:%M:%S')
                formattedTs = Query.formatTimestamp(dateTime, interval)
                valStr = str(value) if value is not None else ''
                outputData.append(f'{formattedTs},{valStr}')
            except ValueError as e:
                Logic.logMessage(
                    "WARN",
                    f"sqlRead thread {threadId}: Invalid timeKey skipped for SDID {SDID}: {timeKey} ({e})",
                )
                continue

            # Merge metadata: base as base, override common tags with interval if present/not None
            mergedRow = baseRow.copy() if baseRow else {}
            mergedRow.update({k: v for k, v in intRow.items() if v is not None})
            mergedRow['SDID'] = str(SDID)
            mergedRow['INTERVAL'] = tableSuffix.lower()

            if intRow:
                mergedRow['INTERVAL_VALUE'] = intRow.get('VALUE')
            if baseRow:
                mergedRow['RBASE_VALUE'] = baseRow.get('RBASE_VALUE')

            # Build display dict with friendly keys and name replacements
            displayMeta = {}
            displayMeta['SDID'] = mergedRow.get('SDID', '')
            displayMeta['Interval'] = mergedRow.get('INTERVAL', '')
            displayMeta['Start Date/Time'] = mergedRow.get('START_DATE_TIME', '')
            displayMeta['End Date/Time'] = mergedRow.get('END_DATE_TIME', '')
            displayMeta['Date/Time Loaded'] = mergedRow.get('DATE_TIME_LOADED', '')
            displayMeta['Interval Value'] = (
                str(mergedRow.get('INTERVAL_VALUE', ''))
                if mergedRow.get('INTERVAL_VALUE') is not None
                else ''
            )
            displayMeta['Base Value'] = (
                str(mergedRow.get('RBASE_VALUE', ''))
                if mergedRow.get('RBASE_VALUE') is not None
                else ''
            )
            displayMeta['Validation'] = mergedRow.get('VALIDATION', '') or ''
            displayMeta['Overwrite Flag'] = mergedRow.get('OVERWRITE_FLAG', '') or ''
            displayMeta['Method'] = methodMap.get(mergedRow.get('METHOD_ID'), '') or ''
            displayMeta['Agency Name'] = agenMap.get(mergedRow.get('AGEN_ID'), '') or ''
            displayMeta['Collection System'] = collectionMap.get(mergedRow.get('COLLECTION_SYSTEM_ID'), '') or ''
            displayMeta['Loading Application'] = loadingMap.get(mergedRow.get('LOADING_APPLICATION_ID'), '') or ''
            compId = mergedRow.get('COMPUTATION_ID')
            compName = computationMap.get(compId, '') if compId is not None else ''
            displayMeta['Computation'] = compName
            displayMeta['Computation ID'] = str(compId) if compId is not None else ''
            displayMeta['Data Flags'] = (
                mergedRow.get('DATA_FLAGS', '') or mergedRow.get('DERIVATION_FLAGS', '') or ''
            )

            mergedMeta.append(displayMeta)

        resultQueue.put((SDID, {'data': outputData, 'rawResponse': mergedMeta}))

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"sqlRead thread {threadId}: Processed {len(outputData)} data points and "
                f"{len(mergedMeta)} merged meta rows for SDID {SDID}",
            )

    # Start threads — one Oracle session per worker, reused across all its tasks
    taskQueue = queue.Queue()
    for task in tasks:
        taskQueue.put(task)
    threads = []

    workerErrors = []
    workerErrorsLock = threading.Lock()

    def worker(threadId):
        """
        Option C: open one connection for this worker, run many (SDID, chunk) tasks,
        close when the queue is empty. Avoids connect/close per task over the WAN.
        """
        oracleConn = None
        tasksDone = 0
        try:
            if getattr(Oracle, 'authFailureMessage', None):
                raise Oracle.OracleAuthError(Oracle.authFailureMessage)

            oracleConn = Oracle.oracleConnection(dsn)
            oracleConn.connect()
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"sqlRead worker {threadId}: opened reusable connection to {dsn}",
                )

            while True:
                try:
                    SDID, subStartStr, subEndStr = taskQueue.get_nowait()
                except queue.Empty:
                    break
                try:
                    queryTask(SDID, subStartStr, subEndStr, threadId, oracleConn)
                    tasksDone += 1
                except Exception as e:
                    Logic.logException(
                        f"sqlRead worker {threadId} failed for SDID {SDID} "
                        f"range {subStartStr}-{subEndStr}",
                        e,
                    )
                    with workerErrorsLock:
                        workerErrors.append(e)
                    # Auth failure: stop this worker; other workers will hit the same block
                    if isinstance(e, Oracle.OracleAuthError) or Oracle.isAuthError(e):
                        break
                finally:
                    try:
                        taskQueue.task_done()
                    except Exception:
                        pass
        except Exception as e:
            # Connect / setup failure before any tasks
            Logic.logException(f"sqlRead worker {threadId} failed to start session", e)
            with workerErrorsLock:
                workerErrors.append(e)
        finally:
            if oracleConn is not None:
                try:
                    oracleConn.close()
                except Exception:
                    pass
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"sqlRead worker {threadId}: closed connection after {tasksDone} task(s)",
                    )

    for i in range(numThreads):
        t = threading.Thread(target=worker, args=(i,), name=f"HDB-sqlRead-{i}")
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Collect results. R path: rawResponse is a list of meta rows (extend).
    # MRID path: rawResponse is a single dict sentinel (kind=mrid) — assign, never extend.
    resultDict = defaultdict(lambda: {'data': [], 'rawResponse': [] if not isMrid else None})

    while not resultQueue.empty():
        SDID, partial = resultQueue.get()
        SDIDStr = str(SDID)
        resultDict[SDIDStr]['data'].extend(partial.get('data') or [])
        raw = partial.get('rawResponse')
        if isinstance(raw, dict):
            resultDict[SDIDStr]['rawResponse'] = raw
        elif isinstance(raw, list):
            existing = resultDict[SDIDStr]['rawResponse']
            if not isinstance(existing, list):
                resultDict[SDIDStr]['rawResponse'] = list(raw)
            else:
                existing.extend(raw)

    if workerErrors and not resultDict:
        # Linked query failed entirely → retry with a direct session to the
        # target DSN. Any worker error (not only ORA-02019) — the previous
        # isDbLinkError filter was missing real link failures.
        if link and not forceDirect:
            Logic.logMessage(
                "WARN",
                f"sqlRead: database link to {svr} failed; retrying with direct connection "
                f"(no @{svr}): {workerErrors[0]}",
            )
            return sqlRead(
                svr, SDIDs, startDate, endDate, interval,
                mrid=mrid, table=table, forceDirect=True,
            )
        # Nothing succeeded — surface the first worker failure (e.g. client setup)
        raise workerErrors[0]
    if workerErrors and Config.debug:
        Logic.logMessage(
            "WARN",
            f"sqlRead: {len(workerErrors)} worker task(s) failed; continuing with partial results "
            f"for {len(resultDict)} SDIDs",
        )
    # Partial results over a link: retry missing SDIDs on a direct connection
    if (
        link
        and not forceDirect
        and workerErrors
        and any(str(s) not in resultDict for s in SDIDs)
    ):
        Logic.logMessage(
            "WARN",
            f"sqlRead: partial link failure for {svr}; retrying missing SDIDs via direct connect",
        )
        missing = [s for s in SDIDs if str(s) not in resultDict]
        try:
            directPartial = sqlRead(
                svr, missing, startDate, endDate, interval,
                mrid=mrid, table=table, forceDirect=True,
            )
            if isinstance(directPartial, dict):
                resultDict.update(directPartial)
        except Exception as e:
            Logic.logException("sqlRead: direct fallback for missing SDIDs failed", e)

    # Sort per SDID (R meta is a list of row dicts; MRID rawResponse is a kind=mrid sentinel dict)
    for SDIDStr in resultDict:
        resultDict[SDIDStr]['data'].sort(
            key=lambda x: Query.parseDisplayTimestamp(x.split(',')[0]) or datetime.min
        )
        raw = resultDict[SDIDStr].get('rawResponse')
        if isinstance(raw, list):
            resultDict[SDIDStr]['rawResponse'].sort(
                key=lambda m: datetime.strptime(
                    m.get('Start Date/Time') or '1900-01-01 00:00:00',
                    '%Y-%m-%d %H:%M:%S',
                )
            )

    # Apply gapCheck
    timestamps = Query.buildTimestamps(startDate, endDate, interval)

    for SDID in SDIDs:
        SDIDStr = str(SDID)

        if SDIDStr in resultDict:
            resultDict[SDIDStr]['data'] = Query.gapCheck(
                timestamps, resultDict[SDIDStr]['data'], SDIDStr, interval=interval
            )
            
            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Post-gapCheck {len(resultDict[SDIDStr]['data'])} rows for SDID {SDID}")

    if not resultDict:
        Logic.logMessage("WARN", "sqlRead: No data after processing")
    return dict(resultDict)