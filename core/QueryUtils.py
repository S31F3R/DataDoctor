# QueryUtils.py

import numpy as np
from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics, QBrush
from PyQt6.QtWidgets import QTableWidgetItem
from core import Logic, Config
from DataDoctor import uiMain

def modifyTable(table, deltaChecked, overlayChecked, databases, queryItems, labelsDict, lookupIds, mainWindow=None):
    if Config.debug:
        Logic.logMessage("DEBUG", "modifyTable: Starting with delta={}, overlay={}".format(deltaChecked, overlayChecked))
    numRows = table.rowCount()

    # Original dataIds from lookupIds
    dataIds = lookupIds

    # Query infos
    queryInfos = [f"{item[0]}|{item[1]}|{item[2]}" for item in queryItems]

    # Iterate col by col, processing pairs dynamically
    col = 0
    pairIndex = 0
    columnMetadata = []

    while col < table.columnCount() - 1:
        pIdx = col
        sIdx = col + 1

        # Dynamically extract vals for current pair
        primaryVals = np.full(numRows, np.nan)
        secondaryVals = np.full(numRows, np.nan)

        for r in range(numRows):
            pItem = table.item(r, pIdx)
            sItem = table.item(r, sIdx)

            if pItem and pItem.text():
                try:
                    primaryVals[r] = float(pItem.text())
                except ValueError:
                    pass
            if sItem and sItem.text():
                try:
                    secondaryVals[r] = float(sItem.text())
                except ValueError:
                    pass
        deltas = computeDeltas(primaryVals, secondaryVals)

        # Perform modifications
        if deltaChecked:
            insertIdx = sIdx + 1
            addDeltaColumn(table, insertIdx, deltas)
        if overlayChecked:
            processOverlay(table, pIdx, sIdx, deltas, numRows, dataIds, databases, queryInfos, pairIndex)

        # Append metadata in final order with lists
        if overlayChecked:
            primaryDb = databases[pairIndex*2]
            primaryId = dataIds[pairIndex*2]
            lookupId = [labelsDict.get(primaryId, primaryId) if primaryDb == 'AQUARIUS' else primaryId,
                        labelsDict.get(dataIds[pairIndex*2+1], dataIds[pairIndex*2+1]) if databases[pairIndex*2+1] == 'AQUARIUS' else dataIds[pairIndex*2+1]]
            columnMetadata.append({
                'type': 'overlay',
                'dataIds': [dataIds[pairIndex*2], dataIds[pairIndex*2+1]],
                'dbs': [databases[pairIndex*2], databases[pairIndex*2+1]],
                'queryInfos': [queryInfos[pairIndex*2], queryInfos[pairIndex*2+1]],
                'pairIndex': pairIndex,
                'lookupId': lookupId # List for multi
            })
        else:
            primaryDb = databases[pairIndex*2]
            primaryId = dataIds[pairIndex*2]
            lookupIdPrimary = labelsDict.get(primaryId, primaryId) if primaryDb == 'AQUARIUS' else primaryId
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pairIndex*2]],
                'dbs': [databases[pairIndex*2]],
                'queryInfos': [queryInfos[pairIndex*2]],
                'lookupId': lookupIdPrimary
            })

            secondaryDb = databases[pairIndex*2+1]
            secondaryId = dataIds[pairIndex*2+1]
            lookupIdSecondary = labelsDict.get(secondaryId, secondaryId) if secondaryDb == 'AQUARIUS' else secondaryId
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pairIndex*2+1]],
                'dbs': [databases[pairIndex*2+1]],
                'queryInfos': [queryInfos[pairIndex*2+1]],
                'lookupId': lookupIdSecondary
            })
        if deltaChecked:
            # Initialize lookupId for delta if not already set (e.g., in delta-only mode)
            if not overlayChecked:
                lookupId = [lookupIdPrimary, lookupIdSecondary]
            columnMetadata.append({
                'type': 'delta',
                'dataIds': [dataIds[pairIndex*2], dataIds[pairIndex*2+1]],
                'dbs': [databases[pairIndex*2], databases[pairIndex*2+1]],
                'queryInfos': [queryInfos[pairIndex*2], queryInfos[pairIndex*2+1]],
                'pairIndex': pairIndex,
                'lookupId': lookupId # Reuse list from overlay or similar
            })

        # Advance col
        col += 2 + (1 if deltaChecked else 0) - (1 if overlayChecked else 0)
        pairIndex += 1

    # For odd last column if any
    if col < table.columnCount():
        lastDb = databases[-1]
        lastId = dataIds[-1]
        lookupIdLast = labelsDict.get(lastId, lastId) if lastDb == 'AQUARIUS' else lastId
        columnMetadata.append({
            'type': 'normal',
            'dataIds': [dataIds[-1]],
            'dbs': [databases[-1]],
            'queryInfos': [queryInfos[-1]],
            'lookupId': lookupIdLast
        })

    # Set columnMetadata on mainWindow
    if mainWindow:
        mainWindow.columnMetadata = columnMetadata
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Set columnMetadata via passed mainWindow with {len(columnMetadata)} entries: {repr(columnMetadata)}")
    else:
        widget = table
        mainWindowFound = None

        while widget is not None:
            if isinstance(widget, uiMain):
                mainWindowFound = widget
                break
            widget = widget.parent()
        if mainWindowFound:
            mainWindowFound.columnMetadata = columnMetadata

            if Config.debug:
                Logic.logMessage("DEBUG", f"Set columnMetadata with {len(columnMetadata)} entries: {repr(columnMetadata)}")
        else:
            if Config.debug:
                Logic.logMessage("WARN", "modifyTable: Could not find uiMain for columnMetadata")

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
            Logic.logMessage("DEBUG", f"modifyTable: Set column {c} width to {columnWidths[c]}")

