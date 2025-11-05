# USBR.py

import requests
import json
from core import Oracle, Query, Config, Logic
from datetime import datetime, timedelta

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
    schema = (svr.upper() + 'A')
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

    # Data query (second SQL)
    dataQuery = f"""
        SELECT 
          site_datatype_id AS SDID, 
          TO_CHAR(end_date_time, 'YYYY-MM-DD HH24:MI:SS') AS DATE_TIME,
          TO_CHAR(date_time_loaded, 'YYYY-MM-DD HH24:MI:SS') AS DATE_TIME_LOADED,
          value,
          validation,
          overwrite_flag,
          method_id,
          derivation_flags
        FROM {dataTable}
        WHERE site_datatype_id in ({sdidPlaceholders})
          AND end_date_time BETWEEN TO_DATE(:{len(SDIDs)+1}, 'YYYY-MM-DD HH24:MI:SS') 
          AND TO_DATE(:{len(SDIDs)+2}, 'YYYY-MM-DD HH24:MI:SS')
        ORDER BY SDID ASC, end_date_time ASC
    """
    dataParams = SDIDs + [startStr, endStr]
    if table == 'M' and mrid != '0':
        dataQuery = dataQuery.replace('ORDER BY', f"AND model_run_id = :{len(SDIDs)+3}\nORDER BY")
        dataParams.append(mrid)

    # Metadata query (first SQL, optional for table=='R')
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
              AND end_date_time BETWEEN TO_DATE(:{len(SDIDs)+1}, 'YYYY-MM-DD HH24:MI:SS') 
              AND TO_DATE(:{len(SDIDs)+2}, 'YYYY-MM-DD HH24:MI:SS') 
              AND interval = '{tableSuffix.lower()}'
            ORDER BY SDID ASC, end_date_time ASC
        """
        metaParams = SDIDs + [startStr, endStr]

    # Execute queries
    resultDict = {}
    oracleConn = None

    try:
        # Map server to TNS alias
        tnsMap = {
            'lchdb': 'USBR-LCHDB',
            'yaohdb': 'USBR-YAOHDB',
            'uchdb2': 'USBR-UCHDB2',
            'ecohdb': 'USBR-ECOHDB',
            'lbohdb': 'USBR-LBOHDB',
            'kbohdb': 'USBR-KBOHDB',
            'pnhyd': 'USBR-PNHYD',
            'gphyd': 'USBR-GPHYD'
        }
        dsn = tnsMap.get(svr.lower(), svr)
        oracleConn = Oracle.oracleConnection(dsn)
        conn = oracleConn.connect()

        # Fetch data
        if Config.debug: 
            Logic.logMessage("DEBUG", f"sqlRead: Executing data query: {dataQuery} with params {dataParams}")
        dataResults = oracleConn.executeCustomQuery(dataQuery, params=dataParams)

        # Group data by SDID
        dataBySDID = defaultdict(list)

        for row in dataResults:
            sdid = str(row['SDID'])
            dataBySDID[sdid].append(row)

        # Fetch metadata if applicable
        if table == 'R':
            if Config.debug: 
                Logic.logMessage("DEBUG", f"sqlRead: Executing meta query: {metaQuery} with params {metaParams}")
            metaResults = oracleConn.executeCustomQuery(metaQuery, params=metaParams)

            # Group meta by SDID
            metaBySDID = defaultdict(list)

            for row in metaResults:
                sdid = str(row['SDID'])
                metaBySDID[sdid].append(row)

        # Process for each SDID
        for sdi in SDIDs:
            sdiStr = str(sdi)
            specific_rows = dataBySDID.get(sdiStr, [])
            outputData = []

            for row in specific_rows:
                value = row.get('VALUE')
                dateTimeStr = row['DATE_TIME']

                try:
                    dateTime = datetime.strptime(dateTimeStr, '%Y-%m-%d %H:%M:%S')

                    if Config.periodOffset and interval == 'HOUR':
                        dateTime = dateTime + timedelta(hours=1)
                    formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
                    valStr = str(value) if value is not None else ''
                    outputData.append(f'{formattedTs},{valStr}')
                except ValueError as e:
                    Logic.logMessage("WARN", f"sqlRead: Invalid date_time skipped for SDID {sdi}: {dateTimeStr} ({e})")
                    continue

            # Metadata for this SDID (base rows)
            metaRows = metaBySDID.get(sdiStr, []) if table == 'R' else []

            # Add INTERVAL and SDID to each meta dict (user request)
            for mrow in metaRows:
                mrow['SDID'] = sdiStr
                mrow['INTERVAL'] = tableSuffix.lower()

            if Config.debug: Logic.logMessage("DEBUG", f"sqlRead: Processed {len(outputData)} data points and {len(metaRows)} meta rows for SDID {sdi}")

            # Structure output with metadata
            resultDict[sdiStr] = {
                'data': outputData,
                'rawResponse': metaRows # List of dicts from base; can merge specific later
            }

    except Exception as e:
        Logic.logMessage("ERROR", f"sqlRead: Query failed: {e}")
        for sdi in SDIDs:
            resultDict[str(sdi)] = {'data': [], 'rawResponse': []}
    finally:
        if oracleConn: oracleConn.close()

    # Apply gapCheck on data
    timestamps = Query.buildTimestamps(startDate, endDate, interval)

    for sdi in SDIDs:
        sdiStr = str(sdi)

        if sdiStr in resultDict:
            resultDict[sdiStr]['data'] = Query.gapCheck(timestamps, resultDict[sdiStr]['data'], sdiStr)
            if Config.debug: Logic.logMessage("DEBUG", f"sqlRead: Post-gapCheck {len(resultDict[sdiStr]['data'])} rows for SDID {sdi}")

    if not resultDict:
        Logic.logMessage("WARN", "sqlRead: No data after processing")
    return resultDict