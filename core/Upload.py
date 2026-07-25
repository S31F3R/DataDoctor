# Upload.py
# Track table edits, prepare write payloads, and dry-run export to documentation/*.csv

import csv
import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QAbstractItemView, QMessageBox

from core import Logic, Config

# User-edited / pending upload (magenta + white) — not used by QAQC
editBg = QColor(0xC2, 0x18, 0x5B)  # #C2185B
editFg = QColor(255, 255, 255)

# Uploaded successfully this session (deep teal + white) — unused elsewhere
uploadOkBg = QColor(0x00, 0x69, 0x5C)  # #00695C
uploadOkFg = QColor(255, 255, 255)

editKey = 'uploadEdit'


def isUsgsDb(db):
    if not db:
        return False
    s = str(db).strip().upper()
    return s == 'USGS' or s.startswith('USGS')


def isPublicQuery(mainWindow):
    qt = getattr(mainWindow, 'lastQueryType', None) or getattr(mainWindow, 'currentQueryType', None) or ''
    return str(qt).strip().lower() == 'public'


def getUserDict(item):
    if item is None:
        return {}
    data = item.data(Qt.ItemDataRole.UserRole)
    return dict(data) if isinstance(data, dict) else {}


def setUserDict(item, user):
    item.setData(Qt.ItemDataRole.UserRole, user)


def getEditState(item):
    user = getUserDict(item)
    edit = user.get(editKey)
    return user, (dict(edit) if isinstance(edit, dict) else {})


def brushToColor(brushOrColor):
    """Normalize QBrush / QColor / None for storage and re-apply."""
    if brushOrColor is None:
        return None
    if isinstance(brushOrColor, QColor):
        return QColor(brushOrColor)
    if isinstance(brushOrColor, QBrush):
        c = brushOrColor.color()
        # Style-role / empty brushes — treat as no override
        if not c.isValid():
            return None
        return QColor(c)
    return None


def captureItemColors(item):
    bg = brushToColor(item.background())
    fgRole = item.data(Qt.ItemDataRole.ForegroundRole)
    if isinstance(fgRole, QBrush):
        fg = brushToColor(fgRole)
    else:
        fg = brushToColor(item.foreground())
    return bg, fg


def applyColors(item, bg, fg):
    if bg is not None:
        item.setBackground(bg)
    else:
        item.setBackground(QBrush())
    if fg is not None:
        item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(fg))
        item.setForeground(fg)
    else:
        item.setData(Qt.ItemDataRole.ForegroundRole, None)
        item.setForeground(QBrush())


def applyEditStyle(item):
    item.setBackground(editBg)
    item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(editFg))
    item.setForeground(editFg)


def applyUploadOkStyle(item):
    item.setBackground(uploadOkBg)
    item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(uploadOkFg))
    item.setForeground(uploadOkFg)


def parseQueryInfo(queryInfo):
    """Return (dataId, interval, database) from 'dataId|interval|database'."""
    if not queryInfo:
        return '', '', ''
    parts = str(queryInfo).split('|')
    if len(parts) >= 3:
        return parts[0].strip(), parts[1].strip(), parts[2].strip()
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ''
    return parts[0].strip(), '', ''


def primaryMeta(meta):
    """Resolve primary series fields from columnMetadata entry."""
    if not meta:
        return None
    colType = meta.get('type') or 'normal'
    if colType == 'delta':
        return None

    dataIds = meta.get('dataIds') or []
    dbs = meta.get('dbs') or []
    queryInfos = meta.get('queryInfos') or []

    if not isinstance(dataIds, list):
        dataIds = [dataIds]
    if not isinstance(dbs, list):
        dbs = [dbs]
    if not isinstance(queryInfos, list):
        queryInfos = [queryInfos]

    dataId = dataIds[0] if dataIds else ''
    db = dbs[0] if dbs else ''
    qInfo = queryInfos[0] if queryInfos else ''
    qDataId, interval, qDb = parseQueryInfo(qInfo)

    # Prefer full dataId from queryInfo when present; fall back to metadata id
    if qDataId:
        dataId = qDataId
    if qDb:
        db = qDb

    if not dataId or not db:
        return None
    if isUsgsDb(db):
        return None

    return {
        'type': colType,
        'dataId': str(dataId),
        'db': str(db),
        'interval': interval or '',
    }


