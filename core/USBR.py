# USBR.py

import requests
import json
from core import Oracle, Query, Config, Logic
from datetime import datetime, timedelta
from collections import defaultdict
from functools import lru_cache

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
                formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
                outputData.append(f'{formattedTs},{value}')
            resultDict[SDID] = outputData
    if not resultDict:
        Logic.logMessage("WARN", "No data after processing all batches.")
    return resultDict

def sqlRead(svr, SDIDs, startDate, endDate, interval, mrid='0', table='R'):
    if Config.debug: Logic.logMessage("DEBUG", f"USBR.sqlRead called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, start: {startDate}, end: {endDate}, mrid: {mrid}, table: {table}")

    # Parse svr to short lower if full format
    if '-' in svr:
        svr = svr.split('-')[1].lower()

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

    # Derive schema and link from svr
    schema = svr.upper().rstrip('2') + 'A' if svr.endswith('2') else svr.upper() + 'A'
    link = f'@{svr}'

    # Table names
    baseTable = f'{schema}.r_base{link}' # Always r_base for metadata
    dataTable = f'{schema}.{table.lower()}_{tableSuffix.lower()}{link}' # r_hour or m_hour, etc.

    # Parse dates with offset handling
    try:
        startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
        endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
        
        if Config.periodOffset and interval == 'HOUR':
            startDateTime = startDateTime - timedelta(hours=1)
    except ValueError as e:
        Logic.logMessage("ERROR", f"sqlRead: Date parse failed: {e}")
        return {}

    startStr = startDateTime.strftime('%Y-%m-%d %H:%M:%S')
    endStr = endDateTime.strftime('%Y-%m-%d %H:%M:%S')

    # Build placeholders for SDIDs
    if not SDIDs:
        Logic.logMessage("WARN", "sqlRead: No SDIDs provided")
        return {}
    sdidPlaceholders = ','.join([f':{i+1}' for i in range(len(SDIDs))])

    # Determine time_col for BETWEEN and matching
    if interval == 'HOUR' and Config.periodOffset:
        timeCol = 'end_date_time'
        timeAlias = 'END_DATE_TIME'
    else:
        timeCol = 'start_date_time'
        timeAlias = 'START_DATE_TIME'

    # Interval query
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
        WHERE site_datatype_id in ({sdidPlaceholders})
          AND {timeCol} BETWEEN TO_DATE(:{len(SDIDs)+1}, 'YYYY-MM-DD HH24:MI:SS') 
          AND TO_DATE(:{len(SDIDs)+2}, 'YYYY-MM-DD HH24:MI:SS')
        ORDER BY SDID ASC, {timeCol} ASC
    """
    dataParams = SDIDs + [startStr, endStr]
    if table == 'M' and mrid != '0':
        dataQuery = dataQuery.replace('ORDER BY', f"AND model_run_id = :{len(SDIDs)+3}\nORDER BY")
        dataParams.append(mrid)

    # Base query (metadata, only for 'R')
    metaResults = [] # Default empty
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
            WHERE site_datatype_id in ({sdidPlaceholders})
              AND {timeCol} BETWEEN TO_DATE(:{len(SDIDs)+1}, 'YYYY-MM-DD HH24:MI:SS') 
              AND TO_DATE(:{len(SDIDs)+2}, 'YYYY-MM-DD HH24:MI:SS') 
              AND interval = '{tableSuffix.lower()}'
            ORDER BY SDID ASC, {timeCol} ASC
        """
        metaParams = SDIDs + [startStr, endStr]

    # Execute queries
    resultDict = {}
    oracleConn = None

    try:
        # Always connect to 'lchdb' and use links for target svr
        dsn = 'lchdb'

        oracleConn = Oracle.oracleConnection(dsn)
        conn = oracleConn.connect()

        # Fetch lookups (caches per svr)
        lookups = fetchLookups(conn, svr)

        # Fetch interval data (always)
        if Config.debug: 
            Logic.logMessage("DEBUG", f"sqlRead: Executing interval query: {dataQuery} with params {dataParams}")
        dataResults = oracleConn.executeCustomQuery(dataQuery, params=dataParams)

        # Group interval data by SDID and time_key (for merging)
        dataBySDIDTime = defaultdict(dict)

        for row in dataResults:
            SDID = str(row['SDID'])
            timeKey = row[timeAlias]
            dataBySDIDTime[SDID][timeKey] = row

        # Fetch base metadata if applicable
        metaBySDIDTime = defaultdict(dict)
        if table == 'R':
            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Executing base query: {metaQuery} with params {metaParams}")
            metaResults = oracleConn.executeCustomQuery(metaQuery, params=metaParams)

            # Group base by SDID and time_key
            for row in metaResults:
                SDID = str(row['SDID'])
                timeKey = row[timeAlias]
                metaBySDIDTime[SDID][timeKey] = row

        # Process for each SDID
        for SDID in SDIDs:
            SDIDStr = str(SDID)
            intervalData = dataBySDIDTime.get(SDIDStr, {})
            baseData = metaBySDIDTime.get(SDIDStr, {}) if table == 'R' else {}
            outputData = []
            mergedMeta = []

            # Use interval times as primary; fall back to base if no interval
            allTimes = sorted(set(list(intervalData.keys()) + list(baseData.keys())))

            for timeKey in allTimes:
                intRow = intervalData.get(timeKey, {})
                baseRow = baseData.get(timeKey, {})

                # Value for table: interval if present, else base (but prefer interval per request)
                value = intRow.get('VALUE') if intRow else baseRow.get('RBASE_VALUE') if baseRow else None

                if value is None:
                    continue # Skip if no value

                # Format timestamp from timeKey
                try:
                    dateTime = datetime.strptime(timeKey, '%Y-%m-%d %H:%M:%S')
                    formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
                    valStr = str(value) if value is not None else ''
                    outputData.append(f'{formattedTs},{valStr}')
                except ValueError as e:
                    Logic.logMessage("WARN", f"sqlRead: Invalid timeKey skipped for SDID {SDID}: {timeKey} ({e})")
                    continue

                # Merge metadata: base as base, override common tags with interval if present/not None
                mergedRow = baseRow.copy() if baseRow else {}
                mergedRow.update({k: v for k, v in intRow.items() if v is not None}) # Override with interval non-None
                mergedRow['SDID'] = SDIDStr
                mergedRow['INTERVAL'] = tableSuffix.lower()

                if intRow:
                    mergedRow['INTERVAL_VALUE'] = intRow.get('VALUE') # Add interval value explicitly
                if baseRow:
                    mergedRow['RBASE_VALUE'] = baseRow.get('RBASE_VALUE') # Preserve base value

                # Replace IDs with names (delete old ID except for computation)
                if 'AGEN_ID' in mergedRow:
                    mergedRow['AGEN_NAME'] = lookups['agenMap'].get(mergedRow['AGEN_ID'], '')
                    del mergedRow['AGEN_ID']
                if 'COLLECTION_SYSTEM_ID' in mergedRow:
                    mergedRow['COLLECTION_SYSTEM'] = lookups['collectionMap'].get(mergedRow['COLLECTION_SYSTEM_ID'], '')
                    del mergedRow['COLLECTION_SYSTEM_ID']
                if 'LOADING_APPLICATION_ID' in mergedRow:
                    mergedRow['LOADING_APPLICATION'] = lookups['loadingMap'].get(mergedRow['LOADING_APPLICATION_ID'], '')
                    del mergedRow['LOADING_APPLICATION_ID']
                if 'METHOD_ID' in mergedRow:
                    mergedRow['METHOD'] = lookups['methodMap'].get(mergedRow['METHOD_ID'], '')
                    del mergedRow['METHOD_ID']
                if 'COMPUTATION_ID' in mergedRow:
                    compName = lookups['computationMap'].get(mergedRow['COMPUTATION_ID'], '')
                    mergedRow['COMPUTATION'] = f"{compName}\nID: {mergedRow['COMPUTATION_ID']}" if compName else str(mergedRow['COMPUTATION_ID'])
                mergedMeta.append(mergedRow)
            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Processed {len(outputData)} data points and {len(mergedMeta)} merged meta rows for SDID {SDID}")

            # Structure output with merged metadata
            resultDict[SDIDStr] = {
                'data': outputData,
                'rawResponse': mergedMeta # List of merged dicts, sorted by time
            }

    except Exception as e:
        Logic.logMessage("ERROR", f"sqlRead: Query failed: {e}")
        resultDict = {} # Reset resultDict on failure

        for SDID in SDIDs:
            resultDict[str(SDID)] = {'data': [], 'rawResponse': []}
    finally:
        if oracleConn: oracleConn.close()

    # Apply gapCheck on data (metadata not gapped, as it's per available time)
    timestamps = Query.buildTimestamps(startDate, endDate, interval)

    for SDID in SDIDs:
        SDIDStr = str(SDID)

        if SDIDStr in resultDict:
            resultDict[SDIDStr]['data'] = Query.gapCheck(timestamps, resultDict[SDIDStr]['data'], SDIDStr)

            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Post-gapCheck {len(resultDict[SDIDStr]['data'])} rows for SDID {SDID}")

    if not resultDict:
        Logic.logMessage("WARN", "sqlRead: No data after processing")
    return resultDict

