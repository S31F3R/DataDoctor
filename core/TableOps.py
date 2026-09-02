# TableOps.py
# Data Query column insert / move / rename / overlay swap / update-from-secondary.
# Custom (user-inserted) columns survive Refresh; query-list order follows moves.

from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QInputDialog, QMenu, QMessageBox,
    QTableWidgetItem,
)

from core import Config, Logic, Upload, Utils
from core.Formula import FORMULA_KEY, shiftFormulaColumns
from core.FormulaUi import _itemFormula, applyCellInput, recalculateAll
from core.QueryUtils import formatDeltaValue, parseDecimalText
from core import TableColors, Undo


def _table(mainWindow):
    return getattr(mainWindow, "mainTable", None) if mainWindow is not None else None


def _metas(mainWindow):
    if mainWindow is None:
        return []
    metas = getattr(mainWindow, "columnMetadata", None)
    if metas is None:
        mainWindow.columnMetadata = []
        return mainWindow.columnMetadata
    return metas


def _meta(mainWindow, col):
    metas = _metas(mainWindow)
    if col < 0 or col >= len(metas):
        return {}
    return metas[col] or {}


def columnType(mainWindow, col) -> str:
    return str(_meta(mainWindow, col).get("type") or "normal")


def isCustomColumn(mainWindow, col) -> bool:
    return columnType(mainWindow, col) == "custom"


def isDeltaColumn(mainWindow, col) -> bool:
    return columnType(mainWindow, col) == "delta"


def isOverlayColumn(mainWindow, col) -> bool:
    return columnType(mainWindow, col) == "overlay"


def _centerItem(text=""):
    item = QTableWidgetItem("" if text is None else str(text))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
    return item


def _cloneItem(item):
    if item is None:
        return _centerItem("")
    new = QTableWidgetItem(item.text())
    new.setTextAlignment(item.textAlignment())
    new.setFlags(item.flags())
    new.setData(Qt.ItemDataRole.UserRole, item.data(Qt.ItemDataRole.UserRole))
    new.setBackground(item.background())
    fg = item.data(Qt.ItemDataRole.ForegroundRole)
    if fg is not None:
        new.setData(Qt.ItemDataRole.ForegroundRole, fg)
        new.setForeground(item.foreground())
    return new


def _headerText(table, col) -> str:
    h = table.horizontalHeaderItem(col) if table is not None else None
    return h.text() if h is not None else ""


def _setHeaderText(table, col, text):
    if table is None:
        return
    item = table.horizontalHeaderItem(col)
    if item is None:
        item = QTableWidgetItem(text)
        table.setHorizontalHeaderItem(col, item)
    else:
        item.setText(text)


def firstHeaderLine(text) -> str:
    for line in str(text or "").split("\n"):
        line = line.strip()
        if line:
            return line
    return str(text or "").strip()


def headerRestLines(text) -> str:
    lines = str(text or "").split("\n")
    kept = []
    skipped = False
    for line in lines:
        if not skipped and line.strip():
            skipped = True
            continue
        if skipped:
            kept.append(line)
    return "\n".join(kept)


def splitCommonName(firstLine, datatype=None) -> str:
    """Strip trailing -datatype from the first header line."""
    first = (firstLine or "").strip()
    dt = (datatype or "").strip()
    if dt and first.endswith("-" + dt):
        return first[: -(len(dt) + 1)].strip()
    return first


def _dictDatatype(mainWindow, dataId, database=None) -> str:
    winDd = getattr(mainWindow, "winDataDictionary", None)
    table = getattr(winDd, "mainTable", None) if winDd is not None else None
    if table is None or not dataId:
        return ""
    from core.Query import getColByName, getDataDictionaryItem, dictionaryLookupKey
    key = dictionaryLookupKey(dataId, database)
    row = getDataDictionaryItem(table, key)
    if row < 0:
        return ""
    col = getColByName(table, "datatype")
    if col < 0:
        return ""
    item = table.item(row, col)
    return item.text().strip() if item and item.text() else ""


