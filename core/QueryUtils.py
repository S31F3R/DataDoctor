# QueryUtils.py

import numpy as np
from datetime import datetime
from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QColor, QFontMetrics, QBrush
from PyQt6.QtWidgets import QTableWidgetItem
from core import Logic, Config, Utils
from DataDoctor import uiMain


def modifyTable(
    table,
    deltaChecked,
    overlayChecked,
    databases,
    queryItems,
    labelsDict,
    lookupIds,
    mainWindow=None,
    progressDialog=None,
):
    """
    Apply delta and/or overlay to the results table.

    Large tables: never call removeColumn in a loop (each call shifts every cell
    in columns to the right — multi-minute freeze on 10k+ rows × many pairs).
    Instead extract values once, compute final columns offline, rewrite table once.
    """
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            "modifyTable: Starting with delta={}, overlay={}".format(deltaChecked, overlayChecked),
        )
    numRows = table.rowCount()
    numCols = table.columnCount()
    if numRows == 0 or numCols == 0:
        return

    dataIds = lookupIds
    labelsDict = labelsDict or {}
    queryInfos = [f"{item[0]}|{item[1]}|{item[2]}" for item in queryItems]

    # --- Extract all cell text once (one grid walk) ---
    def _yield(msg, pct=None):
        if progressDialog is None:
            return
        progressDialog.setLabelText(msg)
        if pct is not None:
            progressDialog.setValue(pct)
        progressDialog.repaint()
        QCoreApplication.processEvents()

    _yield("Overlay/delta: reading table...", 97)

    grid = []
    headers = []
    for c in range(numCols):
        hItem = table.horizontalHeaderItem(c)
        headers.append(hItem.text() if hItem else f"Col {c}")
        colVals = []
        for r in range(numRows):
            item = table.item(r, c)
            colVals.append(item.text().strip() if item and item.text() else '')
            if r > 0 and r % 2000 == 0:
                _yield(f"Overlay/delta: reading... col {c + 1}/{numCols}", 97)
        grid.append(colVals)

    # Pair columns (0,1), (2,3), ... leftover odd column kept as-is
    pairCount = numCols // 2
    hasOdd = (numCols % 2) == 1

    finalCols = []       # list of list[str] cell texts
    finalHeaders = []    # list[str]
    finalRoles = []      # list of list[dict|None] UserRole per cell
    columnMetadata = []

    table.setUpdatesEnabled(False)
    table.blockSignals(True)
    table.setSortingEnabled(False)

    for pairIndex in range(pairCount):
        pIdx = pairIndex * 2
        sIdx = pIdx + 1
        primaryVals = np.full(numRows, np.nan)
        secondaryVals = np.full(numRows, np.nan)

        for r in range(numRows):
            try:
                if grid[pIdx][r]:
                    primaryVals[r] = float(grid[pIdx][r])
            except ValueError:
                pass
            try:
                if grid[sIdx][r]:
                    secondaryVals[r] = float(grid[sIdx][r])
            except ValueError:
                pass

        deltas = computeDeltas(primaryVals, secondaryVals)

        if overlayChecked:
            # Merge secondary into primary column offline
            mergedText = [''] * numRows
            roles = [None] * numRows
            for r in range(numRows):
                hasP = np.isfinite(primaryVals[r])
                hasS = np.isfinite(secondaryVals[r])
                d = deltas[r]
                pStr = Logic.valuePrecision(primaryVals[r]) if hasP else ''
                sStr = Logic.valuePrecision(secondaryVals[r]) if hasS else ''
                dStr = Logic.valuePrecision(d) if np.isfinite(d) else ''
                roles[r] = {
                    'primaryVal': pStr,
                    'secondaryVal': sStr,
                    'delta': dStr,
                    'dataId1': dataIds[pairIndex * 2],
                    'dataId2': dataIds[pairIndex * 2 + 1],
                    'db1': databases[pairIndex * 2],
                    'db2': databases[pairIndex * 2 + 1],
                    'overlay': True,
                }
                mergedText[r] = pStr if hasP else (sStr if hasS else '')
            finalCols.append(mergedText)
            finalRoles.append(roles)
            # Header: keep primary header (two-line style)
            finalHeaders.append(headers[pIdx] if pIdx < len(headers) else f"Overlay {pairIndex}")

            primaryDb = databases[pairIndex * 2]
            primaryId = dataIds[pairIndex * 2]
            lookupId = [
                labelsDict.get(primaryId, primaryId) if primaryDb == 'AQUARIUS' else primaryId,
                labelsDict.get(dataIds[pairIndex * 2 + 1], dataIds[pairIndex * 2 + 1])
                if databases[pairIndex * 2 + 1] == 'AQUARIUS'
                else dataIds[pairIndex * 2 + 1],
            ]
            columnMetadata.append({
                'type': 'overlay',
                'dataIds': [dataIds[pairIndex * 2], dataIds[pairIndex * 2 + 1]],
                'dbs': [databases[pairIndex * 2], databases[pairIndex * 2 + 1]],
                'queryInfos': [queryInfos[pairIndex * 2], queryInfos[pairIndex * 2 + 1]],
                'pairIndex': pairIndex,
                'lookupId': lookupId,
            })
        else:
            # Keep both columns as normal
            finalCols.append(list(grid[pIdx]))
            finalRoles.append([None] * numRows)
            finalHeaders.append(headers[pIdx])
            finalCols.append(list(grid[sIdx]))
            finalRoles.append([None] * numRows)
            finalHeaders.append(headers[sIdx])

            primaryDb = databases[pairIndex * 2]
            primaryId = dataIds[pairIndex * 2]
            lookupIdPrimary = labelsDict.get(primaryId, primaryId) if primaryDb == 'AQUARIUS' else primaryId
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pairIndex * 2]],
                'dbs': [databases[pairIndex * 2]],
                'queryInfos': [queryInfos[pairIndex * 2]],
                'lookupId': lookupIdPrimary,
            })
            secondaryDb = databases[pairIndex * 2 + 1]
            secondaryId = dataIds[pairIndex * 2 + 1]
            lookupIdSecondary = (
                labelsDict.get(secondaryId, secondaryId) if secondaryDb == 'AQUARIUS' else secondaryId
            )
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pairIndex * 2 + 1]],
                'dbs': [databases[pairIndex * 2 + 1]],
                'queryInfos': [queryInfos[pairIndex * 2 + 1]],
                'lookupId': lookupIdSecondary,
            })

        if deltaChecked:
            dCol = [''] * numRows
            for r in range(numRows):
                d = deltas[r]
                dCol[r] = Logic.valuePrecision(d) if np.isfinite(d) else ''
            finalCols.append(dCol)
            finalRoles.append([None] * numRows)
            finalHeaders.append("Delta")
            if not overlayChecked:
                lookupId = [lookupIdPrimary, lookupIdSecondary]
            columnMetadata.append({
                'type': 'delta',
                'dataIds': [dataIds[pairIndex * 2], dataIds[pairIndex * 2 + 1]],
                'dbs': [databases[pairIndex * 2], databases[pairIndex * 2 + 1]],
                'queryInfos': [queryInfos[pairIndex * 2], queryInfos[pairIndex * 2 + 1]],
                'pairIndex': pairIndex,
                'lookupId': lookupId,
            })

        if pairIndex % 2 == 0 or pairIndex == pairCount - 1:
            _yield(f"Overlay/delta: computing pairs... ({pairIndex + 1}/{pairCount})", 97)

    if hasOdd:
        last = numCols - 1
        finalCols.append(list(grid[last]))
        finalRoles.append([None] * numRows)
        finalHeaders.append(headers[last])
        lastDb = databases[-1]
        lastId = dataIds[-1]
        lookupIdLast = labelsDict.get(lastId, lastId) if lastDb == 'AQUARIUS' else lastId
        columnMetadata.append({
            'type': 'normal',
            'dataIds': [dataIds[-1]],
            'dbs': [databases[-1]],
            'queryInfos': [queryInfos[-1]],
            'lookupId': lookupIdLast,
        })

    # --- Single rewrite of the table (no removeColumn loop) ---
    outCols = len(finalCols)
    _yield(f"Overlay/delta: writing {outCols} columns × {numRows} rows...", 97)

    # Preserve vertical header timestamps
    timestamps = []
    for r in range(numRows):
        tsItem = table.verticalHeaderItem(r)
        timestamps.append(tsItem.text() if tsItem else '')

    table.clear()
    table.setRowCount(numRows)
    table.setColumnCount(outCols)
    # Retro trailing blank line under headers (same as buildTable)
    table.setHorizontalHeaderLabels(
        [Utils.formatTableHeaderLabel(h) for h in finalHeaders]
    )
    if timestamps and any(timestamps):
        table.setVerticalHeaderLabels(timestamps)

    align = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
    yieldEvery = 200 if numRows * outCols > 200000 else 500

    for c in range(outCols):
        colData = finalCols[c]
        roles = finalRoles[c]
        isDelta = (columnMetadata[c].get('type') == 'delta') if c < len(columnMetadata) else False
        for r in range(numRows):
            text = colData[r] if r < len(colData) else ''
            item = QTableWidgetItem(text)
            item.setTextAlignment(align)
            role = roles[r] if r < len(roles) else None
            if role is not None:
                item.setData(Qt.ItemDataRole.UserRole, role)
            if isDelta and text:
                try:
                    val = float(text)
                    if val > 0:
                        item.setForeground(QColor(255, 165, 0))
                    elif val < 0:
                        item.setForeground(QColor(68, 165, 255))
                    else:
                        item.setForeground(Config.systemTextColor)
                except ValueError:
                    item.setForeground(Config.systemTextColor)
            table.setItem(r, c, item)

        if c % max(1, outCols // 10) == 0 or c == outCols - 1:
            _yield(f"Overlay/delta: writing column {c + 1}/{outCols}...", 97)

        # Also yield by row volume on very tall tables
        if numRows > 5000 and c == 0:
            pass  # column loop already yields

    # Lightweight width: header + tiny sample (never scan all rows)
    # Match buildTable fudge; ignore blank spacer lines in header text
    font = table.font()
    metrics = QFontMetrics(font)
    sampleN = min(50, numRows)
    for c in range(outCols):
        headerItem = table.horizontalHeaderItem(c)
        headerText = headerItem.text() if headerItem else ""
        # Same original buildTable width math (blank spacer lines ignored)
        headerLines = [line.strip() for line in headerText.split('\n') if line.strip()]
        headerWidth = max(
            (metrics.horizontalAdvance(line) for line in headerLines),
            default=40,
        )
        maxCell = metrics.horizontalAdvance("0.00")
        for r in range(sampleN):
            it = table.item(r, c)
            if it and it.text():
                maxCell = max(maxCell, metrics.horizontalAdvance(it.text()))
        finalWidth = max(maxCell, headerWidth)
        if headerWidth > maxCell:
            finalWidth = maxCell + (headerWidth - maxCell) + 10
        else:
            finalWidth += 20
        table.setColumnWidth(c, finalWidth)

    # Re-apply row/header heights after clear/rewrite
    Utils.applyTableRowMetrics(table, font=font)

    table.blockSignals(False)
    table.setUpdatesEnabled(True)

    # columnMetadata on main window
    if mainWindow:
        mainWindow.columnMetadata = columnMetadata
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Set columnMetadata via passed mainWindow with {len(columnMetadata)} entries",
            )
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
                Logic.logMessage(
                    "DEBUG",
                    f"Set columnMetadata with {len(columnMetadata)} entries",
                )
        elif Config.debug:
            Logic.logMessage("WARN", "modifyTable: Could not find uiMain for columnMetadata")

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"modifyTable: done offline rewrite → {outCols} cols × {numRows} rows",
        )


