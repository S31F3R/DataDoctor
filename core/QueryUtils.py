# QueryUtils.py

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import QTableWidgetItem
from core import Logic, Config
from DataDoctor import uiMain

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

            if overlayChecked:
                # Compute display floats
                displays = np.copy(primaryVals)
                displays[np.isnan(primaryVals)] = secondaryVals[np.isnan(primaryVals)]

                # Add overlay column
                for r in range(numRows):
                    newValues[r].append(displays[r] if np.isfinite(displays[r]) else None)

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
                        newValues[r].append(deltas[r] if np.isfinite(deltas[r]) else None)

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
                        newValues[r].append(values[r, idx] if np.isfinite(values[r, idx]) else None)

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
                        newValues[r].append(deltas[r] if np.isfinite(deltas[r]) else None)

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
            newValues[r].append(values[r, col] if np.isfinite(values[r, col]) else None)

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

    # Reconstruct data as list of strings, apply precision only when displaying in table
    newData = []
    for r in range(numRows):
        rowStrs = [str(newValues[r][c]) if newValues[r][c] is not None else '' for c in range(len(newDataIds))]
        newData.append(f"{timestamps[r]},{','.join(rowStrs)}")

    if Config.debug:
        print("[DEBUG] processDeltaOverlay: Completed with {} new columns".format(len(newDataIds)))

    return newData, newDataIds, newDatabases, newLookupIds, newIntervals, columnMetadata, overlayInfo

