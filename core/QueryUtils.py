from core import Config
from PyQt6.QtGui import QColor
import numpy as np # For delta computation

def processDeltaOverlay(data, dataIds, databases, lookupIds, intervals, queryItems, deltaChecked, overlayChecked):
    """
    Post-process query data for delta and overlay features.
    Parses values, processes pairs, applies logic, and reconstructs data with metadata.
    """
    if Config.debug:
        print("[DEBUG] processDeltaOverlay: Starting with {} rows, {} columns, delta={}, overlay={}".format(len(data), len(dataIds), deltaChecked, overlayChecked))

    # Parse data to timestamps and 2D list of floats/None
    timestamps = []
    values = []
    for rowStr in data:
        parts = rowStr.split(',')
        timestamps.append(parts[0].strip())
        rowValues = []
        for valStr in parts[1:]:
            valStr = valStr.strip()
            try:
                rowValues.append(float(valStr) if valStr else np.nan)
            except ValueError:
                rowValues.append(np.nan)
        values.append(rowValues)

    values = np.array(values)  # For easier computation

    numRows, numCols = values.shape

    # Query infos
    queryInfos = [f"{item[0]}|{item[1]}|{item[2]}" for item in queryItems]

    # Determine pairs
    pairs = [(i, i+1) for i in range(0, numCols, 2)]

    if numCols % 2 == 1 and (deltaChecked or overlayChecked):
        print("[WARN] Odd number of query items; last item omitted from delta/overlay processing.")

    # Build new structures
    newValues = [[] for _ in range(numRows)]  # Will hold floats/None
    newDataIds = []
    newDatabases = []
    newLookupIds = []
    newIntervals = []
    columnMetadata = []
    overlayInfo = []

    col = 0
    pairIndex = 0
    while col < numCols:
        if col < numCols - 1 and (deltaChecked or overlayChecked):
            pIdx = col
            sIdx = col + 1
            primaryVals = values[:, pIdx]
            secondaryVals = values[:, sIdx]
            deltas = np.subtract(primaryVals, secondaryVals)
            deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan

            # In displays
            displays = np.copy(primaryVals)
            displays[np.isnan(primaryVals)] = secondaryVals[np.isnan(primaryVals)]

            if overlayChecked:
                # Compute display floats
                displays = np.where(np.isfinite(primaryVals), primaryVals, secondaryVals)
                displays = np.where(np.logical_and(np.isnan(primaryVals), np.isnan(secondaryVals)), np.nan, displays)

                # Add overlay column
                for r in range(numRows):
                    newValues[r].append(displays[r])

                newDataIds.append(dataIds[pIdx])
                newDatabases.append(databases[pIdx])
                newLookupIds.append(lookupIds[pIdx])
                newIntervals.append(intervals[pIdx])

                columnMetadata.append({
                    'type': 'overlay',
                    'dataIds': [dataIds[pIdx], dataIds[sIdx]],
                    'dbs': [databases[pIdx], databases[sIdx]],
                    'queryInfos': [queryInfos[pIdx], queryInfos[sIdx]],
                    'pairIndex': pairIndex
                })

                overlayInfo.append({
                    'primaryVal': primaryVals,
                    'secondaryVal': secondaryVals,
                    'delta': deltas,
                    'dataId1': dataIds[pIdx],
                    'dataId2': dataIds[sIdx],
                    'db1': databases[pIdx],
                    'db2': databases[sIdx]
                })

                # Add delta column if checked
                if deltaChecked:
                    for r in range(numRows):
                        newValues[r].append(deltas[r])

                    newDataIds.append('Delta')
                    newDatabases.append(None)
                    newLookupIds.append(None)
                    newIntervals.append('')

                    columnMetadata.append({
                        'type': 'delta',
                        'dataIds': [dataIds[pIdx], dataIds[sIdx]],
                        'dbs': [databases[pIdx], databases[sIdx]],
                        'queryInfos': [queryInfos[pIdx], queryInfos[sIdx]],
                        'pairIndex': pairIndex
                    })

                    overlayInfo.append(None)

                pairIndex += 1
                col += 2
                continue

            else:
                # No overlay, add primary and secondary as normal
                for idx in [pIdx, sIdx]:
                    for r in range(numRows):
                        newValues[r].append(values[r, idx])

                    newDataIds.append(dataIds[idx])
                    newDatabases.append(databases[idx])
                    newLookupIds.append(lookupIds[idx])
                    newIntervals.append(intervals[idx])

                    columnMetadata.append({
                        'type': 'normal',
                        'dataIds': [dataIds[idx]],
                        'dbs': [databases[idx]],
                        'queryInfos': [queryInfos[idx]]
                    })

                    overlayInfo.append(None)

                # Add delta if checked
                if deltaChecked:
                    for r in range(numRows):
                        newValues[r].append(deltas[r])

                    newDataIds.append('Delta')
                    newDatabases.append(None)
                    newLookupIds.append(None)
                    newIntervals.append('')

                    columnMetadata.append({
                        'type': 'delta',
                        'dataIds': [dataIds[pIdx], dataIds[sIdx]],
                        'dbs': [databases[pIdx], databases[sIdx]],
                        'queryInfos': [queryInfos[pIdx], queryInfos[sIdx]],
                        'pairIndex': pairIndex
                    })

                    overlayInfo.append(None)

                pairIndex += 1
                col += 2
                continue

        # Odd last or non-pair
        for r in range(numRows):
            newValues[r].append(values[r, col])

        newDataIds.append(dataIds[col])
        newDatabases.append(databases[col])
        newLookupIds.append(lookupIds[col])
        newIntervals.append(intervals[col])

        columnMetadata.append({
            'type': 'normal',
            'dataIds': [dataIds[col]],
            'dbs': [databases[col]],
            'queryInfos': [queryInfos[col]]
        })

        overlayInfo.append(None)

        col += 1

    # Reconstruct data as list of strings
    newData = []
    for r in range(numRows):
        rowStrs = []
        for c in range(len(newDataIds)):
            val = newValues[r][c]
            valStr = '' if np.isnan(val) else str(val)
            rowStrs.append(valStr)
        newData.append(f"{timestamps[r]},{','.join(rowStrs)}")

    if Config.debug:
        print("[DEBUG] processDeltaOverlay: Completed with {} new columns".format(len(newDataIds)))

    return newData, newDataIds, newDatabases, newLookupIds, newIntervals, columnMetadata, overlayInfo