def processDelta(primaryVals, secondaryVals):
    deltas = np.subtract(primaryVals, secondaryVals)
    deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan
    return deltas


def processOverlay(table, pIdx, sIdx, deltas, numRows, dataIds, databases, queryInfos, pairIndex):
    """Legacy path kept for callers; modifyTable no longer uses removeColumn loops."""
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
            pStr = Logic.valuePrecision(primaryVal) if hasP else ''
            sStr = Logic.valuePrecision(secondaryVal) if hasS else ''
            dStr = Logic.valuePrecision(d) if np.isfinite(d) else ''
            item.setData(Qt.ItemDataRole.UserRole, {
                'primaryVal': pStr,
                'secondaryVal': sStr,
                'delta': dStr,
                'dataId1': dataIds[pairIndex * 2],
                'dataId2': dataIds[pairIndex * 2 + 1],
                'db1': databases[pairIndex * 2],
                'db2': databases[pairIndex * 2 + 1],
                'overlay': True,
            })
            item.setText(pStr if hasP else (sStr if hasS else ''))
    table.removeColumn(sIdx)


def applyOverlayColorOverrides(table, progressDialog=None):
    """
    Apply overlay coloring after QAQC.
    Priority: QAQC first (already on cells), then overlay overrides for mismatch / missing pairs.
    Matching values (delta == 0) keep QAQC colors.
    """
    numRows = table.rowCount()
    numCols = table.columnCount()
    table.setUpdatesEnabled(False)
    table.blockSignals(True)
    for c in range(numCols):
        for r in range(numRows):
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
            elif not hasP and hasS:
                item.setBackground(QColor(221, 160, 221))  # Light purple — secondary only
                item.setForeground(QColor(0, 0, 0))
            elif hasP and not hasS:
                item.setBackground(QColor(255, 182, 193))  # Light pink — primary only
                item.setForeground(QColor(0, 0, 0))

        if progressDialog is not None and (c % 5 == 0 or c == numCols - 1):
            progressDialog.setLabelText(f"Overlay colors... ({c + 1}/{numCols})")
            progressDialog.repaint()
            QCoreApplication.processEvents()

    table.blockSignals(False)
    table.setUpdatesEnabled(True)