def columnGroup(mainWindow, col):
    """
    Columns that must move together.
    Overlay + its delta (next column) are locked. Custom columns are free.
    """
    table = _table(mainWindow)
    if table is None or col < 0 or col >= table.columnCount():
        return [col]
    t = columnType(mainWindow, col)
    if t == "custom":
        return [col]
    if t == "delta":
        if col > 0:
            prev = columnType(mainWindow, col - 1)
            if prev in ("overlay", "normal"):
                prevMeta = _meta(mainWindow, col - 1)
                thisMeta = _meta(mainWindow, col)
                if prevMeta.get("pairIndex") == thisMeta.get("pairIndex") or prev == "overlay":
                    return [col - 1, col]
        return [col]
    if col + 1 < table.columnCount() and isDeltaColumn(mainWindow, col + 1):
        nxt = _meta(mainWindow, col + 1)
        cur = _meta(mainWindow, col)
        if nxt.get("pairIndex") == cur.get("pairIndex") or t == "overlay":
            return [col, col + 1]
    return [col]


def _shiftFormulas(table, insertAt, delta):
    if table is None or not delta:
        return
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            if delta > 0 and c == insertAt:
                continue
            item = table.item(r, c)
            formula = _itemFormula(item)
            if not formula:
                continue
            newF = shiftFormulaColumns(formula, insertAt, delta)
            if newF != formula:
                user = Upload.getUserDict(item)
                user[FORMULA_KEY] = newF
                Upload.setUserDict(item, user)


def insertBlankColumn(mainWindow, col, side="right"):
    """Insert an empty custom column left or right of col. Returns new index."""
    table = _table(mainWindow)
    if table is None or table.columnCount() <= 0:
        return -1
    insertAt = col if side == "left" else col + 1
    insertAt = max(0, min(insertAt, table.columnCount()))
    customId = uuid.uuid4().hex[:12]
    name = "Column"
    table.blockSignals(True)
    try:
        table.insertColumn(insertAt)
        _setHeaderText(table, insertAt, Utils.formatTableHeaderLabel(name))
        for r in range(table.rowCount()):
            table.setItem(r, insertAt, _centerItem(""))
        metas = _metas(mainWindow)
        while len(metas) < table.columnCount() - 1:
            metas.append({})
        metas.insert(insertAt, {
            "type": "custom",
            "customId": customId,
            "name": name,
            "dataIds": [],
            "dbs": [],
            "queryInfos": [],
            "lookupId": customId,
        })
        rules = list(getattr(table, "columnRoundingRules", None) or [])
        while len(rules) < table.columnCount() - 1:
            rules.append(Logic.DEFAULT_ROUNDING_SPEC)
        rules.insert(insertAt, Logic.DEFAULT_ROUNDING_SPEC)
        table.columnRoundingRules = rules
        _shiftFormulas(table, insertAt, 1)
    finally:
        table.blockSignals(False)
    Upload.applyEditability(table, mainWindow)
    _rememberCustomColumns(mainWindow)
    if Config.debug:
        Logic.logMessage("DEBUG", f"TableOps.insertBlankColumn at {insertAt} id={customId}")
    return insertAt


def snapshotCustomColumns(mainWindow):
    """Public alias used before a Refresh rebuild."""
    _rememberCustomColumns(mainWindow)


def _rememberCustomColumns(mainWindow):
    table = _table(mainWindow)
    if table is None:
        return
    saved = []
    for c in range(table.columnCount()):
        meta = _meta(mainWindow, c)
        if meta.get("type") != "custom":
            continue
        cells = {}
        for r in range(table.rowCount()):
            tsItem = table.verticalHeaderItem(r)
            ts = tsItem.text() if tsItem else str(r)
            item = table.item(r, c)
            cells[ts] = {
                "text": item.text() if item is not None else "",
                "formula": _itemFormula(item),
            }
        saved.append({
            "id": meta.get("customId") or uuid.uuid4().hex[:12],
            "name": meta.get("name") or firstHeaderLine(_headerText(table, c)) or "Column",
            "indexHint": c,
            "cells": cells,
        })
    mainWindow.customColumns = saved


