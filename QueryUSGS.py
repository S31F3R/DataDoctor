import requests
import json
from datetime import datetime, timedelta
import Logic # For buildTimestamps, gapCheck, combineParameters

def apiRead(dataID, interval, startDate, endDate):
    if Logic.debug == True: print("[DEBUG] QueryUSGS.api called with dataID: {}, interval: {}, start: {}, end: {}".format(dataID, interval, startDate, endDate))
    
    # Standardize timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, interval)

    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return []
    
    # Set interval for USGS ('iv' for HOUR/INSTANT, 'dv' for DAY)
    if interval in ['HOUR', 'INSTANT']:
        usgsInterval = 'iv'
    elif interval == 'DAY':
        usgsInterval = 'dv'
    else:
        print("[ERROR] Unsupported interval: {}".format(interval))
        return []
    
    # Format start/end for API (YYYY-MM-DDTHH:MM, no TZ; assumes local)
    try:
        startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
        endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
        startFormatted = startDateTime.strftime('%Y-%m-%dT%H:%M')
        endFormatted = endDateTime.strftime('%Y-%m-%dT%H:%M')
    except ValueError as e:
        print("[ERROR] Date parse failed: {}".format(e))
        return []
    
    queryLimit = 50
    resultDict = {}
    
    # Batch uids into groups of queryLimit
    for groupStart in range(0, len(dataID), queryLimit):
        groupUids = dataID[groupStart:groupStart + queryLimit]
        if Logic.debug == True: print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))
        
        # Parse group: collect unique sites, params (methods filter post-fetch)
        sites = []
        params = []
        methods = [] # For post-filter
        uidMap = {} # uid -> (site, method, param)

        for uid in groupUids:
            parts = uid.split('-')

            if len(parts) != 3:
                print("[WARN] Invalid uid format skipped: {}".format(uid))
                continue

            site, method, param = parts
            sites.append(site)
            params.append('000' + param) # Pad
            methods.append(method)
            uidMap[uid] = (site, method, param)
        
        if not sites:
            continue
        
        # Unique for efficiency, but API handles dups
        sites = ','.join(set(sites))
        joinedParams = ','.join(set(params))
        
        # Fetch batched using startDT/endDT
        url = "https://waterservices.usgs.gov/nwis/{}/?format=json&sites={}&startDT={}&endDT={}&parameterCd={}&siteStatus=all".format(
            usgsInterval, sites, startFormatted, endFormatted, joinedParams
        )
        if Logic.debug == True: print("[DEBUG] Fetching USGS URL: {}".format(url))
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            readFile = json.loads(response.content)
            timeSeriesList = readFile['value']['timeSeries']
            if Logic.debug == True: print("[DEBUG] Fetched {} timeSeries entries.".format(len(timeSeriesList)))
        except Exception as e:
            print("[ERROR] USGS fetch failed: {}".format(e))
            continue
        
        # Process per input uid in order (reorder/validate)
        for uid in groupUids:
            site, method, param = uidMap.get(uid, (None, None, None))

            if not site:
                resultDict[uid] = [] # Blank
                continue
            
            # Find matching timeSeries
            matchingSeries = None

            for series in timeSeriesList:
                seriesSite = series['sourceInfo']['siteCode'][0]['value'] if 'sourceInfo' in series and 'siteCode' in series['sourceInfo'] else None
                seriesParam = series['variable']['variableCode'][0]['value'] if 'variable' in series and 'variableCode' in series['variable'] else None

                if seriesSite == site and seriesParam == '000' + param:
                    seriesValues = series['values']

                    if seriesValues and 'method' in seriesValues[0] and seriesValues[0]['method']:
                        seriesMethodId = seriesValues[0]['method'][0]['methodID']

                        if str(seriesMethodId) == method:
                            matchingSeries = series
                            break
            
            if not matchingSeries:
                print("[WARN] No matching series for uid '{}': site={}, param={}, method={}. Skipping.".format(uid, site, param, method))
                resultDict[uid] = [] # Blank
                continue
            
            # Extract points
            dataPoints = matchingSeries['values'][0]['value']
            if Logic.debug == True: print("[DEBUG] Found series for '{}': {} points, siteName={}".format(uid, len(dataPoints), matchingSeries['sourceInfo']['siteName']))
            
            outputData = []

            for point in dataPoints:               
                value = point['value']
                dateTimeStr = point['dateTime'].replace('T', ' ').split('.')[0] # YYYY-MM-DD HH:MM:SS    
                
                try:
                    dateTime = datetime.fromisoformat(f"{dateTimeStr.replace(' ', 'T')}") # Ensure ISO for parse
                    formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00') # Standard
                    outputData.append(f"{formattedTs},{value}")
                except ValueError as e:
                    print("[WARN] Invalid point ts skipped for '{}': {} - {}".format(uid, dateTimeStr, e))
            
            # Gap check
            outputData = Logic.gapCheck(timestamps, outputData, uid)
            resultDict[uid] = outputData
    
    return resultDict