def documentationDir():
    """Project documentation folder (dev and bundled)."""
    path = Logic.resourcePath('documentation')
    os.makedirs(path, exist_ok=True)
    return path


def outputCsvPath(dbName):
    """e.g. USBR-LCHDB → documentation/outputUSBR-LCHDB.csv"""
    safe = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in str(dbName).strip())
    if not safe:
        safe = 'UNKNOWN'
    return os.path.join(documentationDir(), f'output{safe}.csv')


def columnIsLocked(mainWindow, col, meta=None):
    """Public queries lock all cells; delta columns always locked from edit."""
    if mainWindow is not None and isPublicQuery(mainWindow):
        return True
    if meta is None and mainWindow is not None:
        metas = getattr(mainWindow, 'columnMetadata', None) or []
        meta = metas[col] if col < len(metas) else {}
    colType = (meta.get('type') or 'normal') if isinstance(meta, dict) else 'normal'
    return colType == 'delta'


def applyEditability(table, mainWindow=None):
    """
    Public: no cell editing (context menu + header sort still work).
    Internal: normal/overlay editable; delta columns locked.
    """
    if table is None:
        return

    isPublic = isPublicQuery(mainWindow) if mainWindow is not None else False
    if isPublic:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    else:
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )

    metas = getattr(mainWindow, 'columnMetadata', None) or [] if mainWindow is not None else []
    table.blockSignals(True)
    try:
        for c in range(table.columnCount()):
            meta = metas[c] if c < len(metas) else {}
            lockCol = columnIsLocked(mainWindow, c, meta)
            for r in range(table.rowCount()):
                item = table.item(r, c)
                if item is None:
                    continue
                flags = item.flags()
                if lockCol:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(
                        flags
                        | Qt.ItemFlag.ItemIsEditable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
    finally:
        table.blockSignals(False)


def prepareTableForEditing(table, mainWindow=None):
    """Apply edit triggers + per-column lock flags after a data query."""
    applyEditability(table, mainWindow)


def snapshotBaseline(table, mainWindow=None):
    """
    After query/QAQC colors are applied: store original text + colors per cell
    so later edits can be flagged and reverted styles restored.
    """
    if table is None:
        return
    table.blockSignals(True)
    try:
        from PyQt6.QtWidgets import QTableWidgetItem

        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item is None:
                    item = QTableWidgetItem('')
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                    table.setItem(r, c, item)
                user = getUserDict(item)
                bg, fg = captureItemColors(item)
                text = item.text() if item.text() is not None else ''
                user[editKey] = {
                    'originalText': text,
                    'baselineBg': bg,
                    'baselineFg': fg,
                    'dirty': False,
                    'uploaded': False,
                }
                setUserDict(item, user)
        if mainWindow is not None:
            mainWindow.uploadBaselineReady = True
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Upload.snapshotBaseline: {table.rowCount()}×{table.columnCount()} cells",
            )
    finally:
        table.blockSignals(False)

    applyEditability(table, mainWindow)


def countPendingEdits(mainWindow):
    """Number of cells with unsaved (dirty) edits."""
    if mainWindow is None:
        return 0
    table = mainWindow.mainTable
    if table is None:
        return 0
    n = 0
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item is None:
                continue
            _, edit = getEditState(item)
            if edit.get('dirty'):
                n += 1
    return n


