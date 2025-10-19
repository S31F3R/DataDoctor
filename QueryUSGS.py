import requests
import json
from datetime import datetime, timedelta
import Logic  # For buildTimestamps, gapCheck, combineParameters, getUtcOffsetInt, debug
import keyring
import re
import time
import ssl

def apiReadOldMethod(dataID, interval, startDate, endDate):
    if Logic.debug: print("[DEBUG] QueryUSGS.apiReadOldMethod called with dataID: {}, interval: {}, start: {}, end: {}".format(dataID, interval, startDate, endDate))

    # Standardize timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, interval)

    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return []

    # Set interval for USGS ('iv' for HOUR/INSTANT, 'dv' for DAY)
    if interval in ['HOUR'] or interval.startswith('INSTANT:'):
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
        if Logic.debug: print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))

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

            # Check for UUID method, reject if present
            if re.match(r'^[0-9a-fA-F]{32}$', method):
                print("[ERROR] UUID method {} in uid {} not supported by old method. Use new API with DAY interval.".format(method, uid))
                return []

            # Pad param to 5 digits for old API
            params.append(param.zfill(5))
            sites.append(site)
            methods.append(method)
            uidMap[uid] = (site, method, param)

        if not sites:
            continue

        # Unique for efficiency, but API handles dups
        sites = ','.join(set(sites))
        joinedParams = ','.join(set(params))

        # Fetch batched using startDT/endDT with retry and SSL handling
        url = "https://waterservices.usgs.gov/nwis/{}/?format=json&sites={}&startDT={}&endDT={}&parameterCd={}&siteStatus=all".format(
            usgsInterval, sites, startFormatted, endFormatted, joinedParams
        )

        if Logic.debug: print("[DEBUG] Fetching USGS URL: {}".format(url))
        maxRetries = 3
        timeout = 10 # Increased timeout in seconds

        for attempt in range(maxRetries):
            try:
                response = requests.get(url, timeout=timeout, verify=True)
                response.raise_for_status()
                readFile = json.loads(response.content)
                timeSeriesList = readFile['value']['timeSeries']
                if Logic.debug: print("[DEBUG] Fetched timeSeries data: {}".format(timeSeriesList))
                if Logic.debug: print("[DEBUG] Fetched {} timeSeries entries.".format(len(timeSeriesList)))
                break
            except requests.exceptions.SSLError as e:
                if attempt < maxRetries - 1:
                    print("[WARN] Retry {} of {}: SSL error: {}. Retrying with increased timeout and disabled verification...".format(attempt + 1, maxRetries, e))
                    timeout *= 2 # Double timeout for next attempt
                    time.sleep(2 ** attempt) # Exponential backoff
                    response = requests.get(url, timeout=timeout, verify=False)
                    response.raise_for_status()
                    readFile = json.loads(response.content)
                    timeSeriesList = readFile['value']['timeSeries']
                    print("[WARN] SSL verification disabled for this request. Update OpenSSL (e.g., 'sudo pacman -Syu openssl' on Manjaro) or check network.")
                    if Logic.debug: print("[DEBUG] Fetched timeSeries data with disabled SSL: {}".format(timeSeriesList))
                    if Logic.debug: print("[DEBUG] Fetched {} timeSeries entries with disabled SSL.".format(len(timeSeriesList)))
                    break
                else:
                    print("[ERROR] Max retries exceeded: {} for URL: {}. Update OpenSSL or use a different network.".format(e, url))
                    return []
            except requests.exceptions.RequestException as e:
                if attempt < maxRetries - 1:
                    print("[WARN] Retry {} of {}: Request failed: {} for URL: {}. Retrying...".format(attempt + 1, maxRetries, e, url))
                    timeout *= 2 # Double timeout for next attempt
                    time.sleep(2 ** attempt) # Exponential backoff
                else:
                    print("[ERROR] Max retries exceeded: {} for URL: {}".format(e, url))
                    return []

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

                if seriesSite == site and seriesParam == param.zfill(5): # Match padded param
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
            if Logic.debug: print("[DEBUG] Found series for '{}': {} points, siteName={}".format(uid, len(dataPoints), matchingSeries['sourceInfo']['siteName']))
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