def processDelta(primaryVals, secondaryVals):
    deltas = np.subtract(primaryVals, secondaryVals)
    deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan
    return deltas

def processOverlay(table, pIdx, sIdx, deltas, numRows, dataIds, databases, queryInfos, pairIndex):
    """Merge secondary into primary column. Colors are applied later (after QAQC) via applyOverlayColorOverrides."""
    for r in range(numRows):
        item = table.item(r, pIdx)
        if item:
            try:
                primaryVal = float(item.text()) if item.text() else np.nan
            except ValueError:
                primaryVal = np.nan
            sItem = table.item(r, sIdx)
            try:
                secondaryVal = float(sItem.text()) if sItem and sItem.text() else np.nan
            except ValueError:
                secondaryVal = np.nan
            hasP = np.isfinite(primaryVal)
            hasS = np.isfinite(secondaryVal)
            d = deltas[r]

            # Set data for details (do not paint yet — QAQC runs first on final display values)
            # valuePrecision handles rawData (fixed-point, no scientific notation)
            pStr = Logic.valuePrecision(primaryVal) if hasP else ''
            sStr = Logic.valuePrecision(secondaryVal) if hasS else ''
            dStr = Logic.valuePrecision(d) if np.isfinite(d) else ''
            item.setData(Qt.ItemDataRole.UserRole, {
                'primaryVal': pStr,
                'secondaryVal': sStr,
                'delta': dStr,
                'dataId1': dataIds[pairIndex*2],
                'dataId2': dataIds[pairIndex*2+1],
                'db1': databases[pairIndex*2],
                'db2': databases[pairIndex*2+1],
                'overlay': True
            })

            # Update text to display (use p if available, else s)
            newText = pStr if hasP else sStr if hasS else ''
            item.setText(newText)

    # Remove sIdx column
    table.removeColumn(sIdx)

def applyOverlayColorOverrides(table):
    """
    Apply overlay coloring after QAQC.
    Priority: QAQC first (already on cells), then overlay overrides for mismatch / missing pairs.
    Matching values (delta == 0) keep QAQC colors.
    """
    for c in range(table.columnCount()):
        for r in range(table.rowCount()):
            item = table.item(r, c)
            if not item:
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, dict) or not data.get('overlay'):
                continue

            pStr = str(data.get('primaryVal', '') or '').strip()
            sStr = str(data.get('secondaryVal', '') or '').strip()
            dStr = str(data.get('delta', '') or '').strip()

            hasP = pStr != ''
            hasS = sStr != ''
            try:
                d = float(dStr) if dStr else np.nan
            except ValueError:
                d = np.nan

            if hasP and hasS:
                if np.isfinite(d) and d != 0:
                    item.setForeground(QColor(255, 0, 0))  # Red for mismatch
                    # Leave background so QAQC band can remain visible under red text if set
                # delta == 0: keep QAQC colors
            elif not hasP and hasS:
                item.setBackground(QColor(221, 160, 221))  # Light purple — secondary only
                item.setForeground(QColor(0, 0, 0))
            elif hasP and not hasS:
                item.setBackground(QColor(255, 182, 193))  # Light pink — primary only
                item.setForeground(QColor(0, 0, 0))