def restoreCustomColumns(mainWindow):
    """Re-insert custom columns after a query rebuild (by saved index)."""
    saved = list(getattr(mainWindow, "customColumns", None) or [])
    if not saved:
        return
    table = _table(mainWindow)
    if table is None or table.rowCount() == 0:
        return
    saved.sort(key=lambda s: s.get("indexHint", 0))
    offset = 0
    for spec in saved:
        idx = int(spec.get("indexHint") or 0) + offset
        if idx >= table.columnCount():
            newIdx = insertBlankColumn(mainWindow, table.columnCount() - 1, side="right")
        else:
            newIdx = insertBlankColumn(mainWindow, idx, side="left")
        if newIdx < 0:
            continue
        offset += 1
        name = spec.get("name") or "Column"
        metas = _metas(mainWindow)
        if newIdx < len(metas):
            metas[newIdx]["customId"] = spec.get("id")
            metas[newIdx]["name"] = name
        _setHeaderText(table, newIdx, Utils.formatTableHeaderLabel(name))
        cells = spec.get("cells") or {}
        table.blockSignals(True)
        try:
            for r in range(table.rowCount()):
                tsItem = table.verticalHeaderItem(r)
                ts = tsItem.text() if tsItem else str(r)
                cell = cells.get(ts) or {}
                formula = cell.get("formula")
                text = cell.get("text") or ""
                if formula:
                    applyCellInput(mainWindow, r, newIdx, formula, asFill=True)
                elif text:
                    applyCellInput(mainWindow, r, newIdx, text, asFill=True)
        finally:
            table.blockSignals(False)
    recalculateAll(mainWindow)
    _rememberCustomColumns(mainWindow)


def _extractColumn(table, col):
    header = _headerText(table, col)
    items = []
    for r in range(table.rowCount()):
        items.append(table.takeItem(r, col))
    return header, items


def _insertExtracted(table, col, header, items):
    table.insertColumn(col)
    _setHeaderText(table, col, header)
    for r, item in enumerate(items):
        table.setItem(r, col, item if item is not None else _centerItem(""))


def moveColumnRange(mainWindow, srcStart, count, destStart):
    """Physically move count columns starting at srcStart so they begin at destStart."""
    table = _table(mainWindow)
    if table is None or count <= 0:
        return False
    n = table.columnCount()
    if srcStart < 0 or srcStart + count > n:
        return False
    destStart = max(0, min(int(destStart), n - count))
    if destStart == srcStart:
        return False
    order = list(range(n))
    block = order[srcStart:srcStart + count]
    rest = order[:srcStart] + order[srcStart + count:]
    insertAt = destStart if destStart <= srcStart else destStart - count
    insertAt = max(0, min(insertAt, len(rest)))
    newOrder = rest[:insertAt] + block + rest[insertAt:]
    if newOrder == order:
        return False

    metas = _metas(mainWindow)
    rules = list(getattr(table, "columnRoundingRules", None) or [])
    while len(metas) < n:
        metas.append({})
    while len(rules) < n:
        rules.append(Logic.DEFAULT_ROUNDING_SPEC)

    packs = []
    table.blockSignals(True)
    header = table.horizontalHeader()
    header.blockSignals(True)
    try:
        for i in range(n):
            packs.append((
                _headerText(table, i),
                [_cloneItem(table.item(r, i)) for r in range(table.rowCount())],
                dict(metas[i]) if i < len(metas) else {},
                rules[i] if i < len(rules) else Logic.DEFAULT_ROUNDING_SPEC,
            ))
        timestamps = []
        for r in range(table.rowCount()):
            tsItem = table.verticalHeaderItem(r)
            timestamps.append(tsItem.text() if tsItem else "")
        newMetas = []
        newRules = []
        for dest, src in enumerate(newOrder):
            h, items, meta, rule = packs[src]
            _setHeaderText(table, dest, h)
            for r, item in enumerate(items):
                table.setItem(r, dest, item)
            newMetas.append(meta)
            newRules.append(rule)
        if timestamps and any(timestamps):
            table.setVerticalHeaderLabels(timestamps)
        table.columnRoundingRules = newRules
        mainWindow.columnMetadata = newMetas
    finally:
        header.blockSignals(False)
        table.blockSignals(False)
    _rebuildQueryItemsFromTable(mainWindow)
    _rememberCustomColumns(mainWindow)
    _syncQueryList(mainWindow)
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"TableOps.moveColumnRange src={srcStart} count={count} dest={destStart} order={newOrder}",
        )
    return True