def modifyTableForDeltaOverlay(table, deltaChecked, overlayChecked, databases, queryItems, labelsDict, dataDictionaryTable, intervals, lookupIds):
    if Config.debug:
        print("[DEBUG] modifyTableForDeltaOverlay: Starting with delta={}, overlay={}".format(deltaChecked, overlayChecked))

    numRows = table.rowCount()
    numCols = table.columnCount()

    # Extract current data as 2D array of floats/nan, and strings for display
    values = np.full((numRows, numCols), np.nan)
    displayTexts = [[''] * numCols for _ in range(numRows)]
    for r in range(numRows):
        for c in range(numCols):
            item = table.item(r, c)
            if item:
                displayTexts[r][c] = item.text()
                try:
                    values[r, c] = float(item.text()) if item.text() else np.nan
                except ValueError:
                    values[r, c] = np.nan

    # Original dataIds from lookupIds (or adjust if buildHeader available)
    dataIds = lookupIds if lookupIds else [table.horizontalHeaderItem(c).text().split('\n')[-1].strip() for c in range(numCols)]

    # Query infos
    queryInfos = [f"{item[0]}|{item[1]}|{item[2]}" for item in queryItems]

    # Determine pairs based on original numCols
    pairs = [(i, i+1) for i in range(0, numCols, 2)]

    if numCols % 2 == 1 and (deltaChecked or overlayChecked):
        print("[WARN] Odd number of query items; last item omitted from delta/overlay processing.")

    # Process pairs, add/remove columns in place
    addedCols = 0
    columnMetadata = []
    for pairIndex, (pIdx, sIdx) in enumerate(pairs):
        pIdx += addedCols  # Adjust for inserted/removed
        sIdx += addedCols
        primaryVals = values[:, pIdx]
        secondaryVals = values[:, sIdx]
        deltas = np.subtract(primaryVals, secondaryVals)
        deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan

        if overlayChecked:
            # Replace pIdx with combined, remove sIdx
            for r in range(numRows):
                item = table.item(r, pIdx)
                if item:
                    hasP = np.isfinite(primaryVals[r])
                    hasS = np.isfinite(secondaryVals[r])
                    d = deltas[r]
                    if hasP and hasS:
                        if d != 0:
                            item.setForeground(QColor(255, 0, 0))  # Red
                    elif not hasP and hasS:
                        item.setBackground(QColor(221, 160, 221))  # Light purple
                        item.setForeground(QColor(0, 0, 0))
                    elif hasP and not hasS:
                        item.setBackground(QColor(255, 182, 193))  # Light pink
                        item.setForeground(QColor(0, 0, 0))
                    # Set data for details
                    p = primaryVals[r]
                    s = secondaryVals[r]
                    pStr = Logic.valuePrecision(str(p)) if hasP and not Config.rawData else str(p) if hasP else ''
                    sStr = Logic.valuePrecision(str(s)) if hasS and not Config.rawData else str(s) if hasS else ''
                    dStr = Logic.valuePrecision(str(d)) if np.isfinite(d) and not Config.rawData else str(d) if np.isfinite(d) else ''
                    item.setData(Qt.UserRole, {
                        'primaryVal': pStr,
                        'secondaryVal': sStr,
                        'delta': dStr,
                        'dataId1': dataIds[pIdx],
                        'dataId2': dataIds[sIdx],
                        'db1': databases[pIdx],
                        'db2': databases[sIdx]
                    })
                    # Update text to display (use p if available, else s)
                    newText = pStr if hasP else sStr if hasS else ''
                    item.setText(newText)
            # Remove sIdx column
            table.removeColumn(sIdx)
            addedCols -= 1
            # Update header for overlay (primary's, already set)

            columnMetadata.append({
                'type': 'overlay',
                'dataIds': [dataIds[pIdx], dataIds[sIdx]],
                'dbs': [databases[pIdx], databases[sIdx]],
                'queryInfos': [queryInfos[pIdx], queryInfos[sIdx]],
                'pairIndex': pairIndex
            })

        else:
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pIdx]],
                'dbs': [databases[pIdx]],
                'queryInfos': [queryInfos[pIdx]]
            })
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[sIdx]],
                'dbs': [databases[sIdx]],
                'queryInfos': [queryInfos[sIdx]]
            })

        if deltaChecked:
            # Add delta column after current pIdx (or original sIdx if no overlay)
            insertIdx = pIdx + 1
            table.insertColumn(insertIdx)
            addedCols += 1
            # Set header
            fullLabel = "Delta"
            table.setHorizontalHeaderItem(insertIdx, QTableWidgetItem(fullLabel))
            # Set cells
            for r in range(numRows):
                d = deltas[r]
                dStr = Logic.valuePrecision(str(d)) if np.isfinite(d) and not Config.rawData else str(d) if np.isfinite(d) else ''
                item = QTableWidgetItem(dStr)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                if dStr:
                    try:
                        val = float(dStr)
                        if val > 0:
                            item.setForeground(QColor(255, 165, 0))  # Orange
                        elif val < 0:
                            item.setForeground(QColor(0, 0, 255))  # Blue
                    except ValueError:
                        pass
                table.setItem(r, insertIdx, item)

            columnMetadata.append({
                'type': 'delta',
                'dataIds': [dataIds[pIdx], dataIds[sIdx]],
                'dbs': [databases[pIdx], databases[sIdx]],
                'queryInfos': [queryInfos[pIdx], queryInfos[sIdx]],
                'pairIndex': pairIndex
            })

    # For odd last column if any
    if numCols % 2 == 1:
        columnMetadata.append({
            'type': 'normal',
            'dataIds': [dataIds[-1]],
            'dbs': [databases[-1]],
            'queryInfos': [queryInfos[-1]]
        })

    # Set columnMetadata on mainWindow
    widget = table
    mainWindow = None
    while widget is not None:
        if isinstance(widget, uiMain):
            mainWindow = widget
            break
        widget = widget.parent()
    if mainWindow:
        mainWindow.columnMetadata = columnMetadata
        if Config.debug:
            print("[DEBUG] modifyTableForDeltaOverlay: Set columnMetadata with {} entries".format(len(columnMetadata)))
    else:
        if Config.debug:
            print("[WARN] modifyTableForDeltaOverlay: Could not find uiMain for columnMetadata")

    # Recalculate widths for updated table
    font = table.font()
    metrics = QFontMetrics(font)
    sampleRows = min(1000, numRows)
    columnWidths = []
    for c in range(table.columnCount()):
        cellValues = [table.item(r, c).text() if table.item(r, c) else "0.00" for r in range(sampleRows)]
        nonEmptyValues = [val for val in cellValues if val]
        if nonEmptyValues:
            maxCellWidth = max(metrics.horizontalAdvance(val) for val in nonEmptyValues)
        else:
            maxCellWidth = metrics.horizontalAdvance("0.00")
        headerItem = table.horizontalHeaderItem(c)
        headerText = headerItem.text() if headerItem else ""
        headerLines = headerText.split('\n')
        headerWidth = max(metrics.horizontalAdvance(line.strip()) for line in headerLines) if headerLines else 0
        finalWidth = max(maxCellWidth, headerWidth)
        if headerWidth > maxCellWidth:
            paddingIncrease = headerWidth - maxCellWidth
            finalWidth = maxCellWidth + paddingIncrease + 10
        else:
            finalWidth += 20
        columnWidths.append(finalWidth)
    for c in range(table.columnCount()):
        table.setColumnWidth(c, columnWidths[c])
        if Config.debug:
            print(f"[DEBUG] modifyTableForDeltaOverlay: Set column {c} width to {columnWidths[c]}")