def applyUsbrRbaseFallbackColors(table, mainWindow):
    """
    HDB/USBR: when interval is empty but r_base has a value, the cell shows the
    r_base number. Paint it like a missing interval (blue box) with black text
    so it is not treated as a normal QAQC'd reading.
    """
    if table is None or mainWindow is None:
        return
    seriesResponses = getattr(mainWindow, 'seriesResponses', None) or {}
    columnMetadata = getattr(mainWindow, 'columnMetadata', None) or []
    if not seriesResponses or not columnMetadata:
        return

    blue = QColor(100, 195, 247)
    black = QColor(0, 0, 0)

    for col, meta in enumerate(columnMetadata):
        if col >= table.columnCount():
            break
        dbs = meta.get('dbs') or []
        if isinstance(dbs, list):
            db = dbs[0] if dbs else ''
        else:
            db = dbs
        if not db or not str(db).startswith('USBR'):
            continue

        # Resolve seriesResponses key (DataID / lookupId)
        lid = meta.get('lookupId')
        if isinstance(lid, list):
            lid = lid[0] if lid else None
        dataIds = meta.get('dataIds') or []
        if isinstance(dataIds, list):
            dataId = dataIds[0] if dataIds else None
        else:
            dataId = dataIds

        response = None
        for key in (lid, dataId):
            if key is not None and str(key) in seriesResponses:
                response = seriesResponses[str(key)]
                break
            if key is not None and key in seriesResponses:
                response = seriesResponses[key]
                break
        if not isinstance(response, list) or not response:
            continue

        # Map End/Start DateTime (query format) -> meta row
        byEnd = {}
        byStart = {}
        for rowMeta in response:
            if not isinstance(rowMeta, dict):
                continue
            endK = rowMeta.get('End Date/Time') or ''
            startK = rowMeta.get('Start Date/Time') or ''
            if endK:
                byEnd[str(endK)] = rowMeta
            if startK:
                byStart[str(startK)] = rowMeta

        for r in range(table.rowCount()):
            item = table.item(r, col)
            if not item or not item.text().strip():
                continue
            tsItem = table.verticalHeaderItem(r)
            if not tsItem:
                continue
            tsStr = tsItem.text()
            try:
                tsDate = datetime.strptime(tsStr, '%m/%d/%y %H:%M:00')
                matchKey = tsDate.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue

            rowMeta = byEnd.get(matchKey) or byStart.get(matchKey)
            if not rowMeta:
                continue
            intervalVal = (rowMeta.get('Interval Value') or '').strip()
            baseVal = (rowMeta.get('Base Value') or '').strip()
            if intervalVal or not baseVal:
                continue

            # r_base fill for missing interval: blue missing box + black text
            item.setBackground(blue)
            item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(black))
            # Keep a light marker for other code paths if needed
            user = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(user, dict):
                user = dict(user)
                user['rbaseFallback'] = True
                item.setData(Qt.ItemDataRole.UserRole, user)

    if Config.debug:
        Logic.logMessage("DEBUG", "applyUsbrRbaseFallbackColors: finished pass")


def computeDeltas(primaryVals, secondaryVals):
    deltas = np.subtract(primaryVals, secondaryVals)
    deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan
    return deltas

def addDeltaColumn(table, insertIdx, deltas):
    numRows = table.rowCount()
    table.insertColumn(insertIdx)
    fullLabel = "Delta"
    table.setHorizontalHeaderItem(insertIdx, QTableWidgetItem(fullLabel))

    for r in range(numRows):
        d = deltas[r]
        # valuePrecision handles rawData (fixed-point, no scientific notation)
        dStr = Logic.valuePrecision(d) if np.isfinite(d) else ''
        item = QTableWidgetItem(dStr)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(Config.systemTextColor) # System default

        if dStr:
            try:
                val = float(dStr)

                if val > 0:
                    item.setForeground(QColor(255, 165, 0)) # Orange
                elif val < 0:
                    item.setForeground(QColor(68, 165, 255)) # Blue
            except ValueError:
                pass
        table.setItem(r, insertIdx, item)