def _rebuildQueryItemsFromTable(mainWindow):
    """Rebuild lastQueryItems from columnMetadata order (skip custom + delta)."""
    items = []
    seen = 0
    for meta in _metas(mainWindow):
        t = (meta or {}).get("type") or "normal"
        if t in ("custom", "delta"):
            continue
        infos = meta.get("queryInfos") or []
        if not isinstance(infos, list):
            infos = [infos]
        for q in infos:
            dataId, interval, database = Upload.parseQueryInfo(q)
            if not dataId:
                continue
            mrid = "0"
            if str(database).startswith("USBR-") and "-" in dataId:
                _sdid, mrid = dataId.rsplit("-", 1)
            items.append((dataId, interval, database, mrid, seen))
            seen += 1
    if items:
        mainWindow.lastQueryItems = items


def _syncQueryList(mainWindow):
    winQuery = getattr(mainWindow, "winQuery", None)
    lst = getattr(winQuery, "listQueryList", None) if winQuery is not None else None
    if lst is None:
        return
    items = getattr(mainWindow, "lastQueryItems", None) or []
    lst.blockSignals(True)
    try:
        lst.clear()
        for dataId, interval, database, _mrid, _idx in items:
            lst.addItem(f"{dataId}|{interval}|{database}")
    finally:
        lst.blockSignals(False)


def enableColumnDrag(mainWindow):
    """
    Column reorder is owned by Upload._HeaderSelectFilter (click vs drag).
    Qt setSectionsMovable is left OFF so a header click cannot look like a sort.
    """
    table = _table(mainWindow)
    if table is None:
        return
    table.setSortingEnabled(False)
    header = table.horizontalHeader()
    header.setSectionsMovable(False)
    try:
        header.setSortIndicatorShown(False)
    except Exception:
        pass
    Upload.ensureHeaderSelectionSync(mainWindow)


def renameHeader(mainWindow, col):
    """Rename the commonName portion of any header (not the datatype suffix)."""
    table = _table(mainWindow)
    if table is None or col < 0:
        return
    meta = _meta(mainWindow, col)
    full = _headerText(table, col)
    first = firstHeaderLine(full)
    rest = headerRestLines(full)
    dataIds = meta.get("dataIds") or []
    dbs = meta.get("dbs") or []
    dataId = dataIds[0] if dataIds else ""
    db = dbs[0] if dbs else ""
    if isinstance(db, list) and db:
        db = db[0]
    datatype = ""
    if meta.get("type") == "custom":
        currentCommon = meta.get("name") or first
    else:
        datatype = _dictDatatype(mainWindow, dataId, db)
        currentCommon = splitCommonName(first, datatype)

    newCommon, ok = QInputDialog.getText(
        mainWindow, "Rename header", "Common name:", text=currentCommon
    )
    if not ok:
        return
    newCommon = (newCommon or "").strip()
    if not newCommon:
        return
    if meta.get("type") == "custom":
        meta["name"] = newCommon
        _setHeaderText(table, col, Utils.formatTableHeaderLabel(newCommon))
        _rememberCustomColumns(mainWindow)
        return
    if datatype and Utils.includeDataTypeInLabel(db):
        newFirst = f"{newCommon}-{datatype}"
    else:
        newFirst = newCommon
    newHeader = newFirst if not rest.strip() else f"{newFirst} \n{rest.lstrip()}"
    _setHeaderText(table, col, Utils.formatTableHeaderLabel(newHeader))
    if dataId:
        renames = getattr(mainWindow, "headerRenames", None)
        if renames is None:
            renames = {}
            mainWindow.headerRenames = renames
        renames[str(dataId)] = {
            "commonName": newCommon,
            "dataId": dataId,
            "database": db,
            "col": col,
            "type": meta.get("type"),
        }
    if Config.debug:
        Logic.logMessage("DEBUG", f"TableOps.renameHeader col={col} → {newCommon!r}")


def reapplyHeaderRenames(mainWindow):
    table = _table(mainWindow)
    renames = getattr(mainWindow, "headerRenames", None) or {}
    if table is None or not renames:
        return
    for c in range(table.columnCount()):
        meta = _meta(mainWindow, c)
        dataIds = meta.get("dataIds") or []
        dataId = str(dataIds[0]) if dataIds else ""
        spec = renames.get(dataId)
        if not spec:
            continue
        newCommon = spec.get("commonName") or ""
        if not newCommon:
            continue
        db = (meta.get("dbs") or [""])[0]
        datatype = _dictDatatype(mainWindow, dataId, db)
        first = firstHeaderLine(_headerText(table, c))
        rest = headerRestLines(_headerText(table, c))
        if datatype and Utils.includeDataTypeInLabel(db):
            newFirst = f"{newCommon}-{datatype}"
        else:
            newFirst = newCommon
        newHeader = newFirst if not rest.strip() else f"{newFirst} \n{rest.lstrip()}"
        _setHeaderText(table, c, Utils.formatTableHeaderLabel(newHeader))


