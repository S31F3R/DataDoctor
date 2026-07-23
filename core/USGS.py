# USGS.py
#
# DataID format: Site-Method-Parameter
#   e.g. 09428500-14eef6ee402b4c50a7341a0efccf0cd4-00065  (time_series_id)
#   e.g. 09428500-158041-00065                            (legacy numeric methodID)
#
# Routing:
#   - 32-char hex method  → modern OGC API (api.waterdata.usgs.gov)
#       continuous (HOUR/INSTANT) and daily (DAY)
#   - numeric methodID    → legacy waterservices.usgs.gov (IV/DV)
#
# API key (optional, higher rate limits on OGC API): keyring "DataDoctor"/"usgsApiKey"
#   sent as X-Api-Key when present.
# OGC limits (as of 2026): ~100 req/hr without key; higher with key.
#   Continuous max ~1100 days/request (chunked at 1000). Max 50k records/page.

import requests
import json
import keyring
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from core import Logic, Query, Config

# --- OGC (new) API constants ---
baseUrl = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
maxContinuousDays = 1000  # API hard-caps at 1100; leave margin
pageLimit = 50000
maxRetries = 3
requestTimeout = 60
dailyTsidBatch = 25

tsidRe = re.compile(r"^[0-9a-fA-F]{32}$")


def isTimeSeriesId(method):
    """True if method is a modern 32-char hex time_series_id (Aquarius-style UID)."""
    return bool(method and tsidRe.match(method))


def isNumericMethodId(method):
    """True if method is a legacy numeric NWIS methodID."""
    return bool(method and method.isdigit())


def classifyUid(uid):
    """
    Parse Site-Method-Parameter.
    Returns ('ogc', site, method, param5), ('legacy', site, method, param5),
    or None if invalid.
    """
    parts = uid.split("-")
    if len(parts) != 3:
        return None
    site, method, param = parts
    if not site or not param:
        return None
    param5 = param.zfill(5)
    if isTimeSeriesId(method):
        return ("ogc", site, method.lower(), param5)
    if isNumericMethodId(method):
        return ("legacy", site, method, param5)
    return None


# ---------------------------------------------------------------------------
# Legacy waterservices.usgs.gov (numeric methodID)
# ---------------------------------------------------------------------------

