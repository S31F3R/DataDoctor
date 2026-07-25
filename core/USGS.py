# USGS.py
#
# DataID format: Site-Method-Parameter
#   e.g. 09428500-14eef6ee402b4c50a7341a0efccf0cd4-00065  (time_series_id)
#   e.g. 09428500-158041-00065                            (legacy numeric methodID)
#
# Routing:
#   - 32-char hex method  → modern OGC API (api.waterdata.usgs.gov)
#       continuous (HOUR/INSTANT) and daily (DAY) only —
#       OGC collections have no monthly/yearly time-series products
#   - numeric methodID    → legacy waterservices.usgs.gov (IV/DV only)
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
                resultDict[uid] = {
                    "data": [],
                    "rawResponse": emptyLegacyRawResponse(),
                }
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
                resultDict.setdefault(
                    uid,
                    {"data": [], "rawResponse": emptyLegacyRawResponse()},
                )
            continue

        for uid in groupUids:
            site, method, param = uidMap.get(uid, (None, None, None))
            if not site:
                resultDict[uid] = {
                    "data": [],
                    "rawResponse": emptyLegacyRawResponse(),
                }
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
                resultDict[uid] = {
                    "data": [],
                    "rawResponse": emptyLegacyRawResponse(),
                }
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
                    formattedTs = Query.formatTimestamp(dateTime, interval)
                    outputData.append("{},{}".format(formattedTs, value))
                except ValueError as e:
                    Logic.logMessage(
                        "WARN",
                        "Invalid point ts skipped for '{}': {} - {}".format(uid, dateTimeStr, e),
                    )

            resultDict[uid] = {
                "data": Query.gapCheck(timestamps, outputData, uid, interval=interval),
                "rawResponse": emptyLegacyRawResponse(),
            }

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
    # Request full feature properties (needed for internal query context-menu metadata).
    # skipGeometry keeps payloads smaller; site lat/lon comes from monitoring-locations.
    params = {
        "f": "json",
        "time_series_id": ",".join(timeSeriesIds),
        "time": "{}/{}".format(timeStart, timeEnd),
        "limit": pageLimit,
        "skipGeometry": "true",
    }
    return "{}/{}/items?{}".format(baseUrl, collection, urlencode(params))


def emptyLegacyRawResponse():
    """Legacy (numeric methodID) path: no rich metadata — details UI shows blanks."""
    return {"kind": "legacy", "seriesMeta": {}, "points": []}


def emptyOgcRawResponse():
    return {"kind": "ogc", "seriesMeta": {}, "points": []}


def formatThresholds(thresholds):
    """Turn time-series-metadata thresholds array into a short display string."""
    if not thresholds:
        return ""
    lines = []
    try:
        for item in thresholds:
            if not isinstance(item, dict):
                continue
            name = item.get("Name") or item.get("name") or "Threshold"
            periods = item.get("Periods") or item.get("periods") or []
            ref = ""
            if periods and isinstance(periods[0], dict):
                refVal = periods[0].get("ReferenceValue")
                if refVal is not None:
                    ref = str(refVal)
            if ref:
                lines.append("{}: {}".format(name, ref))
            else:
                lines.append(str(name))
    except Exception:
        return ""
    return "; ".join(lines)


def fetchJsonFeatures(url, headers):
    """GET a single OGC items page and return feature list (best-effort)."""
    try:
        response = requests.get(url, headers=headers, timeout=requestTimeout)
        if response.status_code == 429:
            time.sleep(2)
            response = requests.get(url, headers=headers, timeout=requestTimeout)
        response.raise_for_status()
        payload = response.json()
        return payload.get("features") or []
    except Exception as e:
        Logic.logMessage("WARN", "USGS metadata fetch failed for {}: {}".format(url, e))
        return []


