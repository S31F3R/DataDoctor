import requests
import QueryAquarius
import json
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QMessageBox  # For error popup
import Logic  # For buildTimestamps, gapCheck, combineParameters

def api(database, dataID, startDate, endDate, interval):
    print("[DEBUG] QueryUSBR.api called with database: {}, dataID: {}, interval: {}, start: {}, end: {}".format(database, dataID, interval, startDate, endDate))
    
    # Standardize timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, interval)
    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return []
    
    # Remove agency from database string
    database = database.lower().split('-')[1]
    
    # Fallback to Aquarius if 'aquarius'
    if database == 'aquarius':
        return QueryAquarius.api(dataID, startDate, endDate, interval)    
    try:
        # Parse start time
        startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
        startYear = startDateTime.year
        startMonth = f'{startDateTime.month:02d}'
        startDay = f'{startDateTime.day:02d}'
        startHour = f'{startDateTime.hour:02d}'
        startMinute = f'{startDateTime.minute:02d}'
        
        # Parse end time
        endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
        endYear = endDateTime.year
        endMonth = f'{endDateTime.month:02d}'
        endDay = f'{endDateTime.day:02d}'
        endHour = f'{endDateTime.hour:02d}'
        endMinute = f'{endDateTime.minute:02d}'
        
        # Set the interval
        if interval == 'HOUR': interval = 'HR'
        elif interval == 'INSTANT': interval = 'IN'
        elif interval == 'DAY': interval = 'DY'
        else:
            print("[ERROR] Unsupported interval: {}".format(interval))
            return []
        
        sdis = dataID.split(',')
        queryLimit = 50
        output = []
        buildHeader = []
        
        # Batch sdis into groups of queryLimit
        for groupStart in range(0, len(sdis), queryLimit):
            groupSdis = sdis[groupStart:groupStart + queryLimit]
            print("[DEBUG] Processing batch of {} sdis: {}".format(len(groupSdis), groupSdis[:3] if groupSdis else []))
            
            groupSdiStr = ','.join(groupSdis)
            
            # Fetch batched
            urlStr = f'https://www.usbr.gov/pn-bin/hdb/hdb.pl?svr={database}&sdi={groupSdiStr}&tstp={interval}&t1={startYear}-{startMonth}-{startDay}T{startHour}:{startMinute}&t2={endYear}-{endMonth}-{endDay}T{endHour}:{endMinute}&table=R&mrid=0&format=json'
            print("[DEBUG] Fetching USBR URL: {}".format(urlStr))
            try:
                response = requests.get(urlStr)
                response.raise_for_status()
                readFile = json.loads(response.content)
                seriesList = readFile['Series']
                print("[DEBUG] Fetched {} series entries.".format(len(seriesList)))
            except Exception as e:
                print("[ERROR] USBR fetch failed: {}".format(e))
                continue
            
            # Process per input sdi in order (reorder)
            groupOutputData = []  # List of outputData lists, one per sdi
            groupHeader = []  # Temp for group

            for sdi in groupSdis:
                # Find matching series (API may shuffle)
                matchingSeries = None

                for series in seriesList:
                    if float(series['SDI']) == float(sdi):
                        matchingSeries = series
                        break
                
                if not matchingSeries:
                    print("[WARN] No matching series for sdi '{}'. Skipping.".format(sdi))
                    groupOutputData.append([])  # Pad blanks in gapCheck
                    continue
                
                groupHeader.append(sdi)  # Raw SDI for header
                
                dataPoints = matchingSeries['Data']
                print("[DEBUG] Found series for '{}': {} points.".format(sdi, len(dataPoints)))
                
                outputData = []
                for point in dataPoints:
                    value = point['v']
                    dateTime = point['t']  # MM/DD/YY HH:MM:SS AM/PM
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

                    if interval == 'HOUR':
                        dateTime = dateTime + timedelta(hours=1)
                    
                    # Change time from 12 hour clock to 24
                    if amPm == 'AM' and hour == 12:
                        dateTime = dateTime - timedelta(hours=12)
                    elif amPm == 'PM' and hour < 12:
                        dateTime = dateTime + timedelta(hours=12)
                    
                    formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')  # Standard, zero sec
                    outputData.append(f'{formattedTs},{value}')
                
                # Gap check
                outputData = Logic.gapCheck(timestamps, outputData, sdi)
                groupOutputData.append(outputData)
            
            # Combine group outputs
            if groupOutputData:
                combined = groupOutputData[0]
                for nextData in groupOutputData[1:]:
                    combined = Logic.combineParameters(combined, nextData)
                if output:
                    output = Logic.combineParameters(output, combined)
                else:
                    output = combined
            buildHeader.extend(groupHeader)
        
        if not output:
            print("[WARN] No data after processing all batches.")
            return []
        
        # Prepend header
        output.insert(0, buildHeader)
        output.pop(len(output) - 1)  # USBR fix: Pop extra item
        print("[DEBUG] Final output len={} (incl header), sample row: {}".format(len(output), output[1] if len(output) > 1 else 'empty'))
        return output
    except requests.exceptions.RequestException as e:
        QMessageBox.warning(None, "API Error", f"USBR query failed:\n{e}\nCheck connection or SDID.")
        return []
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        QMessageBox.warning(None, "Parse Error", f"USBR response invalid:\n{e}")
        return []