def apiReadOldMethod(dataID, interval, startDate, endDate):
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            "USGS.apiReadOldMethod called with dataID: {}, interval: {}, start: {}, end: {}".format(
                dataID, interval, startDate, endDate
            ),
        )

    timestamps = Query.buildTimestamps(startDate, endDate, interval)
    if not timestamps:
        Logic.logMessage("ERROR", "No timestamps generated - invalid dates or interval.")
        return {}

    if interval in ["HOUR"] or (isinstance(interval, str) and interval.startswith("INSTANT:")):
        usgsInterval = "iv"
    elif interval == "DAY":
        usgsInterval = "dv"
    else:
        Logic.logMessage("ERROR", "Unsupported interval: {}".format(interval))
        return {}

    try:
        startDateTime = datetime.strptime(startDate, "%Y-%m-%d %H:%M")
        endDateTime = datetime.strptime(endDate, "%Y-%m-%d %H:%M")
        # DV wants date-only; IV wants local datetime without TZ
        if usgsInterval == "dv":
            startFormatted = startDateTime.strftime("%Y-%m-%d")
            endFormatted = endDateTime.strftime("%Y-%m-%d")
        else:
            startFormatted = startDateTime.strftime("%Y-%m-%dT%H:%M")
            endFormatted = endDateTime.strftime("%Y-%m-%dT%H:%M")
    except ValueError as e:
        Logic.logMessage("ERROR", "Date parse failed: {}".format(e))
        return {}

    queryLimit = 50
    resultDict = {}

    for groupStart in range(0, len(dataID), queryLimit):
        groupUids = dataID[groupStart : groupStart + queryLimit]
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                "Processing legacy batch of {} uids: {}".format(
                    len(groupUids), groupUids[:3] if groupUids else []
                ),
            )

        sites = []
        params = []
        uidMap = {}

        for uid in groupUids:
            classified = classifyUid(uid)
            if not classified or classified[0] != "legacy":
                Logic.logMessage("WARN", "Invalid or non-numeric method uid skipped in legacy path: {}".format(uid))
                resultDict[uid] = []
                continue
            _, site, method, param = classified
            params.append(param)
            sites.append(site)
            uidMap[uid] = (site, method, param)

        if not sites:
            continue

        sitesJoined = ",".join(set(sites))
        joinedParams = ",".join(set(params))

        url = (
            "https://waterservices.usgs.gov/nwis/{}/?format=json&sites={}"
            "&startDT={}&endDT={}&parameterCd={}&siteStatus=all".format(
                usgsInterval, sitesJoined, startFormatted, endFormatted, joinedParams
            )
        )

        if Config.debug:
            Logic.logMessage("DEBUG", "Fetching USGS legacy URL: {}".format(url))

        maxRetries = 3
        timeout = 10
        timeSeriesList = None

        for attempt in range(maxRetries):
            try:
                response = requests.get(url, timeout=timeout, verify=True)
                response.raise_for_status()
                readFile = json.loads(response.content)
                timeSeriesList = readFile["value"]["timeSeries"]
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        "Fetched {} timeSeries entries.".format(len(timeSeriesList)),
                    )
                break
            except requests.exceptions.SSLError as e:
                if attempt < maxRetries - 1:
                    Logic.logMessage(
                        "WARN",
                        "Retry {} of {}: SSL error: {}. Retrying with increased timeout and disabled verification...".format(
                            attempt + 1, maxRetries, e
                        ),
                    )
                    timeout *= 2
                    time.sleep(2 ** attempt)
                    try:
                        response = requests.get(url, timeout=timeout, verify=False)
                        response.raise_for_status()
                        readFile = json.loads(response.content)
                        timeSeriesList = readFile["value"]["timeSeries"]
                        Logic.logMessage(
                            "WARN",
                            "SSL verification disabled for this request. Update OpenSSL or check network.",
                        )
                        break
                    except Exception as e2:
                        Logic.logMessage("WARN", "SSL fallback failed: {}".format(e2))
                else:
                    Logic.logMessage(
                        "ERROR",
                        "Max retries exceeded: {} for URL: {}. Update OpenSSL or use a different network.".format(
                            e, url
                        ),
                    )
                    return resultDict
            except requests.exceptions.RequestException as e:
                if attempt < maxRetries - 1:
                    Logic.logMessage(
                        "WARN",
                        "Retry {} of {}: Request failed: {} for URL: {}. Retrying...".format(
                            attempt + 1, maxRetries, e, url
                        ),
                    )
                    timeout *= 2
                    time.sleep(2 ** attempt)
                else:
                    Logic.logMessage("ERROR", "Max retries exceeded: {} for URL: {}".format(e, url))
                    return resultDict

        if timeSeriesList is None:
            for uid in groupUids:
                resultDict.setdefault(uid, [])
            continue

        for uid in groupUids:
            site, method, param = uidMap.get(uid, (None, None, None))
            if not site:
                resultDict[uid] = []
                continue

            matchingSeries = None
            for series in timeSeriesList:
                seriesSite = (
                    series["sourceInfo"]["siteCode"][0]["value"]
                    if "sourceInfo" in series and "siteCode" in series["sourceInfo"]
                    else None
                )
                seriesParam = (
                    series["variable"]["variableCode"][0]["value"]
                    if "variable" in series and "variableCode" in series["variable"]
                    else None
                )

                if seriesSite == site and seriesParam == param:
                    seriesValues = series["values"]
                    if seriesValues and "method" in seriesValues[0] and seriesValues[0]["method"]:
                        seriesMethodId = seriesValues[0]["method"][0]["methodID"]
                        if str(seriesMethodId) == method:
                            matchingSeries = series
                            break

            if not matchingSeries:
                Logic.logMessage(
                    "WARN",
                    "No matching series for uid '{}': site={}, param={}, method={}. Skipping.".format(
                        uid, site, param, method
                    ),
                )
                resultDict[uid] = []
                continue

            dataPoints = matchingSeries["values"][0]["value"]
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    "Found series for '{}': {} points, siteName={}".format(
                        uid, len(dataPoints), matchingSeries["sourceInfo"]["siteName"]
                    ),
                )
            outputData = []
            for point in dataPoints:
                value = point["value"]
                dateTimeStr = point["dateTime"].replace("T", " ").split(".")[0]
                try:
                    dateTime = datetime.fromisoformat(dateTimeStr.replace(" ", "T"))
                    formattedTs = dateTime.strftime("%m/%d/%y %H:%M:00")
                    outputData.append("{},{}".format(formattedTs, value))
                except ValueError as e:
                    Logic.logMessage(
                        "WARN",
                        "Invalid point ts skipped for '{}': {} - {}".format(uid, dateTimeStr, e),
                    )

            resultDict[uid] = Query.gapCheck(timestamps, outputData, uid)

    return resultDict


