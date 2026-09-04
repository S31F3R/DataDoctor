# QueryUtils.py

import numpy as np
from decimal import Decimal, InvalidOperation
from datetime import datetime
from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QTableWidgetItem
from core import Logic, Config, Utils, TableColors


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

    # Full query DataIDs (for seriesResponses / columnMetadata) — NOT dictionary keys.
    # lookupIds are dict keys (USGS → bare tsid, USBR → SDID); use those only for rounding.
    dataIds = [item[0] for item in queryItems] if queryItems else list(lookupIds or [])
    dictKeys = list(lookupIds) if lookupIds is not None else list(dataIds)
    labelsDict = labelsDict or {}
    queryInfos = [f"{item[0]}|{item[1]}|{item[2]}" for item in queryItems]
    databases = list(databases) if databases else []

    # Per-series rounding rules (same as buildTable) so re-format does not drop DEC(3) etc.
    dictTable = None
    dictIndex = None
    if mainWindow is not None:
        winDd = getattr(mainWindow, 'winDataDictionary', None)
        if winDd is not None:
            dictTable = getattr(winDd, 'mainTable', None)
        dictIndex = getattr(table, 'dataDictIndex', None)

    def ruleForId(idx_or_id):
        """
        Resolve RoundingSpec for overlay/delta columns.

        Full query DataID + database so USGS site-tsid[-param] hits bare
        time_series_id and applies precisionOverride (DEC(2) over Discharge DEC(3)).
        """
        if dictTable is None:
            return Logic.DEFAULT_ROUNDING_SPEC
        if isinstance(idx_or_id, int):
            i = idx_or_id
            qid = dataIds[i] if i < len(dataIds) else None
            db = databases[i] if i < len(databases) else None
        else:
            qid = idx_or_id
            db = None
            if qid in dataIds:
                i = dataIds.index(qid)
                db = databases[i] if i < len(databases) else None
        if not qid:
            return Logic.DEFAULT_ROUNDING_SPEC
        return Logic.roundingSpecForDataId(
            dictTable, qid, dictIndex=dictIndex, database=db
        )

    # --- Extract all cell text once (one grid walk) ---
    def yieldProgress(msg, pct=None):
        if progressDialog is None:
            return
        progressDialog.setLabelText(msg)
        if pct is not None:
            progressDialog.setValue(pct)
        progressDialog.repaint()
        QCoreApplication.processEvents()

    yieldProgress("Overlay/delta: reading table...", 97)

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
                yieldProgress(f"Overlay/delta: reading... col {c + 1}/{numCols}", 97)
        grid.append(colVals)

    # Pair columns (0,1), (2,3), ... leftover odd column kept as-is
    pairCount = numCols // 2
    hasOdd = (numCols % 2) == 1

    finalCols = []       # list of list[str] cell texts
    finalHeaders = []    # list[str]
    finalRoles = []      # list of list[dict|None] UserRole per cell
    columnMetadata = []
    finalRules = []      # RoundingSpec per final display column

    table.setUpdatesEnabled(False)
    table.blockSignals(True)
    table.setSortingEnabled(False)

    for pairIndex in range(pairCount):
        pIdx = pairIndex * 2
        sIdx = pIdx + 1
        primaryVals = np.full(numRows, np.nan)
        secondaryVals = np.full(numRows, np.nan)
        # Exact string→Decimal deltas (avoids float binary noise / scientific notation)
        deltaDecimals = [None] * numRows
        pRule = ruleForId(pIdx)
        sRule = ruleForId(sIdx)
        # Deltas: use primary series rule (same units as primary)
        dRule = pRule

        # Native (each series' own buildTable rounding) plus overlay display
        # strings (both with the primary spec). Matching overlay text → delta 0.
        pNativeCol = [''] * numRows
        sNativeCol = [''] * numRows
        pDispCol = [''] * numRows
        sDispCol = [''] * numRows
        for r in range(numRows):
            pText = grid[pIdx][r] if pIdx < len(grid) else ''
            sText = grid[sIdx][r] if sIdx < len(grid) else ''
            pNativeCol[r] = pText
            sNativeCol[r] = sText
            pDec = parseDecimalText(pText)
            sDec = parseDecimalText(sText)
            if pDec is not None:
                primaryVals[r] = float(pDec)
            if sDec is not None:
                secondaryVals[r] = float(sDec)
            if overlayChecked:
                pDisp, sDisp, dStr = overlayPairDisplays(pText, sText, pRule)
                pDispCol[r] = pDisp if pDec is not None else ''
                sDispCol[r] = sDisp if sDec is not None else ''
                if pDec is not None and sDec is not None:
                    dDec = parseDecimalText(dStr)
                    deltaDecimals[r] = dDec if dDec is not None else Decimal(0)
            else:
                pDispCol[r] = pText
                sDispCol[r] = sText
                if pDec is not None and sDec is not None:
                    deltaDecimals[r] = pDec - sDec

        if overlayChecked:
            # Merge secondary into primary column offline
            mergedText = [''] * numRows
            roles = [None] * numRows
            for r in range(numRows):
                hasP = np.isfinite(primaryVals[r])
                hasS = np.isfinite(secondaryVals[r])
                pStr = pDispCol[r] if hasP else ''
                sStr = sDispCol[r] if hasS else ''
                dStr = formatDeltaValue(deltaDecimals[r], dRule)
                roles[r] = {
                    'primaryVal': pStr,
                    'secondaryVal': sStr,
                    'primaryNative': pNativeCol[r],
                    'secondaryNative': sNativeCol[r],
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
            finalRules.append(pRule)
            # Header: keep primary header (two-line style)
            finalHeaders.append(headers[pIdx] if pIdx < len(headers) else f"Overlay {pairIndex}")

            def _firstHeaderLine(h):
                """First non-empty line of a multi-line header (graph legends)."""
                if not h:
                    return ''
                for line in str(h).split('\n'):
                    line = line.strip()
                    if line:
                        return line
                return str(h).strip()

            pHeaderFull = headers[pIdx] if pIdx < len(headers) else ''
            sHeaderFull = headers[sIdx] if sIdx < len(headers) else ''
            pHeaderFirst = _firstHeaderLine(pHeaderFull)
            sHeaderFirst = _firstHeaderLine(sHeaderFull)

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
                'headerFirstLines': [pHeaderFirst, sHeaderFirst],
                'headerFullLines': [pHeaderFull, sHeaderFull],
                'roundRules': [pRule, sRule],
            })
        else:
            # Keep both columns as normal (already formatted in buildTable; keep text)
            finalCols.append(list(grid[pIdx]))
            finalRoles.append([None] * numRows)
            finalHeaders.append(headers[pIdx])
            finalRules.append(pRule)
            finalCols.append(list(grid[sIdx]))
            finalRoles.append([None] * numRows)
            finalHeaders.append(headers[sIdx])
            finalRules.append(sRule)

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
                dCol[r] = formatDeltaValue(deltaDecimals[r], dRule)
            finalCols.append(dCol)
            finalRoles.append([None] * numRows)
            finalHeaders.append("Delta")
            finalRules.append(dRule)
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
            yieldProgress(f"Overlay/delta: computing pairs... ({pairIndex + 1}/{pairCount})", 97)

    if hasOdd:
        last = numCols - 1
        finalCols.append(list(grid[last]))
        finalRoles.append([None] * numRows)
        finalHeaders.append(headers[last])
        finalRules.append(ruleForId(last))
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
    table.columnRoundingRules = list(finalRules)
    yieldProgress(f"Overlay/delta: writing {outCols} columns × {numRows} rows...", 97)

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
        Utils.sizeVerticalHeader(table)

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
                        TableColors.applyToItem(item, "deltaPositive")
                    elif val < 0:
                        TableColors.applyToItem(item, "deltaNegative")
                    else:
                        item.setForeground(Config.systemTextColor)
                except ValueError:
                    item.setForeground(Config.systemTextColor)
            table.setItem(r, c, item)

        if c % max(1, outCols // 10) == 0 or c == outCols - 1:
            yieldProgress(f"Overlay/delta: writing column {c + 1}/{outCols}...", 97)

        # Also yield by row volume on very tall tables
        if numRows > 5000 and c == 0:
            pass  # column loop already yields

    # Column width deferred to executeQuery (Utils.autoSizeTableColumns) after
    # final headers + valuePrecision + any further color passes.

    # Re-apply row/header heights after clear/rewrite
    Utils.applyTableRowMetrics(table, font=table.font())

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
            # uiMain lives in DataDoctor.py / app.pyw (__main__), not a
            # DataDoctor module — Windows packages have no DataDoctor.py.
            if type(widget).__name__ == "uiMain":
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
    return computeDeltas(primaryVals, secondaryVals)


def processOverlay(table, pIdx, sIdx, deltas, numRows, dataIds, databases, queryInfos, pairIndex):
    """Legacy path kept for callers; modifyTable no longer uses removeColumn loops."""
    for r in range(numRows):
        item = table.item(r, pIdx)
        if item:
            pText = item.text().strip() if item.text() else ''
            sItem = table.item(r, sIdx)
            sText = sItem.text().strip() if sItem and sItem.text() else ''
            pDec = parseDecimalText(pText)
            sDec = parseDecimalText(sText)
            hasP = pDec is not None
            hasS = sDec is not None
            pStr = Logic.valuePrecision(pText) if hasP else ''
            sStr = Logic.valuePrecision(sText) if hasS else ''
            dStr = (
                formatDeltaValue(pDec - sDec)
                if hasP and hasS
                else ''
            )
            # Legacy path — prefer main modifyTable rewrite which has per-series rules
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

            prevPaint = data.get("overlayPaint")
            paint = None
            if hasP and hasS:
                if np.isfinite(d) and d != 0:
                    paint = "mismatch"
            elif not hasP and hasS:
                paint = "secondary"
            elif hasP and not hasS:
                paint = "primary"
            if paint == "mismatch":
                TableColors.applyToItem(item, "overlayMismatch")
            elif paint == "secondary":
                TableColors.applyToItem(item, "overlaySecondaryOnly")
            elif paint == "primary":
                TableColors.applyToItem(item, "overlayPrimaryOnly")
            elif prevPaint:
                # Pair now matches at the current primary spec — drop overlay red
                # (QAQC on still-matching cells is left alone: prevPaint is None).
                item.setBackground(QBrush())
                item.setForeground(Config.systemTextColor)
            if paint != prevPaint:
                data = dict(data)
                if paint:
                    data["overlayPaint"] = paint
                else:
                    data.pop("overlayPaint", None)
                item.setData(Qt.ItemDataRole.UserRole, data)

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
            from core.Query import parseDisplayTimestamp, periodStart
            tsDate = parseDisplayTimestamp(tsStr)
            if tsDate is None:
                continue
            matchKey = tsDate.strftime('%Y-%m-%d %H:%M:%S')

            rowMeta = byEnd.get(matchKey) or byStart.get(matchKey)
            if not rowMeta:
                # Coarser display intervals: match any meta row in the same calendar day
                for key, meta in list(byEnd.items()) + list(byStart.items()):
                    try:
                        rowDt = datetime.strptime(key, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        continue
                    if periodStart(rowDt, 'DAY') == periodStart(tsDate, 'DAY'):
                        rowMeta = meta
                        break
            if not rowMeta:
                continue
            intervalVal = (rowMeta.get('Interval Value') or '').strip()
            baseVal = (rowMeta.get('Base Value') or '').strip()
            if intervalVal or not baseVal:
                continue

            TableColors.applyToItem(item, "qaqcMissing")
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


def parseDecimalText(text):
    """
    Parse a cell string to Decimal without float binary noise.
    Returns None for blank / non-numeric.
    """
    if text is None:
        return None
    s = str(text).strip().replace(',', '')
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def formatSeriesDisplay(text, rule=None):
    """
    Format a series value with an explicit rounding spec.

    Uses applyRoundingSpec on the original string (Decimal path) so a DEC(3)
    primary can pull an Aquarius 642.2724 down to 642.272. valuePrecision
    goes through float first and is only the fallback.
    """
    if text is None:
        return ''
    s = str(text).strip()
    if not s:
        return ''
    if Config.rawData:
        return Logic.formatRawNumber(s)
    try:
        out = Logic.applyRoundingSpec(s, rule)
        if out is not None and str(out).strip() != '':
            return str(out)
    except Exception:
        pass
    formatted = Logic.valuePrecision(s, rule=rule)
    return formatted if formatted is not None else s


def overlayPairDisplays(pNative, sNative, pRule):
    """
    Overlay display strings and delta, both rounded with the *primary* spec.

    Matching displayed values (or equal after quantize to the primary's
    decimal places) → delta 0 so a 0.0004 residual is not flagged red.
    Native series strings stay on the cell as primaryNative/secondaryNative
    for swap + individual details.
    """
    pDisp = formatSeriesDisplay(pNative, pRule)
    sDisp = formatSeriesDisplay(sNative, pRule)
    pDec = parseDecimalText(pDisp)
    sDec = parseDecimalText(sDisp)
    if pDec is None or sDec is None:
        return pDisp, sDisp, ''
    if pDisp == sDisp or pDec == sDec:
        return pDisp, sDisp, formatDeltaValue(Decimal(0), pRule)
    # Fallback when the primary rule did not land: match at primary's
    # displayed decimals (642.272 vs 642.2724 → both 642.272, delta 0).
    if '.' in str(pDisp):
        n = len(str(pDisp).split('.', 1)[1])
        try:
            quant = Decimal('1').scaleb(-n)
            pQ = pDec.quantize(quant)
            sQ = sDec.quantize(quant)
            if pQ == sQ:
                sDisp = format(sQ, f'.{n}f')
                if sDisp.startswith('-') and sQ == 0:
                    sDisp = format(Decimal(0), f'.{n}f')
                return pDisp, sDisp, formatDeltaValue(Decimal(0), pRule)
        except Exception:
            pass
    return pDisp, sDisp, formatDeltaValue(pDec - sDec, pRule)


def formatDeltaValue(deltaDec, rule=None):
    """
    Format a primary−secondary delta for the table / overlay UserRole.

    Uses Decimal math + valuePrecision so raw mode never shows scientific
    notation (e.g. 1e-12) for tiny residual differences.

    Signed zeros from rounding (-0.00, -0) are normalized to unsigned 0 /
    0.00 so tiny negative residuals never display a minus on a zero.
    """
    if deltaDec is None:
        return ''
    try:
        if not isinstance(deltaDec, Decimal):
            deltaDec = Decimal(str(deltaDec))
    except (InvalidOperation, ValueError, ArithmeticError):
        return ''
    if deltaDec.is_nan() or deltaDec.is_infinite():
        return ''
    # Exact zero (including Decimal('-0'))
    if deltaDec == 0:
        return Logic.valuePrecision(0, rule=rule)
    # Pass through valuePrecision (raw → formatRawNumber fixed-point; else DEC/SIG)
    # Use string form so _toDecimal / float path does not reintroduce binary noise.
    formatted = Logic.valuePrecision(format(deltaDec, 'f'), rule=rule)
    return normalizeSignedZeroText(formatted)


def normalizeSignedZeroText(text):
    """Turn '-0', '-0.0', '-0.00' into unsigned zero with the same decimals."""
    if text is None:
        return ''
    s = str(text).strip()
    if not s.startswith('-'):
        return s
    body = s[1:]
    if not body:
        return s
    # Only digits and at most one dot
    if body.replace('.', '', 1).isdigit() and body.replace('.', '').strip('0') == '':
        return body
    return s


def computeDeltas(primaryVals, secondaryVals):
    """
    Float/numpy delta array (legacy helpers / tests).
    Prefer Decimal path in modifyTable for display strings.
    """
    deltas = np.subtract(primaryVals, secondaryVals)
    deltas[~ (np.isfinite(primaryVals) & np.isfinite(secondaryVals))] = np.nan
    # Collapse pure float noise to 0 so residual 1e-15 does not color as mismatch
    with np.errstate(invalid='ignore'):
        noise = np.isfinite(deltas) & (np.abs(deltas) < 1e-12)
        deltas[noise] = 0.0
    return deltas


def addDeltaColumn(table, insertIdx, deltas):
    """Legacy helper; modifyTable writes delta columns offline for large tables."""
    numRows = table.rowCount()
    table.insertColumn(insertIdx)
    fullLabel = "Delta"
    table.setHorizontalHeaderItem(insertIdx, QTableWidgetItem(fullLabel))

    for r in range(numRows):
        d = deltas[r]
        if np.isfinite(d):
            dStr = formatDeltaValue(Decimal(str(d)))
        else:
            dStr = ''
        item = QTableWidgetItem(dStr)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(Config.systemTextColor)

        if dStr:
            try:
                val = float(dStr)
                if val > 0:
                    TableColors.applyToItem(item, "deltaPositive")
                elif val < 0:
                    TableColors.applyToItem(item, "deltaNegative")
            except ValueError:
                pass
        table.setItem(r, insertIdx, item)
