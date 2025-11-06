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
    if Config.debug:
        Logic.logMessage("DEBUG", f"USBR.sqlRead called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, start: {startDate}, end: {endDate}, mrid: {mrid}, table: {table}")

    if '-' in svr:
        svr = svr.split('-')[1].lower()

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

    tableSuffix = intervalMap.get(interval, 'HOUR')

    schema = svr.upper().rstrip('2') + 'A' if svr.endswith('2') else svr.upper() + 'A'

    baseTable = f'{schema}.r_base'
    dataTable = f'{schema}.{table.lower()}_{tableSuffix.lower()}'

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

    if not SDIDs:
        Logic.logMessage("WARN", "sqlRead: No SDIDs provided")
        return {}
    sdidPlaceholders = ','.join([f':{i+1}' for i in range(len(SDIDs))])

    if interval == 'HOUR' and Config.periodOffset:
        timeCol = 'end_date_time'
        timeAlias = 'END_DATE_TIME'
    else:
        timeCol = 'start_date_time'
        timeAlias = 'START_DATE_TIME'

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

    metaResults = []

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

    resultDict = {}
    oracleConn = None
    try:
        dsn = svr

        oracleConn = Oracle.oracleConnection(dsn)
        conn = oracleConn.connect()

        agenMap = fetchAgenMap(conn)
        collectionMap = fetchCollectionMap(conn)
        loadingMap = fetchLoadingMap(conn)
        methodMap = fetchMethodMap(conn)
        computationMap = fetchComputationMap(conn, schema)

        if Config.debug: 
            Logic.logMessage("DEBUG", f"sqlRead: Executing interval query: {dataQuery} with params {dataParams}")
        dataResults = oracleConn.executeCustomQuery(dataQuery, params=dataParams)

        dataBySDIDTime = defaultdict(dict)

        for row in dataResults:
            SDID = str(row['SDID'])
            timeKey = row[timeAlias]
            dataBySDIDTime[SDID][timeKey] = row

        metaBySDIDTime = defaultdict(dict)

        if table == 'R':
            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Executing base query: {metaQuery} with params {metaParams}")
            metaResults = oracleConn.executeCustomQuery(metaQuery, params=metaParams)

            for row in metaResults:
                SDID = str(row['SDID'])
                timeKey = row[timeAlias]
                metaBySDIDTime[SDID][timeKey] = row

        for SDID in SDIDs:
            SDIDStr = str(SDID)
            intervalData = dataBySDIDTime.get(SDIDStr, {})
            baseData = metaBySDIDTime.get(SDIDStr, {}) if table == 'R' else {}
            outputData = []
            mergedMeta = []

            allTimes = sorted(set(list(intervalData.keys()) + list(baseData.keys())))

            for timeKey in allTimes:
                intRow = intervalData.get(timeKey, {})
                baseRow = baseData.get(timeKey, {})

                value = intRow.get('VALUE') if intRow else baseRow.get('RBASE_VALUE') if baseRow else None

                if value is None:
                    continue

                try:
                    dateTime = datetime.strptime(timeKey, '%Y-%m-%d %H:%M:%S')
                    formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
                    valStr = str(value) if value is not None else ''
                    outputData.append(f'{formattedTs},{valStr}')
                except ValueError as e:
                    Logic.logMessage("WARN", f"sqlRead: Invalid timeKey skipped for SDID {SDID}: {timeKey} ({e})")
                    continue

                mergedRow = baseRow.copy() if baseRow else {}
                mergedRow.update({k: v for k, v in intRow.items() if v is not None})
                mergedRow['SDID'] = SDIDStr
                mergedRow['INTERVAL'] = tableSuffix.lower()

                if intRow:
                    mergedRow['INTERVAL_VALUE'] = intRow.get('VALUE')
                if baseRow:
                    mergedRow['RBASE_VALUE'] = baseRow.get('RBASE_VALUE')

                displayMeta = {}
                displayMeta['SDID'] = mergedRow.get('SDID', '')
                displayMeta['Interval'] = mergedRow.get('INTERVAL', '')
                displayMeta['Start Date/Time'] = mergedRow.get('START_DATE_TIME', '')
                displayMeta['End Date/Time'] = mergedRow.get('END_DATE_TIME', '')
                displayMeta['Date/Time Loaded'] = mergedRow.get('DATE_TIME_LOADED', '')
                displayMeta['Interval Value'] = str(mergedRow.get('INTERVAL_VALUE', '')) if mergedRow.get('INTERVAL_VALUE') is not None else ''
                displayMeta['r_base Value'] = str(mergedRow.get('RBASE_VALUE', '')) if mergedRow.get('RBASE_VALUE') is not None else ''
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
                displayMeta['Data Flags'] = mergedRow.get('DATA_FLAGS', '') or mergedRow.get('DERIVATION_FLAGS', '') or ''

                mergedMeta.append(displayMeta)

            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Processed {len(outputData)} data points and {len(mergedMeta)} merged meta rows for SDID {SDID}")

            resultDict[SDIDStr] = {
                'data': outputData,
                'rawResponse': mergedMeta
            }

    except Exception as e:
        Logic.logMessage("ERROR", f"sqlRead: Query failed: {e}")
        resultDict = {}

        for SDID in SDIDs:
            resultDict[str(SDID)] = {'data': [], 'rawResponse': []}
    finally:
        if oracleConn: oracleConn.close()

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