# ---------------------------------------------------------------------------
# Modern OGC API (32-char hex time_series_id)
# ---------------------------------------------------------------------------

def apiHeaders():
    headers = {"Accept": "application/json"}
    apiKey = keyring.get_password("DataDoctor", "usgsApiKey") or ""
    if apiKey:
        headers["X-Api-Key"] = apiKey
    return headers


def getOffsetHours():
    return Logic.getUtcOffsetInt(Config.utcOffset)


def localToUtc(dt, offsetHours):
    return dt - timedelta(hours=offsetHours)


def utcToLocal(dt, offsetHours):
    return dt + timedelta(hours=offsetHours)


def parseApiTime(timeStr):
    if not timeStr:
        raise ValueError("empty time")
    if len(timeStr) == 10 and timeStr[4] == "-" and timeStr[7] == "-":
        return datetime.strptime(timeStr, "%Y-%m-%d")
    normalized = timeStr.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        utcOffset = dt.utcoffset() or timedelta(0)
        dt = (dt - utcOffset).replace(tzinfo=None)
    return dt


def chunkDateRange(startUtc, endUtc, maxDays):
    if startUtc > endUtc:
        return
    chunkStart = startUtc
    maxDelta = timedelta(days=maxDays)
    while chunkStart <= endUtc:
        chunkEnd = min(chunkStart + maxDelta, endUtc)
        yield chunkStart, chunkEnd
        if chunkEnd >= endUtc:
            break
        chunkStart = chunkEnd + timedelta(seconds=1)


def fetchFeatures(url, headers):
    features = []
    currentUrl = url
    page = 0

    while currentUrl:
        page += 1
        timeout = requestTimeout
        response = None

        for attempt in range(maxRetries):
            try:
                response = requests.get(currentUrl, headers=headers, timeout=timeout)
                if response.status_code == 429:
                    retryAfter = response.headers.get("Retry-After")
                    wait = int(retryAfter) if retryAfter and retryAfter.isdigit() else (2 ** attempt) * 5
                    Logic.logMessage(
                        "WARN",
                        "USGS rate limited (429). Waiting {}s before retry {}/{}.".format(
                            wait, attempt + 1, maxRetries
                        ),
                    )
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < maxRetries - 1:
                    timeout *= 2
                    wait = 2 ** attempt
                    Logic.logMessage(
                        "WARN",
                        "Retry {} of {}: USGS OGC fetch failed: {}. Retrying in {}s...".format(
                            attempt + 1, maxRetries, e, wait
                        ),
                    )
                    time.sleep(wait)
                else:
                    Logic.logMessage(
                        "ERROR",
                        "Max retries exceeded for USGS OGC URL: {} — {}".format(currentUrl, e),
                    )
                    return features

        try:
            payload = json.loads(response.content)
        except (ValueError, TypeError) as e:
            Logic.logMessage("ERROR", "USGS OGC response JSON parse failed: {}".format(e))
            return features

        if isinstance(payload, dict) and payload.get("code") and "features" not in payload:
            Logic.logMessage(
                "ERROR",
                "USGS OGC API error {}: {}".format(
                    payload.get("code"), payload.get("description", payload)
                ),
            )
            return features

        pageFeatures = payload.get("features") or []
        features.extend(pageFeatures)

        if Config.debug:
            remaining = response.headers.get("X-RateLimit-Remaining")
            limit = response.headers.get("X-RateLimit-Limit")
            Logic.logMessage(
                "DEBUG",
                "USGS OGC page {}: +{} features (total {}), rate {}/{}".format(
                    page, len(pageFeatures), len(features), remaining, limit
                ),
            )

        nextUrl = None
        for link in payload.get("links") or []:
            if link.get("rel") == "next" and link.get("href"):
                nextUrl = link["href"]
                break
        currentUrl = nextUrl

    return features


