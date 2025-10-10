import requests
import json
from datetime import datetime, timedelta
import Logic  # For buildTimestamps, gapCheck, combineParameters

def api(dataID, intervalStr, startDateStr, endDateStr):
    print("[DEBUG] QueryUSGS.api called with dataID: {}, interval: {}, start: {}, end: {}".format(dataID, intervalStr, startDateStr, endDateStr))
    
    # Standardize timestamps
    timestamps = Logic.buildTimestamps(startDateStr, endDateStr, intervalStr)

    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return []
    
    # Set interval for USGS ('iv' for HOUR/INSTANT, 'dv' for DAY)
    if intervalStr in ['HOUR', 'INSTANT']:
        usgsInterval = 'iv'
    elif intervalStr == 'DAY':
        usgsInterval = 'dv'
    else:
        print("[ERROR] Unsupported intervalStr: {}".format(intervalStr))
        return []
    
    # Compute period in hours (keep current method)
    try:
        startDateTime = datetime.strptime(startDateStr, '%Y-%m-%d %H:%M')
        endDateTime = datetime.strptime(endDateStr, '%Y-%m-%d %H:%M')
        periodDelta = endDateTime - startDateTime
        periodHours = int(periodDelta.total_seconds() / 3600)
    except ValueError as e:
        print("[ERROR] Date parse failed: {}".format(e))
        return []
    
    uids = dataID.split(',')
    queryLimit = 50
    output = []
    buildHeader = []
    
    # Batch uids into groups of queryLimit
    for groupStart in range(0, len(uids), queryLimit):
        groupUids = uids[groupStart:groupStart + queryLimit]
        print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))
        
        # Parse group: collect unique sites, params (methods filter post-fetch)
        sites = []
        params = []
        methods = []  # For post-filter
        uidMap = {}  # uid -> (site, method, param)

        for uid in groupUids:
            parts = uid.split('-')

            if len(parts) != 3:
                print("[WARN] Invalid uid format skipped: {}".format(uid))
                continue

            site, method, param = parts
            sites.append(site)
            params.append('000' + param)  # Pad
            methods.append(method)
            uidMap[uid] = (site, method, param)
        
        if not sites:
            continue
        
        # Unique for efficiency, but API handles dups
        sitesStr = ','.join(set(sites))
        paramsStr = ','.join(set(params))
        
        # Fetch batched
        url = "https://waterservices.usgs.gov/nwis/{}/?format=json&sites={}&period=PT{}H&parameterCd={}&siteStatus=all".format(
            usgsInterval, sitesStr, periodHours, paramsStr
        )
        print("[DEBUG] Fetching USGS URL: {}".format(url))

        try:
            response = requests.get(url)
            response.raise_for_status()
            readFile = json.loads(response.content)
            timeSeriesList = readFile['value']['timeSeries']
            print("[DEBUG] Fetched {} timeSeries entries.".format(len(timeSeriesList)))
        except Exception as e:
            print("[ERROR] USGS fetch failed: {}".format(e))
            continue
        
        # Process per input uid in order (reorder/validate)
        groupOutputData = []  # List of outputData lists, one per uid

        for idx, uid in enumerate(groupUids):
            site, method, param = uidMap.get(uid, (None, None, None))

            if not site:
                groupOutputData.append([])  # Empty for invalid
                continue
            
            # Find matching timeSeries
            matchingSeries = None

            for series in timeSeriesList:
                seriesSite = series['sourceInfo']['siteCode'][0]['value'] if 'sourceInfo' in series and 'siteCode' in series['sourceInfo'] else None
                seriesParam = series['variable']['variableCode'][0]['value'] if 'variable' in series and 'variableCode' in series['variable'] else None

                if seriesSite == site and seriesParam == '000' + param:
                    # Check method
                    seriesValues = series['values']

                    if seriesValues and 'method' in seriesValues[0] and seriesValues[0]['method']:
                        seriesMethodId = seriesValues[0]['method'][0]['methodID']

                        if str(seriesMethodId) == method:
                            matchingSeries = series
                            break
            
            if not matchingSeries:
                print("[WARN] No matching series for uid '{}': site={}, param={}, method={}. Skipping.".format(uid, site, param, method))
                groupOutputData.append([])  # Will pad to blanks in gapCheck
                continue
            
            # Extract points
            dataPoints = matchingSeries['values'][0]['value']
            siteName = matchingSeries['sourceInfo']['siteName']  # Unused, but log
            print("[DEBUG] Found series for '{}': {} points, siteName={}".format(uid, len(dataPoints), siteName))
            
            outputData = []

            for point in dataPoints:
                value = point['value']
                dateTimeStr = point['dateTime'].replace('T', ' ').split('.')[0]  # YYYY-MM-DD HH:MM:SS

                try:
                    dateTime = datetime.strptime(dateTimeStr, '%Y-%m-%d %H:%M:%S')
                    formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')  # Standard, zero sec
                    outputData.append(f"{formattedTs},{value}")
                except ValueError as e:
                    print("[WARN] Invalid point ts skipped for '{}': {} - {}".format(uid, dateTimeStr, e))
            
            # Gap check
            outputData = Logic.gapCheck(timestamps, outputData, uid)
            groupOutputData.append(outputData)
            
            # Header: raw uid
            buildHeader.append(uid)
        
        # Combine group outputs
        if groupOutputData:
            combined = groupOutputData[0]
            
            for nextData in groupOutputData[1:]:
                combined = Logic.combineParameters(combined, nextData)
            if output:
                output = Logic.combineParameters(output, combined)
            else:
                output = combined
    
    if not output:
        print("[WARN] No data after processing all batches.")
        return []
    
    # Prepend header
    output.insert(0, buildHeader)
    print("[DEBUG] Final output len={} (incl header), sample row: {}".format(len(output), output[1] if len(output) > 1 else 'empty'))

    return output