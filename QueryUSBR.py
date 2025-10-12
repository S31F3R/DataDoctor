import requests
import QueryAquarius
import json
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QMessageBox # For error popup
import Logic # For buildTimestamps, gapCheck, combineParameters

periodOffset = True # Global for end of period shift/pad (USBR HOUR only; toggle via config later)

def api(svr, SDIDs, startDate, endDate, interval, mrid='0'):
    if Logic.debug == True: print(f"[DEBUG] QueryUSBR.api called with svr: {svr}, SDIDs: {SDIDs}, interval: {interval}, start: {startDate}, end: {endDate}, mrid: {mrid}")
    
    # Map for URL only
    if interval == 'HOUR':
        tstp = 'HR'
    elif interval == 'INSTANT':
        tstp = 'IN'
    elif interval == 'DAY':
        tstp = 'DY'
    else:
        print("[ERROR] Unsupported interval: {}".format(interval))
        return {}
    
    # Use original interval for timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, interval)
    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return {}
    
    # Parse start (with pad if periodOffset and HOUR)
    startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')

    if periodOffset and interval == 'HOUR':
        startDateTime = startDateTime - timedelta(hours=1) # Pad fetch start by -1h

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
        url = f'https://www.usbr.gov/pn-bin/hdb/hdb.pl?svr={svr}&SDI={groupSDIDStr}&tstp={tstp}&t1={startYear}-{startMonth}-{startDay}T{startHour}:{startMinute}&t2={endYear}-{endMonth}-{endDay}T{endHour}:{endMinute}&table=R&mrid={mrid}&format=json'
        if Logic.debug == True: print("[DEBUG] Fetching USBR URL: {}".format(url))
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            readFile = json.loads(response.content)
            seriesList = readFile['Series']
            if Logic.debug == True: print("[DEBUG] Fetched {} series entries.".format(len(seriesList)))
        except Exception as e:
            print("[ERROR] USBR fetch failed: {}".format(e))
            continue
        
        for SDID in groupSDIDs:
            matchingSeries = None
            
            for series in seriesList:
                jsonSDID = series['SDI']

                if isinstance(jsonSDID, list):
                    jsonSDID = jsonSDID[0] if jsonSDID else '' # Handle list
                if str(jsonSDID) == SDID: # Str comparison
                    matchingSeries = series
                    break
            
            if not matchingSeries:
                print(f"[WARN] No matching series for SDID '{SDID}'.")
                resultDict[SDID] = [] # Blanks
                continue
            
            dataPoints = matchingSeries['Data']
            if Logic.debug == True: print(f"[DEBUG] Found series for '{SDID}': {len(dataPoints)} points.")
            
            outputData = []

            for point in dataPoints:  
                value = point['v']
                dateTime = point['t'] # MM/DD/YY HH:MM:SS AM/PM
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
                
                if periodOffset and interval == 'HOUR':
                    dateTime = dateTime + timedelta(hours=1)
                
                # Change time from 12 hour clock to 24
                if amPm == 'AM' and hour == 12:
                    dateTime = dateTime - timedelta(hours=12)
                elif amPm == 'PM' and hour < 12:
                    dateTime = dateTime + timedelta(hours=12)
                
                formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00') # Standard, zero sec  
                outputData.append(f'{formattedTs},{value}')
                
            resultDict[SDID] = outputData
    
    if not resultDict:
        print("[WARN] No data after processing all batches.")
    
    return resultDict