def fetchTimeSeriesMetadata(tsid, headers, cache):
    """Series-level metadata from time-series-metadata collection."""
    key = (tsid or "").lower()
    if key in cache:
        return cache[key]
    props = {}
    if key:
        url = "{}/time-series-metadata/items?{}".format(
            baseUrl, urlencode({"f": "json", "id": key, "limit": "1"})
        )
        features = fetchJsonFeatures(url, headers)
        if features:
            props = features[0].get("properties") or {}
    cache[key] = props
    return props


def fetchMonitoringLocation(site, headers, cache):
    """Site-level metadata from monitoring-locations collection."""
    site = (site or "").strip()
    mid = site if site.upper().startswith("USGS-") else "USGS-{}".format(site)
    if mid in cache:
        return cache[mid]
    props = {}
    if site:
        url = "{}/monitoring-locations/items?{}".format(
            baseUrl, urlencode({"f": "json", "id": mid, "limit": "1"})
        )
        features = fetchJsonFeatures(url, headers)
        if features:
            props = features[0].get("properties") or {}
    cache[mid] = props
    return props


def buildSeriesMeta(site, tsid, param, seriesProps, locationProps):
    """Friendly series/site tags for context menu (USBR-style Type/Value rows)."""
    seriesProps = seriesProps or {}
    locationProps = locationProps or {}
    mid = locationProps.get("id") or seriesProps.get("monitoring_location_id") or (
        "USGS-{}".format(site) if site else ""
    )
    return {
        "Time Series ID": seriesProps.get("id") or tsid or "",
        "Monitoring Location ID": mid or "",
        "Site Name": locationProps.get("monitoring_location_name") or "",
        "Site Type": locationProps.get("site_type") or "",
        "Site Type Code": locationProps.get("site_type_code") or "",
        "Agency": locationProps.get("agency_name") or locationProps.get("agency_code") or "",
        "Parameter Name": seriesProps.get("parameter_name") or "",
        "Parameter Description": seriesProps.get("parameter_description") or "",
        "Parameter Code": seriesProps.get("parameter_code") or param or "",
        "Statistic ID": seriesProps.get("statistic_id") or "",
        "Unit of Measure": seriesProps.get("unit_of_measure") or "",
        "Sublocation": seriesProps.get("sublocation_identifier") or "",
        "Computation": seriesProps.get("computation_identifier") or "",
        "Computation Period": seriesProps.get("computation_period_identifier") or "",
        "Series Begin (UTC)": seriesProps.get("begin_utc") or seriesProps.get("begin") or "",
        "Series End (UTC)": seriesProps.get("end_utc") or seriesProps.get("end") or "",
        "State": locationProps.get("state_name") or seriesProps.get("state_name") or "",
        "County": locationProps.get("county_name") or "",
        "HUC": locationProps.get("hydrologic_unit_code")
        or seriesProps.get("hydrologic_unit_code")
        or "",
        "Time Zone": locationProps.get("time_zone_abbreviation") or "",
        "Uses Daylight Savings": locationProps.get("uses_daylight_savings") or "",
        "Altitude": ""
        if locationProps.get("altitude") is None
        else str(locationProps.get("altitude")),
        "Vertical Datum": locationProps.get("vertical_datum_name")
        or locationProps.get("vertical_datum")
        or "",
        "Data Gap Interval": seriesProps.get("data_gap_interval") or "",
        "Web Description": seriesProps.get("web_description") or "",
        "Thresholds": formatThresholds(seriesProps.get("thresholds")),
        "Series Last Modified": seriesProps.get("last_modified") or "",
    }