@lru_cache(maxsize=None)
def fetchLookups(conn, svr):
    """Fetch all lookup maps for a svr (agen, collection, loading, method, computation)."""
    lookups = {
        'agenMap': {},
        'collectionMap': {},
        'loadingMap': {},
        'methodMap': {},
        'computationMap': {}
    }

    # Schema adjustment for special cases like uchdb2
    schema = svr.upper().rstrip('2') + 'A' if svr.endswith('2') else svr.upper() + 'A'
    link = f'@{svr}'

    # Common lookups (hdb_* tables)
    agenQuery = f"""
        SELECT agen_id, agen_name
        FROM {schema}.hdb_agen{link}
        ORDER BY agen_id
    """
    collectionQuery = f"""
        SELECT collection_system_id, collection_system_name
        FROM {schema}.hdb_collection_system{link}
        ORDER BY collection_system_id
    """
    loadingQuery = f"""
        SELECT loading_application_id, loading_application_name
        FROM {schema}.hdb_loading_application{link}
        ORDER BY loading_application_id
    """
    methodQuery = f"""
        SELECT method_id, method_name
        FROM {schema}.hdb_method{link}
        ORDER BY method_id
    """

    # Computation-specific
    computationQuery = f"""
        SELECT computation_id, computation_name
        FROM {schema}.cp_computation{link}
        ORDER BY computation_id
    """

    try:
        lookups['agenMap'] = {row['AGEN_ID']: row['AGEN_NAME'] for row in conn.executeCustomQuery(agenQuery)}
        lookups['collectionMap'] = {row['COLLECTION_SYSTEM_ID']: row['COLLECTION_SYSTEM_NAME'] for row in conn.executeCustomQuery(collectionQuery)}
        lookups['loadingMap'] = {row['LOADING_APPLICATION_ID']: row['LOADING_APPLICATION_NAME'] for row in conn.executeCustomQuery(loadingQuery)}
        lookups['methodMap'] = {row['METHOD_ID']: row['METHOD_NAME'] for row in conn.executeCustomQuery(methodQuery)}
        lookups['computationMap'] = {row['COMPUTATION_ID']: row['COMPUTATION_NAME'] for row in conn.executeCustomQuery(computationQuery)}

        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched lookups for svr {svr}: agen {len(lookups['agenMap'])}, collection {len(lookups['collectionMap'])}, loading {len(lookups['loadingMap'])}, method {len(lookups['methodMap'])}, computation {len(lookups['computationMap'])}")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch lookups for svr {svr}: {e}")
    
    return lookups