def _dictionaryLookupId(dataId, database) -> str:
    from core.Query import dictionaryLookupKey
    return dictionaryLookupKey(dataId, database)


def _usgsFieldsFromResponse(response) -> dict:
    meta = {}
    if isinstance(response, dict):
        meta = response.get("seriesMeta") or {}
    mid = str(meta.get("Monitoring Location ID") or "")
    siteId = ""
    if "-" in mid:
        siteId = mid.split("-", 1)[1].strip()
    elif mid:
        siteId = mid
    return {
        "siteID": siteId,
        "siteName": str(meta.get("Site Name") or ""),
        "datatype": str(meta.get("Parameter Name") or ""),
        "dataID": str(meta.get("Time Series ID") or ""),
    }


def _aquariusFieldsFromResponse(response) -> dict:
    raw = response if isinstance(response, dict) else {}
    if "rawResponse" in raw and isinstance(raw["rawResponse"], dict):
        raw = raw["rawResponse"]
    param = raw.get("Parameter") or raw.get("parameter") or ""
    return {"datatype": str(param or "")}


def promptDictionaryRenames(mainWindow):
    """After a new query, offer to save renamed commonNames into bunker.db."""
    renames = getattr(mainWindow, "headerRenames", None) or {}
    if not renames:
        return
    # Only prompt for dataIDs that are in the current table
    present = set()
    for meta in _metas(mainWindow):
        for did in (meta.get("dataIds") or []):
            present.add(str(did))
    pending = {k: v for k, v in renames.items() if k in present}
    if not pending:
        return
    names = ", ".join(sorted({v.get("commonName") or k for k, v in pending.items()}))
    box = QMessageBox(mainWindow)
    box.setWindowTitle("Headers renamed")
    box.setText(
        "Headers renamed, save/update Data Dictionary as Common Name?\n\n"
        f"{names}"
    )
    saveBtn = box.addButton("Save / update", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is not saveBtn:
        return
    for spec in pending.values():
        _upsertDictionaryCommonName(mainWindow, spec)
    try:
        winDd = getattr(mainWindow, "winDataDictionary", None)
        if winDd is not None and getattr(winDd, "mainTable", None) is not None:
            Utils.loadDataDictionary(winDd.mainTable)
    except Exception as e:
        Logic.logException("promptDictionaryRenames: reload dictionary failed", e)
    mainWindow.headerRenames = {
        k: v for k, v in renames.items() if k not in pending
    }


def _upsertDictionaryCommonName(mainWindow, spec):
    import sqlite3
    dataId = spec.get("dataId") or ""
    database = spec.get("database") or ""
    commonName = spec.get("commonName") or ""
    if not dataId or not commonName:
        return
    lookupId = _dictionaryLookupId(dataId, database)
    fields = {
        "dataID": lookupId,
        "database": database,
        "commonName": commonName,
    }
    responses = getattr(mainWindow, "seriesResponses", None) or {}
    response = responses.get(dataId) or responses.get(lookupId)
    if Upload.isUsgsDb(database):
        extra = _usgsFieldsFromResponse(response)
        if extra.get("dataID"):
            fields["dataID"] = extra["dataID"]
        if extra.get("siteID"):
            fields["siteID"] = extra["siteID"]
        if extra.get("siteName"):
            fields["siteName"] = extra["siteName"]
        if extra.get("datatype"):
            fields["datatype"] = extra["datatype"]
    elif Upload.isAquariusDb(database):
        extra = _aquariusFieldsFromResponse(response)
        if extra.get("datatype"):
            fields["datatype"] = extra["datatype"]
    elif str(database).startswith("USBR-"):
        # SDID without MRID
        fields["dataID"] = str(dataId).split("-", 1)[0]

    dbPath = Logic.resourcePath("core/bunker.db")
    try:
        Logic.ensureDataDictionarySchema()
        with sqlite3.connect(dbPath) as conn:
            cur = conn.cursor()
            cur.execute(
                'SELECT rowid FROM dataDictionary WHERE dataID = ? AND database = ?',
                (fields["dataID"], fields["database"]),
            )
            row = cur.fetchone()
            if row:
                sets = ", ".join(f'"{k}" = ?' for k in fields if k not in ("dataID", "database"))
                vals = [fields[k] for k in fields if k not in ("dataID", "database")]
                vals.extend([fields["dataID"], fields["database"]])
                cur.execute(
                    f'UPDATE dataDictionary SET {sets} WHERE dataID = ? AND database = ?',
                    vals,
                )
            else:
                cols = list(fields.keys())
                placeholders = ", ".join("?" for _ in cols)
                colSql = ", ".join(f'"{c}"' for c in cols)
                cur.execute(
                    f"INSERT INTO dataDictionary ({colSql}) VALUES ({placeholders})",
                    [fields[c] for c in cols],
                )
            conn.commit()
        Logic.logMessage(
            "INFO",
            f"Data Dictionary {'updated' if row else 'inserted'} "
            f"dataID={fields['dataID']!r} commonName={commonName!r}",
        )
    except Exception as e:
        Logic.logException("upsert dictionary commonName failed", e)


def swapOverlayPrimarySecondary(mainWindow, col):
    """Swap which series is primary vs secondary for an overlay column."""
    table = _table(mainWindow)
    meta = _meta(mainWindow, col)
    if table is None or meta.get("type") != "overlay":
        return
    dataIds = list(meta.get("dataIds") or [])
    dbs = list(meta.get("dbs") or [])
    queryInfos = list(meta.get("queryInfos") or [])
    lookupId = list(meta.get("lookupId") or []) if isinstance(meta.get("lookupId"), list) else meta.get("lookupId")
    headers = list(meta.get("headerFirstLines") or [])
    if len(dataIds) < 2 or len(queryInfos) < 2:
        return
    dataIds[0], dataIds[1] = dataIds[1], dataIds[0]
    if len(dbs) >= 2:
        dbs[0], dbs[1] = dbs[1], dbs[0]
    queryInfos[0], queryInfos[1] = queryInfos[1], queryInfos[0]
    if isinstance(lookupId, list) and len(lookupId) >= 2:
        lookupId[0], lookupId[1] = lookupId[1], lookupId[0]
        meta["lookupId"] = lookupId
    if len(headers) >= 2:
        headers[0], headers[1] = headers[1], headers[0]
        meta["headerFirstLines"] = headers
    meta["dataIds"] = dataIds
    meta["dbs"] = dbs
    meta["queryInfos"] = queryInfos

    table.blockSignals(True)
    try:
        for r in range(table.rowCount()):
            item = table.item(r, col)
            if item is None:
                continue
            user = Upload.getUserDict(item)
            if not user.get("overlay"):
                continue
            p, s = user.get("primaryVal", ""), user.get("secondaryVal", "")
            user["primaryVal"], user["secondaryVal"] = s, p
            user["dataId1"], user["dataId2"] = user.get("dataId2"), user.get("dataId1")
            user["db1"], user["db2"] = user.get("db2"), user.get("db1")
            pDec = parseDecimalText(s)
            sDec = parseDecimalText(p)
            dRule = None
            rules = getattr(table, "columnRoundingRules", None) or []
            if col < len(rules):
                dRule = rules[col]
            if pDec is not None and sDec is not None:
                user["delta"] = formatDeltaValue(pDec - sDec, dRule)
            else:
                user["delta"] = ""
            Upload.setUserDict(item, user)
            # Display follows new primary (old secondary)
            hasP = bool(str(user.get("primaryVal") or "").strip())
            hasS = bool(str(user.get("secondaryVal") or "").strip())
            item.setText(user["primaryVal"] if hasP else (user["secondaryVal"] if hasS else ""))
        # Matching delta column: negate values / swap colors
        if col + 1 < table.columnCount() and isDeltaColumn(mainWindow, col + 1):
            dCol = col + 1
            dMeta = _meta(mainWindow, dCol)
            dMeta["dataIds"] = list(dataIds)
            dMeta["dbs"] = list(dbs)
            dMeta["queryInfos"] = list(queryInfos)
            for r in range(table.rowCount()):
                dItem = table.item(r, dCol)
                if dItem is None or not dItem.text().strip():
                    continue
                try:
                    val = float(dItem.text())
                except ValueError:
                    continue
                newVal = -val
                dItem.setText(formatDeltaValue(parseDecimalText(str(newVal)), None) or ("0" if newVal == 0 else str(newVal)))
                if newVal > 0:
                    TableColors.applyToItem(dItem, "deltaPositive")
                elif newVal < 0:
                    TableColors.applyToItem(dItem, "deltaNegative")
                else:
                    dItem.setForeground(Config.systemTextColor)
                    dItem.setBackground(QBrush())
    finally:
        table.blockSignals(False)

    from core import QueryUtils
    QueryUtils.applyOverlayColorOverrides(table)
    _rebuildQueryItemsFromTable(mainWindow)
    _syncQueryList(mainWindow)
    # Swap header to the new primary's first line when we have it
    if headers:
        rest = headerRestLines(_headerText(table, col))
        newFirst = headers[0]
        newHeader = newFirst if not rest.strip() else f"{newFirst} \n{rest.lstrip()}"
        _setHeaderText(table, col, Utils.formatTableHeaderLabel(newHeader))
    if Config.debug:
        Logic.logMessage("DEBUG", f"TableOps.swapOverlay col={col} now primary={dataIds[0]}")


def overlayDiffers(item) -> bool:
    if item is None:
        return False
    user = Upload.getUserDict(item)
    if not user.get("overlay"):
        return False
    p = str(user.get("primaryVal") or "").strip()
    s = str(user.get("secondaryVal") or "").strip()
    if not p or not s:
        return False
    d = str(user.get("delta") or "").strip()
    try:
        return float(d) != 0
    except ValueError:
        return p != s


def updateFromSecondary(mainWindow, cells):
    """
    Copy secondary overlay value into the displayed (primary) cell for
    cells whose pair differs. Skips USGS / Aquarius primaries.
    cells: iterable of (row, col)
    """
    table = _table(mainWindow)
    if table is None:
        return 0
    updated = 0
    Undo.stackFor(mainWindow).beginMacro()
    try:
        for row, col in cells:
            meta = _meta(mainWindow, col)
            if meta.get("type") != "overlay":
                continue
            dbs = meta.get("dbs") or []
            primaryDb = dbs[0] if dbs else ""
            if Upload.isUsgsDb(primaryDb) or Upload.isAquariusDb(primaryDb):
                continue
            item = table.item(row, col)
            if not overlayDiffers(item):
                continue
            user = Upload.getUserDict(item)
            secondary = str(user.get("secondaryVal") or "")
            oldText = item.text() if item is not None else ""
            oldFormula = _itemFormula(item)
            applyCellInput(mainWindow, row, col, secondary)
            Undo.pushCellEdit(mainWindow, row, col, oldText, oldFormula, secondary, None)
            updated += 1
    finally:
        Undo.stackFor(mainWindow).endMacro()
        recalculateAll(mainWindow)
    if Config.debug:
        Logic.logMessage("DEBUG", f"TableOps.updateFromSecondary updated {updated} cell(s)")
    return updated


def selectedCells(table):
    cells = set()
    if table is None:
        return cells
    try:
        for idx in table.selectedIndexes():
            cells.add((idx.row(), idx.column()))
        for r in table.selectedRanges():
            for row in range(r.topRow(), r.bottomRow() + 1):
                for col in range(r.leftColumn(), r.rightColumn() + 1):
                    cells.add((row, col))
    except Exception:
        pass
    return cells


def afterQuery(mainWindow, isRefresh=False):
    """Re-apply custom columns, header renames, and column-drag after a query."""
    if isRefresh:
        restoreCustomColumns(mainWindow)
        reapplyHeaderRenames(mainWindow)
    else:
        # New query: keep rename mapping (prompt below) but drop custom cols
        # from the previous table unless the user re-inserts them.
        mainWindow.customColumns = []
        reapplyHeaderRenames(mainWindow)
        promptDictionaryRenames(mainWindow)
    enableColumnDrag(mainWindow)
    Undo.stackFor(mainWindow).clear()
