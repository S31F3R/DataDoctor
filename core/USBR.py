# USBR.py

import requests
import json
from core import Oracle, Query, Config
from datetime import datetime, timedelta

def apiRead(svr, SDIDs, startDate, endDate, interval, mrid='0', table='R'):
    if Config.debug:
        print(f"[DEBUG] USBR.apiRead called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, start: {startDate}, end: {endDate}, mrid: {mrid}, table='R'")

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
        print("[ERROR] Unsupported interval: {}".format(interval))
        return {}

    # Use original interval for timestamps
    timestamps = Query.buildTimestamps(startDate, endDate, interval)

    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
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
            print("[DEBUG] Fetching USBR URL: {}".format(url))
        try:
            response = requests.get(url)
            response.raise_for_status()
            readFile = json.loads(response.content)
            seriesList = readFile['Series']

            if Config.debug:
                print("[DEBUG] Fetched {} series entries.".format(len(seriesList)))
        except Exception as e:
            print("[ERROR] USBR fetch failed: {}".format(e))
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
                print(f"[WARN] No matching series for SDID '{SDID}'.")
                resultDict[SDID] = []
                continue
            dataPoints = matchingSeries['Data']

            if Config.debug:
                print(f"[DEBUG] Found series for '{SDID}': {len(dataPoints)} points.")
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
        print("[WARN] No data after processing all batches.")
    return resultDict

def sqlRead(svr, SDIDs, startDate, endDate, interval, mrid='0', table='R'):
    if Config.debug: print(f"[DEBUG] USBR.sqlRead called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, start: {startDate}, end: {endDate}, mrid: {mrid}, table: {table}")

    # Map interval to Oracle table suffix
    intervalMap = {
        'HOUR': 'H',
        'INSTANT:1': 'M',
        'INSTANT:15': 'M',
        'INSTANT:60': 'M',
        'DAY': 'D',
        'MONTH': 'M',
        'YEAR': 'Y',
        'WATER YEAR': 'WY'
    }

    tableSuffix = intervalMap.get(interval, 'H')

    # Adjust table name for MRID
    tableName = f"HDB_{table}_{tableSuffix}" if table == 'R' else f"HDB_M_{tableSuffix}"

    # Parse dates
    try:
        startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
        endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
        if Config.periodOffset and interval == 'HOUR': startDateTime = startDateTime - timedelta(hours=1)
    except ValueError as e:
        print(f"[ERROR] sqlRead: Date parse failed: {e}")
        return {}

    # Build query
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

        for sdi in SDIDs:
            query = f"""
                SELECT TO_CHAR(hdb_date, 'MM/DD/YY HH24:MI:00') AS timestamp, value
                FROM {tableName}
                WHERE sdi = :1
                AND hdb_date BETWEEN TO_DATE(:2, 'YYYY-MM-DD HH24:MI')
                AND TO_DATE(:3, 'YYYY-MM-DD HH24:MI')
                {'AND mrid = :4' if mrid != '0' else ''}
                ORDER BY hdb_date
            """

            params = [sdi, startDate, endDate]
            if mrid != '0': params.append(mrid)
            if Config.debug: print(f"[DEBUG] sqlRead: Executing query for SDI {sdi}: {query}")

            try:
                data = oracleConn.executeQuery(query, params=params)
                resultDict[sdi] = Query.gapCheck(
                    Query.buildTimestamps(startDate, endDate, interval),
                    data,
                    sdi
                )

                if Config.debug: print(f"[DEBUG] sqlRead: Fetched {len(resultDict[sdi])} rows for SDI {sdi}")
            except Exception as e:
                print(f"[ERROR] sqlRead: Query failed for SDI {sdi}: {e}")
                resultDict[sdi] = []
    except Exception as e:
        print(f"[ERROR] sqlRead: Connection failed: {e}")
        return {}
    finally:
        if oracleConn: oracleConn.close()
            
    return resultDict