def fetchAgenMap(conn):
    agenMap = {}
    agenQuery = """
        SELECT agen_id, agen_name
        FROM LCHDBA.hdb_agen@lchdb
        ORDER BY agen_id
    """
    try:
        results = conn.executeCustomQuery(agenQuery)
        agenMap = {row['AGEN_ID']: row['AGEN_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(agenMap)} agen mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch agenMap: {e}")
    return agenMap

def fetchCollectionMap(conn):
    collectionMap = {}
    collectionQuery = """
        SELECT collection_system_id, collection_system_name
        FROM LCHDBA.hdb_collection_system@lchdb
        ORDER BY collection_system_id
    """
    try:
        results = conn.executeCustomQuery(collectionQuery)
        collectionMap = {row['COLLECTION_SYSTEM_ID']: row['COLLECTION_SYSTEM_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(collectionMap)} collection mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch collectionMap: {e}")
    return collectionMap

def fetchLoadingMap(conn):
    loadingMap = {}
    loadingQuery = """
        SELECT loading_application_id, loading_application_name
        FROM LCHDBA.hdb_loading_application@lchdb
        ORDER BY loading_application_id
    """
    try:
        results = conn.executeCustomQuery(loadingQuery)
        loadingMap = {row['LOADING_APPLICATION_ID']: row['LOADING_APPLICATION_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(loadingMap)} loading mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch loadingMap: {e}")
    return loadingMap

def fetchMethodMap(conn):
    methodMap = {}
    methodQuery = """
        SELECT method_id, method_name
        FROM LCHDBA.hdb_method@lchdb
        ORDER BY method_id
    """
    try:
        results = conn.executeCustomQuery(methodQuery)
        methodMap = {row['METHOD_ID']: row['METHOD_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(methodMap)} method mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch methodMap: {e}")
    return methodMap

def fetchComputationMap(conn, schema):
    computationMap = {}
    computationQuery = f"""
        SELECT computation_id, computation_name
        FROM {schema}.cp_computation
        ORDER BY computation_id
    """
    try:
        results = conn.executeCustomQuery(computationQuery)
        computationMap = {row['COMPUTATION_ID']: row['COMPUTATION_NAME'] for row in results}
        if Config.debug:
            Logic.logMessage("DEBUG", f"Fetched {len(computationMap)} computation mappings")
    except Exception as e:
        Logic.logMessage("ERROR", f"Failed to fetch computationMap: {e}")
    return computationMap