def buildCollectionUrl(collection, timeSeriesIds, timeStart, timeEnd):
    params = {
        "f": "json",
        "time_series_id": ",".join(timeSeriesIds),
        "time": "{}/{}".format(timeStart, timeEnd),
        "limit": pageLimit,
        "skipGeometry": "true",
        "properties": "time_series_id,time,value",
    }
    return "{}/{}/items?{}".format(baseUrl, collection, urlencode(params))


def featuresToOutput(features, timeSeriesId, interval, offsetHours):
    points = []
    for feature in features:
        props = feature.get("properties") or {}
        tsid = (props.get("time_series_id") or props.get("timeseries_id") or "").lower()
        if tsid != timeSeriesId:
            continue
        value = props.get("value")
        timeStr = props.get("time")
        if value is None or timeStr is None:
            continue
        try:
            apiDt = parseApiTime(timeStr)
            if interval == "DAY":
                localDt = apiDt.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                localDt = utcToLocal(apiDt, offsetHours)
            formattedTs = localDt.strftime("%m/%d/%y %H:%M:00")
            points.append((localDt, "{},{}".format(formattedTs, value)))
        except (ValueError, TypeError) as e:
            Logic.logMessage(
                "WARN",
                "Invalid USGS OGC point skipped (tsid={}): {} — {}".format(
                    timeSeriesId, timeStr, e
                ),
            )

    points.sort(key=lambda p: p[0])
    deduped = {}
    for dt, line in points:
        deduped[dt] = line
    return [deduped[k] for k in sorted(deduped.keys())]