def featuresToOutput(features, timeSeriesId, interval, offsetHours):
    """
    Convert OGC features to:
      - output lines: 'mm/dd/yy HH:MM:00,value'
      - point meta list: dicts with Timestamp + per-observation fields
    """
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
            formattedTs = Query.formatTimestamp(localDt, interval)
            qualifier = props.get("qualifier")
            if qualifier is None:
                qualifier = ""
            pointMeta = {
                "Timestamp": formattedTs,
                "Value": str(value),
                "Time (UTC)": str(timeStr),
                "Unit of Measure": props.get("unit_of_measure") or "",
                "Approval Status": props.get("approval_status") or "",
                "Qualifier": str(qualifier) if qualifier != "" else "",
                "Last Modified": props.get("last_modified") or "",
                "Parameter Code": props.get("parameter_code") or "",
                "Statistic ID": props.get("statistic_id") or "",
                "Time Series ID": tsid or "",
                "Monitoring Location ID": props.get("monitoring_location_id") or "",
            }
            points.append((localDt, "{},{}".format(formattedTs, value), pointMeta))
        except (ValueError, TypeError) as e:
            Logic.logMessage(
                "WARN",
                "Invalid USGS OGC point skipped (tsid={}): {} — {}".format(
                    timeSeriesId, timeStr, e
                ),
            )

    points.sort(key=lambda p: p[0])
    dedupedLines = {}
    dedupedMeta = {}
    for dt, line, meta in points:
        dedupedLines[dt] = line
        dedupedMeta[dt] = meta
    orderedKeys = sorted(dedupedLines.keys())
    outputData = [dedupedLines[k] for k in orderedKeys]
    pointList = [dedupedMeta[k] for k in orderedKeys]
    return outputData, pointList


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
    resultDict = {
        uid: {"data": [], "rawResponse": emptyOgcRawResponse()} for uid in dataID
    }
    if not validUids:
        return resultDict

    seriesCache = {}
    locationCache = {}

    def packResult(uid, site, tsid, param, outputData, pointList):
        seriesProps = fetchTimeSeriesMetadata(tsid, headers, seriesCache)
        locationProps = fetchMonitoringLocation(site, headers, locationCache)
        seriesMeta = buildSeriesMeta(site, tsid, param, seriesProps, locationProps)
        rawResponse = {
            "kind": "ogc",
            "seriesMeta": seriesMeta,
            "points": pointList or [],
        }
        resultDict[uid] = {
            "data": Query.gapCheck(timestamps, outputData, uid, interval=interval),
            "rawResponse": rawResponse,
        }

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
                site, tsid, param = uidMap[uid]
                outputData, pointList = featuresToOutput(
                    features, tsid, interval, offsetHours
                )
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        "Extracted {} daily points for '{}': sample {}".format(
                            len(outputData), uid, outputData[:3]
                        ),
                    )
                packResult(uid, site, tsid, param, outputData, pointList)
    else:
        startUtc = localToUtc(startLocal, offsetHours)
        endUtc = localToUtc(endLocal, offsetHours)

        for uid in validUids:
            site, tsid, param = uidMap[uid]
            allFeatures = []
            for chunkStart, chunkEnd in chunkDateRange(startUtc, endUtc, maxContinuousDays):
                timeStart = chunkStart.strftime("%Y-%m-%dT%H:%M:%SZ")
                timeEnd = chunkEnd.strftime("%Y-%m-%dT%H:%M:%SZ")
                url = buildCollectionUrl("continuous", [tsid], timeStart, timeEnd)
                if Config.debug:
                    Logic.logMessage("DEBUG", "Fetching USGS OGC continuous URL: {}".format(url))
                features = fetchFeatures(url, headers)
                allFeatures.extend(features)

            outputData, pointList = featuresToOutput(
                allFeatures, tsid, interval, offsetHours
            )
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
            packResult(uid, site, tsid, param, outputData, pointList)

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
            resultDict[uid] = {
                "data": [],
                "rawResponse": emptyLegacyRawResponse(),
            }
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
                resultDict[uid] = {"data": [], "rawResponse": emptyOgcRawResponse()}

    if legacyIds:
        legacyResult = apiReadOldMethod(legacyIds, interval, startDate, endDate)
        if isinstance(legacyResult, dict):
            resultDict.update(legacyResult)
        else:
            for uid in legacyIds:
                resultDict[uid] = {
                    "data": [],
                    "rawResponse": emptyLegacyRawResponse(),
                }

    # Preserve input order keys even if a path returned incomplete
    for uid in dataID:
        resultDict.setdefault(
            uid, {"data": [], "rawResponse": emptyLegacyRawResponse()}
        )

    return resultDict