def confirmDiscardPendingEdits(parent, actionDescription="run a new query"):
    """
    If dirty edits exist, warn and ask to discard or cancel.
    Returns True if safe to proceed (no edits, or user chose discard).
    """
    mainWindow = parent
    # uiQuery passes itself; prefer winMain when present
    if hasattr(parent, 'winMain') and parent.winMain is not None:
        mainWindow = parent.winMain
    count = countPendingEdits(mainWindow)
    if count <= 0:
        return True

    reply = QMessageBox.warning(
        parent,
        "Unsaved Edits",
        f"You have {count} edited cell(s) that have not been uploaded.\n\n"
        f"If you {actionDescription}, those changes will be lost.\n\n"
        "Discard edits and continue?",
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return reply == QMessageBox.StandardButton.Ok


def onItemChanged(mainWindow, item):
    """Mark cell dirty (edit colors) or restore baseline when text matches original."""
    if item is None or mainWindow is None:
        return
    if getattr(mainWindow, 'uploadTrackingBlocked', False):
        return
    if not getattr(mainWindow, 'uploadBaselineReady', False):
        return
    table = mainWindow.mainTable
    if table is None or item.tableWidget() is not table:
        return

    user, edit = getEditState(item)
    if not edit:
        # Late-created item: seed baseline from current (no prior snapshot)
        bg, fg = captureItemColors(item)
        edit = {
            'originalText': item.text(),
            'baselineBg': bg,
            'baselineFg': fg,
            'dirty': False,
            'uploaded': False,
        }

    current = item.text() if item.text() is not None else ''
    original = edit.get('originalText', '')
    table.blockSignals(True)
    try:
        if current != original:
            edit['dirty'] = True
            edit['uploaded'] = False
            user[editKey] = edit
            setUserDict(item, user)
            applyEditStyle(item)
        else:
            # Restored to original — clear dirty; keep uploaded style if already uploaded
            wasUploaded = bool(edit.get('uploaded'))
            edit['dirty'] = False
            user[editKey] = edit
            setUserDict(item, user)
            if wasUploaded:
                applyUploadOkStyle(item)
            else:
                applyColors(item, edit.get('baselineBg'), edit.get('baselineFg'))
    finally:
        table.blockSignals(False)


def collectUploadRows(mainWindow):
    """
    Build list of dicts ready for CSV / future DB write from user-edited cells only.
    Overlay values go to the primary series; user must edit the cell deliberately.
    """
    rows = []
    table = mainWindow.mainTable
    if table is None or table.rowCount() == 0:
        return rows

    # Public: cells are locked; nothing should be dirty
    if isPublicQuery(mainWindow):
        return rows

    columnMetadata = getattr(mainWindow, 'columnMetadata', None) or []
    numCols = table.columnCount()
    numRows = table.rowCount()

    for c in range(numCols):
        meta = columnMetadata[c] if c < len(columnMetadata) else {}
        primary = primaryMeta(meta)
        if primary is None:
            continue

        for r in range(numRows):
            item = table.item(r, c)
            if item is None:
                continue
            _, edit = getEditState(item)
            if not edit.get('dirty'):
                continue

            tsItem = table.verticalHeaderItem(r)
            timestamp = tsItem.text() if tsItem else ''
            originalText = edit.get('originalText', '')
            if originalText is None:
                originalText = ''
            value = item.text() if item.text() is not None else ''

            rows.append({
                'database': primary['db'],
                'dataId': primary['dataId'],
                'interval': primary['interval'],
                'timestamp': timestamp,
                'value': value,
                'originalValue': originalText,
                'reason': 'userEdit',
                'row': r,
                'col': c,
            })

    return rows


def writeUploadCsvs(uploadRows):
    """
    Group by database; overwrite documentation/output{DB}.csv (long form).
    Returns (writtenPaths, cellCoordsMarked) or raises on failure.
    """
    byDb = {}
    for row in uploadRows:
        byDb.setdefault(row['database'], []).append(row)

    written = []
    for db, rows in byDb.items():
        path = outputCsvPath(db)
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Database', 'DataID', 'Interval', 'Timestamp',
                'Value', 'OriginalValue', 'Reason',
            ])
            # Stable order: timestamp, dataId
            rowsSorted = sorted(rows, key=lambda x: (x.get('timestamp', ''), x.get('dataId', '')))
            for r in rowsSorted:
                writer.writerow([
                    r['database'],
                    r['dataId'],
                    r['interval'],
                    r['timestamp'],
                    r['value'],
                    r['originalValue'],
                    r['reason'],
                ])
        written.append(path)
        if Config.debug:
            Logic.logMessage("DEBUG", f"Upload.writeUploadCsvs: wrote {len(rows)} rows → {path}")

    return written