def apiReadNewMethod(dataID, interval, startDate, endDate):
    """OGC continuous/daily path for Site-time_series_id-Parameter DataIDs."""
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            "USGS.apiReadNewMethod called with dataID: {}, interval: {}, start: {}, end: {}".format(
                dataID, interval, startDate, endDate
            ),
        )

    timestamps = Query.buildTimestamps(startDate, endDate, interval)
    if not timestamps:
        Logic.logMessage("ERROR", "No timestamps generated - invalid dates or interval.")
        return {}

    if interval == "DAY":
        collection = "daily"
    elif interval in ("HOUR",) or (isinstance(interval, str) and interval.startswith("INSTANT:")):
        collection = "continuous"
    else:
        Logic.logMessage("ERROR", "Unsupported interval for USGS OGC: {}".format(interval))
        return {}

    try:
        startLocal = datetime.strptime(startDate, "%Y-%m-%d %H:%M")
        endLocal = datetime.strptime(endDate, "%Y-%m-%d %H:%M")
    except ValueError as e:
        Logic.logMessage("ERROR", "Date parse failed: {}".format(e))
        return {}

    offsetHours = getOffsetHours()
    headers = apiHeaders()
    if Config.debug:
        Logic.logMessage("DEBUG", "USGS API key present: {}".format("X-Api-Key" in headers))

    uidMap = {}
    for uid in dataID:
        classified = classifyUid(uid)
        if not classified or classified[0] != "ogc":
            Logic.logMessage(
                "WARN",
                "Invalid or non-UID method skipped in OGC path: {}".format(uid),
            )
            uidMap[uid] = None
            continue
        _, site, tsid, param = classified
        uidMap[uid] = (site, tsid, param)

    validUids = [u for u, p in uidMap.items() if p]
    resultDict = {uid: [] for uid in dataID}
    if not validUids:
        return resultDict

    if collection == "daily":
        timeStart = startLocal.strftime("%Y-%m-%d")
        timeEnd = endLocal.strftime("%Y-%m-%d")
        tsids = [uidMap[u][1] for u in validUids]
        for batchStart in range(0, len(tsids), dailyTsidBatch):
            batchTsids = tsids[batchStart : batchStart + dailyTsidBatch]
            batchUids = [u for u in validUids if uidMap[u][1] in batchTsids]
            url = buildCollectionUrl("daily", batchTsids, timeStart, timeEnd)
            if Config.debug:
                Logic.logMessage("DEBUG", "Fetching USGS OGC daily URL: {}".format(url))
            features = fetchFeatures(url, headers)
            for uid in batchUids:
                _, tsid, _ = uidMap[uid]
                outputData = featuresToOutput(features, tsid, interval, offsetHours)
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        "Extracted {} daily points for '{}': sample {}".format(
                            len(outputData), uid, outputData[:3]
                        ),
                    )
                resultDict[uid] = Query.gapCheck(timestamps, outputData, uid)
    else:
        startUtc = localToUtc(startLocal, offsetHours)
        endUtc = localToUtc(endLocal, offsetHours)

        for uid in validUids:
            _, tsid, _ = uidMap[uid]
            allFeatures = []
            for chunkStart, chunkEnd in chunkDateRange(startUtc, endUtc, maxContinuousDays):
                timeStart = chunkStart.strftime("%Y-%m-%dT%H:%M:%SZ")
                timeEnd = chunkEnd.strftime("%Y-%m-%dT%H:%M:%SZ")
                url = buildCollectionUrl("continuous", [tsid], timeStart, timeEnd)
                if Config.debug:
                    Logic.logMessage("DEBUG", "Fetching USGS OGC continuous URL: {}".format(url))
                features = fetchFeatures(url, headers)
                allFeatures.extend(features)

            outputData = featuresToOutput(allFeatures, tsid, interval, offsetHours)
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    "Extracted {} continuous points for '{}': sample {}".format(
                        len(outputData), uid, outputData[:3]
                    ),
                )
            if not allFeatures:
                Logic.logMessage(
                    "WARN",
                    "No matching continuous data for uid '{}' (time_series_id={}).".format(
                        uid, tsid
                    ),
                )
            resultDict[uid] = Query.gapCheck(timestamps, outputData, uid)

    return resultDict


# ---------------------------------------------------------------------------
# Public entry — route each DataID by method form
# ---------------------------------------------------------------------------

def apiRead(dataID, interval, startDate, endDate):
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            "USGS.apiRead called with dataID: {}, interval: {}, start: {}, end: {}".format(
                dataID, interval, startDate, endDate
            ),
        )

    if not dataID:
        return {}

    ogcIds = []
    legacyIds = []
    resultDict = {}

    for uid in dataID:
        classified = classifyUid(uid)
        if not classified:
            Logic.logMessage(
                "WARN",
                "Invalid USGS uid '{}' — expected Site-Method-Parameter "
                "(Method = numeric methodID or 32-char hex time_series_id).".format(uid),
            )
            resultDict[uid] = []
            continue
        kind = classified[0]
        if kind == "ogc":
            ogcIds.append(uid)
        else:
            legacyIds.append(uid)

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            "USGS.apiRead routing: {} OGC (time_series_id), {} legacy (numeric methodID)".format(
                len(ogcIds), len(legacyIds)
            ),
        )

    if ogcIds:
        ogcResult = apiReadNewMethod(ogcIds, interval, startDate, endDate)
        if isinstance(ogcResult, dict):
            resultDict.update(ogcResult)
        else:
            for uid in ogcIds:
                resultDict[uid] = []

    if legacyIds:
        legacyResult = apiReadOldMethod(legacyIds, interval, startDate, endDate)
        if isinstance(legacyResult, dict):
            resultDict.update(legacyResult)
        else:
            for uid in legacyIds:
                resultDict[uid] = []

    # Preserve input order keys even if a path returned incomplete
    for uid in dataID:
        resultDict.setdefault(uid, [])

    return resultDict