def apiRead(dataID, interval, startDate, endDate):
    if Logic.debug: print("[DEBUG] QueryUSGS.apiRead called with dataID: {}, interval: {}, start: {}, end: {}".format(dataID, interval, startDate, endDate))

    # Standardize timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, interval)

    if not timestamps:
        print("[ERROR] No timestamps generated - invalid dates or interval.")
        return []

    # Use new API only for DAY with UID methods
    if interval == 'DAY':

        # Check all UIDs for UID methods
        hasNonUid = False

        for uid in dataID:
            parts = uid.split('-')

            if len(parts) != 3 or not re.match(r'^[0-9a-fA-F]{32}$', parts[1]): # Match 32-char hex without hyphens
                hasNonUid = True
                if Logic.debug: print("[DEBUG] Non-UID method {} detected in uid {}".format(parts[1], uid))
                break

        if hasNonUid:
            print("[WARN] Non-UID method detected. Use numeric methodIDs with legacy method or UIDs with DAY interval.")
            return []

        # Format start/end for new API (UTC, midnight for DAY)
        try:
            startDateTime = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
            endDateTime = datetime.strptime(endDate, '%Y-%m-%d %H:%M')

            # Apply UTC offset for new API (negative to convert local to UTC)
            offsetHours = Logic.getUtcOffsetInt(Logic.utcOffset)
            startDateTime = startDateTime - timedelta(hours=offsetHours)
            endDateTime = endDateTime - timedelta(hours=offsetHours)

            # Set to midnight for daily
            startFormatted = startDateTime.replace(hour=0, minute=0, second=0).strftime('%Y-%m-%dT00:00:00Z')
            endFormatted = endDateTime.replace(hour=0, minute=0, second=0).strftime('%Y-%m-%dT00:00:00Z')
        except ValueError as e:
            print("[ERROR] Date parse failed: {}".format(e))
            return []

        queryLimit = 50
        resultDict = {}

        # Batch uids into groups of queryLimit
        for groupStart in range(0, len(dataID), queryLimit):
            groupUids = dataID[groupStart:groupStart + queryLimit]
            if Logic.debug: print("[DEBUG] Processing batch of {} uids: {}".format(len(groupUids), groupUids[:3] if groupUids else []))

            # Parse group: collect unique sites, params, and check method
            sites = []
            params = []
            uidMap = {} # uid -> (site, method, param)

            for uid in groupUids:
                parts = uid.split('-')

                if len(parts) != 3:
                    print("[WARN] Invalid uid format skipped: {}".format(uid))
                    continue

                site, method, param = parts
                if Logic.debug: print("[DEBUG] UID parts: site={}, method={}, param={}".format(site, method, param))

                # Prepend USGS- for new API
                sites.append('USGS-' + site)

                # Pad param to 5 digits for new API
                params.append(param.zfill(5))
                uidMap[uid] = (site, method, param)
            if not sites:
                continue

            # Unique for efficiency
            sites = ','.join(set(sites))
            joinedParams = ','.join(set(params))

            # Get API key if available, otherwise proceed without
            apiKey = keyring.get_password("DataDoctor", "usgsApiKey") or ''
            headers = {'X-Api-Key': apiKey} if apiKey else {}

            # Construct URL for daily collection
            url = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items?f=json&monitoring_location_id={}&time={}/{}&parameter_code={}&statistic_id=00003".format(
                sites, startFormatted, endFormatted, joinedParams
            )

            if Logic.debug: print("[DEBUG] Fetching USGS new API URL: {}".format(url))
            maxRetries = 3

            for attempt in range(maxRetries):
                try:
                    response = requests.get(url, headers=headers)
                    response.raise_for_status()
                    readFile = json.loads(response.content)
                    if Logic.debug: print("[DEBUG] API response: {}".format(readFile)) # Debug full response
                    features = readFile.get('features', [])
                    if Logic.debug: print("[DEBUG] Fetched {} feature entries.".format(len(features)))
                    break
                except Exception as e:
                    if attempt < maxRetries - 1:
                        print("[WARN] Retry {} of {}: USGS new API fetch failed: {} for URL: {}. Retrying...".format(attempt + 1, maxRetries, e, url))
                        time.sleep(2 ** attempt) # Exponential backoff
                    else:
                        print("[ERROR] Max retries exceeded: {} for URL: {}".format(e, url))
                        return []

            # Process features
            for uid in groupUids:
                site, method, param = uidMap.get(uid, (None, None, None))

                if not site:
                    resultDict[uid] = [] # Blank
                    continue

                # Match by site, param, and time_series_id
                matchingFeature = None

                for feature in features:
                    featureSite = feature['properties'].get('monitoring_location_id')
                    featureParam = feature['properties'].get('parameter_code')
                    featureTimeSeriesId = feature['properties'].get('time_series_id')

                    if featureSite == 'USGS-' + site and featureParam == param.zfill(5) and featureTimeSeriesId == method:
                        matchingFeature = feature
                        break
                if not matchingFeature:
                    print("[WARN] No matching feature for uid '{}': site={}, param={}, method={}. Skipping.".format(uid, site, param, method))
                    resultDict[uid] = [] # Blank
                    continue

                # Extract points
                if Logic.debug: print("[DEBUG] Found feature for '{}': properties={}".format(uid, matchingFeature['properties']))
                outputData = []

                # Collect all matching features for the UID
                matchingFeatures = [f for f in features if f['properties'].get('time_series_id') == method]

                # Sort by 'time' chronologically
                matchingFeatures.sort(key=lambda f: f['properties'].get('time'))

                for feature in matchingFeatures:
                    value = feature['properties'].get('value')
                    dateTimeStr = feature['properties'].get('time') + 'T00:00:00Z' # Use UTC midnight

                    try:
                        dateTime = datetime.fromisoformat(dateTimeStr)
                        formattedTs = dateTime.strftime('%m/%d/%y %H:%M:00')
                        if value is not None: # Ensure value exists
                            outputData.append(f"{formattedTs},{value}")
                    except ValueError as e:
                        print("[WARN] Invalid point ts skipped for '{}': {} - {}".format(uid, dateTimeStr, e))

                if Logic.debug: print("[DEBUG] Extracted {} points for '{}': {}".format(len(outputData), uid, outputData))

                # Gap check
                outputData = Logic.gapCheck(timestamps, outputData, uid)
                resultDict[uid] = outputData

        return resultDict
    else:
        return apiReadOldMethod(dataID, interval, startDate, endDate)