def markUploaded(mainWindow, uploadRows):
    """After successful file write: success colors, clear dirty, update originalText."""
    table = mainWindow.mainTable
    if table is None:
        return
    table.blockSignals(True)
    mainWindow.uploadTrackingBlocked = True
    try:
        for r in uploadRows:
            item = table.item(r['row'], r['col'])
            if item is None:
                continue
            user, edit = getEditState(item)
            newText = r['value']
            if item.text() != newText:
                item.setText(newText)
            edit['originalText'] = newText
            edit['dirty'] = False
            edit['uploaded'] = True
            edit['baselineBg'] = QColor(uploadOkBg)
            edit['baselineFg'] = QColor(uploadOkFg)
            user[editKey] = edit
            # Keep overlay UserRole in sync with the value the user uploaded to primary
            if user.get('overlay'):
                user['primaryVal'] = newText
                sStr = str(user.get('secondaryVal', '') or '').strip()
                try:
                    p = float(newText) if str(newText).strip() else float('nan')
                    s = float(sStr) if sStr else float('nan')
                    if p == p and s == s:
                        user['delta'] = str(p - s)
                    else:
                        user['delta'] = ''
                except ValueError:
                    user['delta'] = '' if newText == sStr else '1'
            setUserDict(item, user)
            applyUploadOkStyle(item)
    finally:
        mainWindow.uploadTrackingBlocked = False
        table.blockSignals(False)


def runUpload(mainWindow):
    """
    btnUpload entry point: collect user edits, write CSVs, mark success.
    Public queries have editing locked; no special dialog for that case.
    """
    try:
        table = mainWindow.mainTable
        if table is None or table.rowCount() == 0:
            QMessageBox.information(mainWindow, "Upload", "No data in the table to upload.")
            return

        if not getattr(mainWindow, 'uploadBaselineReady', False):
            # Defensive: snapshot if query path missed it
            snapshotBaseline(table, mainWindow)

        uploadRows = collectUploadRows(mainWindow)
        if not uploadRows:
            QMessageBox.information(
                mainWindow,
                "Upload",
                "Nothing to upload.\n\n"
                "Edit cells after an internal query to flag them for upload.",
            )
            return

        paths = writeUploadCsvs(uploadRows)
        markUploaded(mainWindow, uploadRows)

        byDb = {}
        for r in uploadRows:
            byDb[r['database']] = byDb.get(r['database'], 0) + 1
        summaryLines = [f"  {db}: {n} value(s) → {os.path.basename(outputCsvPath(db))}" for db, n in sorted(byDb.items())]
        pathList = '\n'.join(paths)
        QMessageBox.information(
            mainWindow,
            "Upload Complete",
            f"Wrote {len(uploadRows)} value(s) to {len(paths)} file(s) "
            f"(dry-run; files overwritten each upload):\n\n"
            + '\n'.join(summaryLines)
            + f"\n\n{pathList}",
        )
        Logic.logMessage(
            "INFO",
            f"Upload dry-run: {len(uploadRows)} rows → {paths}",
        )
    except Exception as e:
        Logic.logException("Upload.runUpload failed", e)
        QMessageBox.warning(mainWindow, "Upload Error", f"Failed to write upload files:\n{e}")