def applyUsbrRbaseFallbackColors(table, mainWindow, progressDialog=None):
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
    numRows = table.rowCount()

    table.setUpdatesEnabled(False)
    table.blockSignals(True)

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

        for r in range(numRows):
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

            item.setBackground(blue)
            item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(black))
            user = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(user, dict):
                user = dict(user)
                user['rbaseFallback'] = True
                item.setData(Qt.ItemDataRole.UserRole, user)

        if progressDialog is not None and col % 5 == 0:
            progressDialog.setLabelText(f"HDB r_base colors... ({col + 1}/{len(columnMetadata)})")
            progressDialog.repaint()
            QCoreApplication.processEvents()

    table.blockSignals(False)
    table.setUpdatesEnabled(True)

    if Config.debug:
        Logic.logMessage("DEBUG", "applyUsbrRbaseFallbackColors: finished pass")


def computeDeltas(primaryVals, secondaryVals):
    deltas = np.subtract(primaryVals, secondaryVals)
    deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan
    return deltas


def addDeltaColumn(table, insertIdx, deltas):
    """Legacy helper; modifyTable writes delta columns offline for large tables."""
    numRows = table.rowCount()
    table.insertColumn(insertIdx)
    fullLabel = "Delta"
    table.setHorizontalHeaderItem(insertIdx, QTableWidgetItem(fullLabel))

    for r in range(numRows):
        d = deltas[r]
        dStr = Logic.valuePrecision(d) if np.isfinite(d) else ''
        item = QTableWidgetItem(dStr)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(Config.systemTextColor)

        if dStr:
            try:
                val = float(dStr)
                if val > 0:
                    item.setForeground(QColor(255, 165, 0))
                elif val < 0:
                    item.setForeground(QColor(68, 165, 255))
            except ValueError:
                pass
        table.setItem(r, insertIdx, item)
