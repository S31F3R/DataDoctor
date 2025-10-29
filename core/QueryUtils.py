# QueryUtils.py

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import QTableWidgetItem
from core import Logic, Config
from DataDoctor import uiMain

def modifyTable(table, deltaChecked, overlayChecked, databases, queryItems, labelsDict, dataDictionaryTable, intervals, lookupIds, mainWindow=None):
    if Config.debug:
        print("[DEBUG] modifyTable: Starting with delta={}, overlay={}".format(deltaChecked, overlayChecked))
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

        # Append metadata in final order
        if overlayChecked:
            columnMetadata.append({
                'type': 'overlay',
                'dataIds': [dataIds[pairIndex*2], dataIds[pairIndex*2+1]],
                'dbs': [databases[pairIndex*2], databases[pairIndex*2+1]],
                'queryInfos': [queryInfos[pairIndex*2], queryInfos[pairIndex*2+1]],
                'pairIndex': pairIndex
            })
        else:
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pairIndex*2]],
                'dbs': [databases[pairIndex*2]],
                'queryInfos': [queryInfos[pairIndex*2]]
            })
            columnMetadata.append({
                'type': 'normal',
                'dataIds': [dataIds[pairIndex*2+1]],
                'dbs': [databases[pairIndex*2+1]],
                'queryInfos': [queryInfos[pairIndex*2+1]]
            })
        if deltaChecked:
            columnMetadata.append({
                'type': 'delta',
                'dataIds': [dataIds[pairIndex*2], dataIds[pairIndex*2+1]],
                'dbs': [databases[pairIndex*2], databases[pairIndex*2+1]],
                'queryInfos': [queryInfos[pairIndex*2], queryInfos[pairIndex*2+1]],
                'pairIndex': pairIndex
            })

        # Advance col
        col += 2 + (1 if deltaChecked else 0) - (1 if overlayChecked else 0)
        pairIndex += 1

    # For odd last column if any
    if col < table.columnCount():
        columnMetadata.append({
            'type': 'normal',
            'dataIds': [dataIds[-1]],
            'dbs': [databases[-1]],
            'queryInfos': [queryInfos[-1]]
        })

    # Set columnMetadata on mainWindow
    if mainWindow:
        mainWindow.columnMetadata = columnMetadata
        if Config.debug:
            print("[DEBUG] modifyTable: Set columnMetadata via passed mainWindow with {} entries".format(len(columnMetadata)))
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
                print("[DEBUG] modifyTable: Set columnMetadata with {} entries".format(len(columnMetadata)))
        else:
            if Config.debug:
                print("[WARN] modifyTable: Could not find uiMain for columnMetadata")

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
            print(f"[DEBUG] modifyTable: Set column {c} width to {columnWidths[c]}")

def processDelta(primaryVals, secondaryVals):
    deltas = np.subtract(primaryVals, secondaryVals)
    deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan
    return deltas

def processOverlay(table, pIdx, sIdx, deltas, numRows, dataIds, databases, queryInfos, pairIndex):
    for r in range(numRows):
        item = table.item(r, pIdx)
        if item:
            # Dynamically get vals for hasP/hasS/d
            primaryVal = float(item.text()) if item.text() else np.nan
            sItem = table.item(r, sIdx)
            secondaryVal = float(sItem.text()) if sItem and sItem.text() else np.nan
            hasP = np.isfinite(primaryVal)
            hasS = np.isfinite(secondaryVal)
            d = deltas[r]

            if hasP and hasS:
                if d != 0:
                    item.setForeground(QColor(255, 0, 0)) # Red
                    item.setBackground(QColor(0, 0, 0, 0)) # System default
                else:
                    item.setForeground(Config.systemTextColor) # System default
                    item.setBackground(QColor(0, 0, 0, 0)) # System default
            elif not hasP and hasS:
                item.setBackground(QColor(221, 160, 221)) # Light purple
                item.setForeground(QColor(0, 0, 0)) # Black
            elif hasP and not hasS:
                item.setBackground(QColor(255, 182, 193)) # Light pink
                item.setForeground(QColor(0, 0, 0)) # Black

            # Set data for details
            pStr = Logic.valuePrecision(str(primaryVal)) if hasP and not Config.rawData else str(primaryVal) if hasP else ''
            sStr = Logic.valuePrecision(str(secondaryVal)) if hasS and not Config.rawData else str(secondaryVal) if hasS else ''
            dStr = Logic.valuePrecision(str(d)) if np.isfinite(d) and not Config.rawData else str(d) if np.isfinite(d) else ''
            item.setData(Qt.ItemDataRole.UserRole, {
                'primaryVal': pStr,
                'secondaryVal': sStr,
                'delta': dStr,
                'dataId1': dataIds[pairIndex*2],
                'dataId2': dataIds[pairIndex*2+1],
                'db1': databases[pairIndex*2],
                'db2': databases[pairIndex*2+1]
            })

            # Update text to display (use p if available, else s)
            newText = pStr if hasP else sStr if hasS else ''
            item.setText(newText)

    # Remove sIdx column
    table.removeColumn(sIdx)

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
        dStr = Logic.valuePrecision(str(d)) if np.isfinite(d) and not Config.rawData else str(d) if np.isfinite(d) else ''
        item = QTableWidgetItem(dStr)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(Config.systemTextColor) # System default

        if dStr:
            try:
                val = float(dStr)

                if val > 0:
                    item.setForeground(QColor(255, 165, 0)) # Orange
                elif val < 0:
                    item.setForeground(QColor(0, 0, 255)) # Blue
            except ValueError:
                pass
        table.setItem(r, insertIdx, item)