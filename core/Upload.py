# Upload.py
# Track table edits, prepare write payloads, and upload to HDB
# (MODIFY_R_BASE for values; DELETE_R_BASE for blank cells).
# Aquarius writes are stubbed (popup + success styling until implemented).

import queue
import threading
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QAbstractItemView, QMessageBox

from core import Logic, Config, Oracle

# User-edited / pending upload (magenta + white) — not used by QAQC
editBg = QColor(0xC2, 0x18, 0x5B)  # #C2185B
editFg = QColor(255, 255, 255)

# Uploaded successfully this session (deep teal + white) — unused elsewhere
uploadOkBg = QColor(0x00, 0x69, 0x5C)  # #00695C
uploadOkFg = QColor(255, 255, 255)

editKey = 'uploadEdit'

# Parallel writers per HDB database (mirrors USBR.sqlRead style)
maxWriteThreads = 8

# MODIFY_R_BASE parameter names in procedure order (DEBUG labels only)
modifyRBaseParamNames = (
    'SITE_DATATYPE_ID',
    'INTERVAL',
    'START_DATE_TIME',
    'END_DATE_TIME',
    'VALUE',
    'AGEN_ID',
    'OVERWRITE_FLAG',
    'VALIDATION',
    'COLLECTION_SYSTEM_ID',
    'LOADING_APPLICATION_ID',
    'METHOD_ID',
    'COMPUTATION_ID',
    'DO_UPDATE_Y_OR_N',
    'DATA_FLAGS',
    'TIME_ZONE',
)

# DELETE_R_BASE — blank cell edit; same date/interval/agen/loading rules as MODIFY
# SDID is required to identify the series (same parse as MODIFY).
deleteRBaseParamNames = (
    'SITE_DATATYPE_ID',
    'INTERVAL',
    'START_DATE_TIME',
    'END_DATE_TIME',
    'AGEN_ID',
    'LOADING_APPLICATION_ID',
)


# ---------------------------------------------------------------------------
# Helpers: DB kind / DSN / interval / style
# ---------------------------------------------------------------------------

def isUsgsDb(db):
    if not db:
        return False
    s = str(db).strip().upper()
    return s == 'USGS' or s.startswith('USGS')


def isHdbDb(db):
    """USBR HDB databases (USBR-LCHDB, USBR-UCHDB2, ...)."""
    if not db:
        return False
    return str(db).strip().upper().startswith('USBR-')


def isAquariusDb(db):
    if not db:
        return False
    return str(db).strip().upper() == 'AQUARIUS'


def isPublicQuery(mainWindow):
    qt = getattr(mainWindow, 'lastQueryType', None) or getattr(mainWindow, 'currentQueryType', None) or ''
    return str(qt).strip().lower() == 'public'


def databaseToDsn(dbName):
    """
    Map UI database name to Oracle TNS alias.
    USBR-LCHDB → lchdb; USBR-UCHDB2 → uchdb2.
    Writing cannot use database links — connect to each DSN separately.
    """
    s = str(dbName or '').strip()
    if '-' in s:
        return s.split('-', 1)[1].lower()
    return s.lower()


def modifyInterval(interval):
    """Map UI interval string to HDB MODIFY_R_BASE INTERVAL value (lowercase)."""
    iv = str(interval or '').strip().upper()
    if iv.startswith('INSTANT'):
        return 'instant'
    if iv == 'WATER YEAR':
        return 'wy'
    if iv in ('HOUR', 'DAY', 'MONTH', 'YEAR'):
        return iv.lower()
    if not iv:
        raise ValueError('Interval is empty; cannot write to HDB')
    return iv.lower()


def parseSdid(dataId):
    """
    SITE_DATATYPE_ID from dataId. Strips trailing -mrid when present (e.g. 20179-0 → 20179).
    """
    s = str(dataId or '').strip()
    if not s:
        raise ValueError('dataId is empty')
    if '-' in s:
        left, right = s.rsplit('-', 1)
        if left.isdigit() and right.isdigit():
            return int(left)
    if s.isdigit():
        return int(s)
    raise ValueError(f'Invalid SITE_DATATYPE_ID (dataId): {dataId!r}')


def isBlankUploadValue(valueText):
    """True if the edited cell is empty / whitespace-only (→ DELETE_R_BASE)."""
    text = '' if valueText is None else str(valueText).strip()
    return text == ''


def parseUploadValue(valueText):
    """Parse cell text to Decimal for VALUE; reject blanks / non-numeric."""
    text = '' if valueText is None else str(valueText).strip()
    if text == '':
        raise ValueError('Value is blank')
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f'Invalid numeric value {valueText!r}: {e}') from e


def resolveUploadDateTimes(uploadRow):
    """
    Shared START/END datetime resolution for MODIFY_R_BASE and DELETE_R_BASE.

    Returns (intervalStr, startDt, endDt, sdid) using the same rules as modify:
      HOUR + EOP → START = display − 1h, END = display
      HOUR + BOP → START = display, END = display + 1h
      other      → START = display, END = null
    """
    # Lazy import: Query imports Upload for snapshotBaseline (avoid circular import)
    from core import Query

    sdid = parseSdid(uploadRow.get('dataId'))
    interval = modifyInterval(uploadRow.get('interval'))
    displayTs = uploadRow.get('timestamp', '')
    displayDt = Query.parseDisplayTimestamp(displayTs)
    if displayDt is None:
        raise ValueError(f'Unparseable timestamp: {displayTs!r}')

    startDt, endDt = dateTimeParams(uploadRow.get('interval'), displayDt)
    return interval, startDt, endDt, sdid


def dateTimeParams(interval, displayDt):
    """
    Choose START_DATE_TIME / END_DATE_TIME for MODIFY_R_BASE / DELETE_R_BASE.

    HOUR data always sends both ends of the period (procedures need a full range):

      HOUR + EOP (Config.periodOffset True):
        END_DATE_TIME   = display timestamp (end of period)
        START_DATE_TIME = display timestamp − 1 hour

      HOUR + BOP (Config.periodOffset False):
        START_DATE_TIME = display timestamp (beginning of period)
        END_DATE_TIME   = display timestamp + 1 hour

      All other intervals:
        START_DATE_TIME = display timestamp
        END_DATE_TIME   = null
    """
    if displayDt is None:
        raise ValueError('Timestamp datetime is None')
    if not isinstance(displayDt, datetime):
        raise ValueError(f'Timestamp must be datetime, got {type(displayDt)}')

    iv = str(interval or '').strip().upper()
    if iv == 'HOUR':
        if Config.periodOffset:
            # EOP: display is end-of-period
            endDt = displayDt
            startDt = displayDt - timedelta(hours=1)
        else:
            # BOP: display is beginning-of-period
            startDt = displayDt
            endDt = displayDt + timedelta(hours=1)
        return startDt, endDt
    return displayDt, None


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
    Build list of dicts ready for DB write from user-edited cells only.
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


# ---------------------------------------------------------------------------
# HDB MODIFY_R_BASE / DELETE_R_BASE write path
# ---------------------------------------------------------------------------

def buildModifyRBaseParams(uploadRow):
    """
    Build positional param list for MODIFY_R_BASE from one upload row.

    Defaults come from Config (AGEN_ID, OVERWRITE_FLAG, DATA_FLAGS, TIME_ZONE
    are designed to become Options-driven later; None → Oracle NULL).
    """
    interval, startDt, endDt, sdid = resolveUploadDateTimes(uploadRow)
    value = parseUploadValue(uploadRow.get('value'))

    # Future Options: overwrite / data flags / time zone / agen
    overwrite = Config.hdbOverwriteFlag
    dataFlags = Config.hdbDataFlags
    timeZone = Config.hdbTimeZone
    agenId = Config.hdbAgenId

    params = [
        sdid,                                   # SITE_DATATYPE_ID
        interval,                               # INTERVAL
        startDt,                                # START_DATE_TIME (or None)
        endDt,                                  # END_DATE_TIME (or None)
        value,                                  # VALUE
        int(agenId),                            # AGEN_ID
        overwrite,                              # OVERWRITE_FLAG (None → NULL)
        str(Config.hdbValidation),              # VALIDATION
        int(Config.hdbCollectionSystemId),      # COLLECTION_SYSTEM_ID
        int(Config.hdbLoadingApplicationId),    # LOADING_APPLICATION_ID
        int(Config.hdbMethodId),                # METHOD_ID
        int(Config.hdbComputationId),           # COMPUTATION_ID
        str(Config.hdbDoUpdateYorN or 'Y'),     # DO_UPDATE_Y_OR_N (always Y for now)
        dataFlags,                              # DATA_FLAGS (None → NULL)
        timeZone,                               # TIME_ZONE (None → NULL)
    ]
    return params


def buildDeleteRBaseParams(uploadRow):
    """
    Build positional param list for DELETE_R_BASE (blank cell edit).

    Inputs (plus SITE_DATATYPE_ID to identify the series — same as MODIFY):
      INTERVAL, START_DATE_TIME, END_DATE_TIME, AGEN_ID, LOADING_APPLICATION_ID

    Date/interval/agen/loading filled with the same helpers as MODIFY_R_BASE.
    """
    interval, startDt, endDt, sdid = resolveUploadDateTimes(uploadRow)
    params = [
        sdid,                                   # SITE_DATATYPE_ID
        interval,                               # INTERVAL
        startDt,                                # START_DATE_TIME
        endDt,                                  # END_DATE_TIME (HOUR always set; else null)
        int(Config.hdbAgenId),                  # AGEN_ID
        int(Config.hdbLoadingApplicationId),    # LOADING_APPLICATION_ID
    ]
    return params


def writeOneHdbValue(oracleConn, uploadRow, threadId=0):
    """
    Call MODIFY_R_BASE (numeric value) or DELETE_R_BASE (blank cell).
    Commit on success (via callproc helper).
    """
    db = uploadRow.get('database', '')
    dsn = databaseToDsn(db)
    blank = isBlankUploadValue(uploadRow.get('value'))

    if blank:
        params = buildDeleteRBaseParams(uploadRow)
        procName = 'DELETE_R_BASE'
        paramNames = list(deleteRBaseParamNames)
        action = 'delete'
    else:
        params = buildModifyRBaseParams(uploadRow)
        procName = 'MODIFY_R_BASE'
        paramNames = list(modifyRBaseParamNames)
        action = 'modify'

    # Stash for summary / debug (mutate copy only if needed by caller)
    uploadRow['hdbAction'] = action

    if Config.debug:
        paired = ', '.join(
            f"{n}={Oracle.oracleConnection._formatParamForLog(v)}"
            for n, v in zip(paramNames, params)
        )
        Logic.logMessage(
            "DEBUG",
            f"Upload.writeOneHdbValue thread={threadId} dsn={dsn} db={db} "
            f"cell=({uploadRow.get('row')},{uploadRow.get('col')}) "
            f"{procName} [{paired}]",
        )

    oracleConn.callStoredProcedureWithRetry(
        procName,
        params=params,
        commit=True,
        paramNames=paramNames,
    )

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"Upload.writeOneHdbValue thread={threadId}: OK {action} "
            f"SDID={params[0]} interval={params[1]} ts={uploadRow.get('timestamp')!r} "
            f"value={uploadRow.get('value')!r}",
        )


def writeHdbRows(uploadRows):
    """
    Write HDB rows via MODIFY_R_BASE (value) or DELETE_R_BASE (blank).

    Separate Oracle connections per database (no DB links on write).
    Within each DB: worker threads each hold one reusable session (like sqlRead).

    Returns (successRows, failedRows) where failedRows entries include 'error'.
    """
    successRows = []
    failedRows = []
    resultLock = threading.Lock()

    if not uploadRows:
        return successRows, failedRows

    byDb = {}
    for row in uploadRows:
        byDb.setdefault(row['database'], []).append(row)

    if Config.debug:
        summary = ', '.join(f"{db}={len(rows)}" for db, rows in sorted(byDb.items()))
        Logic.logMessage(
            "DEBUG",
            f"Upload.writeHdbRows: {len(uploadRows)} row(s) across {len(byDb)} DB(s): {summary}",
        )

    def processDatabase(dbName, rows):
        dsn = databaseToDsn(dbName)
        taskQueue = queue.Queue()
        for r in rows:
            taskQueue.put(r)

        numThreads = min(maxWriteThreads, max(1, len(rows)))
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Upload.writeHdbRows: DB={dbName} dsn={dsn} rows={len(rows)} "
                f"threads={numThreads}",
            )

        workerErrors = []
        workerErrorsLock = threading.Lock()

        def worker(threadId):
            oracleConn = None
            tasksDone = 0
            try:
                if getattr(Oracle, 'authFailureMessage', None):
                    raise Oracle.OracleAuthError(Oracle.authFailureMessage)

                oracleConn = Oracle.oracleConnection(dsn)
                oracleConn.connect()
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"Upload HDB-write worker {threadId} ({dsn}): connection opened",
                    )

                while True:
                    try:
                        row = taskQueue.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        writeOneHdbValue(oracleConn, row, threadId=threadId)
                        with resultLock:
                            successRows.append(row)
                        tasksDone += 1
                    except Exception as e:
                        errText = str(e)
                        Logic.logException(
                            f"Upload HDB-write worker {threadId} ({dsn}) failed "
                            f"SDID={row.get('dataId')} ts={row.get('timestamp')!r} "
                            f"value={row.get('value')!r}",
                            e,
                        )
                        failedEntry = dict(row)
                        failedEntry['error'] = errText
                        with resultLock:
                            failedRows.append(failedEntry)
                        with workerErrorsLock:
                            workerErrors.append(e)
                        if isinstance(e, Oracle.OracleAuthError) or Oracle.isAuthError(e):
                            # Drain remaining tasks as auth failures so they don't hang
                            while True:
                                try:
                                    leftover = taskQueue.get_nowait()
                                except queue.Empty:
                                    break
                                failLeft = dict(leftover)
                                failLeft['error'] = errText
                                with resultLock:
                                    failedRows.append(failLeft)
                                try:
                                    taskQueue.task_done()
                                except Exception:
                                    pass
                            break
                    finally:
                        try:
                            taskQueue.task_done()
                        except Exception:
                            pass
            except Exception as e:
                Logic.logException(
                    f"Upload HDB-write worker {threadId} ({dsn}) failed to start session",
                    e,
                )
                with workerErrorsLock:
                    workerErrors.append(e)
                # Mark all remaining queue items failed
                while True:
                    try:
                        leftover = taskQueue.get_nowait()
                    except queue.Empty:
                        break
                    failLeft = dict(leftover)
                    failLeft['error'] = str(e)
                    with resultLock:
                        failedRows.append(failLeft)
                    try:
                        taskQueue.task_done()
                    except Exception:
                        pass
            finally:
                if oracleConn is not None:
                    try:
                        oracleConn.close()
                    except Exception as e:
                        Logic.logException(
                            f"Upload HDB-write worker {threadId} ({dsn}): close failed",
                            e,
                        )
                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            f"Upload HDB-write worker {threadId} ({dsn}): "
                            f"closed after {tasksDone} success(es)",
                        )

        threads = []
        for i in range(numThreads):
            t = threading.Thread(
                target=worker,
                args=(i,),
                name=f"HDB-write-{dsn}-{i}",
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        if Config.debug and workerErrors:
            Logic.logMessage(
                "WARN",
                f"Upload.writeHdbRows: DB={dbName} finished with "
                f"{len(workerErrors)} worker error(s)",
            )

    # Parallel across databases (each DB has its own connection pool of workers)
    dbThreads = []
    for dbName, rows in byDb.items():
        t = threading.Thread(
            target=processDatabase,
            args=(dbName, rows),
            name=f"HDB-write-db-{databaseToDsn(dbName)}",
        )
        dbThreads.append(t)
        t.start()
    for t in dbThreads:
        t.join()

    Logic.logMessage(
        "INFO",
        f"Upload.writeHdbRows: done — {len(successRows)} ok, {len(failedRows)} failed "
        f"of {len(uploadRows)} total",
    )
    return successRows, failedRows


def markUploaded(mainWindow, uploadRows):
    """After successful write: success colors, clear dirty, update originalText."""
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


# ---------------------------------------------------------------------------
# Background worker + UI entry point
# ---------------------------------------------------------------------------

class uploadSignals(QObject):
    """Signals from background HDB write worker back to the UI thread."""
    finished = pyqtSignal(object)  # result dict
    failed = pyqtSignal(str, bool)  # message, isAuthError


class uploadWorker(QRunnable):
    """Run HDB writes off the UI thread."""

    def __init__(self, hdbRows, signals):
        super().__init__()
        self.hdbRows = hdbRows
        self.signals = signals

    def run(self):
        try:
            successRows, failedRows = writeHdbRows(self.hdbRows)
            self.signals.finished.emit({
                'successRows': successRows,
                'failedRows': failedRows,
            })
        except Exception as e:
            isAuth = False
            try:
                isAuth = isinstance(e, Oracle.OracleAuthError) or Oracle.isAuthError(e)
            except Exception:
                pass
            Logic.logException("Upload.uploadWorker failed", e)
            self.signals.failed.emit(str(e), isAuth)


def _setUploadUiBusy(mainWindow, busy):
    """Disable upload control while a write is in progress."""
    try:
        mainWindow.uploadRunning = bool(busy)
        btn = getattr(mainWindow, 'btnUpload', None)
        if btn is not None:
            btn.setEnabled(not busy)
    except Exception:
        pass


def _finishUploadUi(
    mainWindow,
    hdbSuccessRows,
    failedRows,
    aquariusCount=0,
    otherSkipped=None,
    markHdb=True,
):
    """
    Mark HDB successes teal (if markHdb) and show a summary dialog (UI thread).
    Aquarius cells are marked earlier in runUpload after the stub popup.
    """
    otherSkipped = otherSkipped or []
    hdbSuccessRows = hdbSuccessRows or []
    failedRows = failedRows or []
    try:
        if markHdb and hdbSuccessRows:
            markUploaded(mainWindow, hdbSuccessRows)

        lines = []
        nHdb = len(hdbSuccessRows)
        nFail = len(failedRows)
        nAq = aquariusCount
        nOk = nHdb + nAq

        if nHdb:
            byDb = {}
            byDbDelete = {}
            byDbModify = {}
            for r in hdbSuccessRows:
                db = r['database']
                byDb[db] = byDb.get(db, 0) + 1
                if r.get('hdbAction') == 'delete' or isBlankUploadValue(r.get('value')):
                    byDbDelete[db] = byDbDelete.get(db, 0) + 1
                else:
                    byDbModify[db] = byDbModify.get(db, 0) + 1
            for db in sorted(byDb.keys()):
                nMod = byDbModify.get(db, 0)
                nDel = byDbDelete.get(db, 0)
                parts = []
                if nMod:
                    parts.append(f"{nMod} modified (MODIFY_R_BASE)")
                if nDel:
                    parts.append(f"{nDel} deleted (DELETE_R_BASE)")
                detail = ', '.join(parts) if parts else f"{byDb[db]} value(s)"
                lines.append(f"  {db}: {detail}")

        if nAq:
            lines.append(
                f"  AQUARIUS: {nAq} value(s) marked success "
                f"(write not implemented yet)"
            )

        if nFail:
            lines.append(f"\nFailed ({nFail}):")
            for r in failedRows[:25]:
                lines.append(
                    f"  {r.get('database')} SDID={r.get('dataId')} "
                    f"@ {r.get('timestamp')}: {r.get('error', 'unknown error')}"
                )
            if nFail > 25:
                lines.append(f"  … and {nFail - 25} more (see app.log)")

        if otherSkipped:
            lines.append(f"\nSkipped unsupported ({len(otherSkipped)}):")
            for r in otherSkipped[:10]:
                lines.append(
                    f"  {r.get('database')} dataId={r.get('dataId')} @ {r.get('timestamp')}"
                )

        header = f"Upload finished: {nOk} succeeded"
        if nFail:
            header += f", {nFail} failed"
        body = header + (('\n\n' + '\n'.join(lines)) if lines else '')

        if nFail and nOk == 0:
            QMessageBox.warning(mainWindow, "Upload Failed", body)
        elif nFail:
            QMessageBox.warning(mainWindow, "Upload Partial Success", body)
        else:
            QMessageBox.information(mainWindow, "Upload Complete", body)

        Logic.logMessage("INFO", f"Upload UI summary: {header}")
    except Exception as e:
        Logic.logException("Upload._finishUploadUi failed", e)
        QMessageBox.warning(mainWindow, "Upload Error", f"Upload finished with UI error:\n{e}")


def runUpload(mainWindow):
    """
    btnUpload entry point:
      - Collect user edits
      - HDB (USBR-*): MODIFY_R_BASE for values; DELETE_R_BASE for blank cells
      - Aquarius: popup that write is not implemented, then teal success styling
      - No CSV dry-run
    """
    try:
        table = mainWindow.mainTable
        if table is None or table.rowCount() == 0:
            QMessageBox.information(mainWindow, "Upload", "No data in the table to upload.")
            return

        if getattr(mainWindow, 'uploadRunning', False):
            QMessageBox.information(mainWindow, "Upload", "An upload is already in progress.")
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

        hdbRows = [r for r in uploadRows if isHdbDb(r['database'])]
        aquariusRows = [r for r in uploadRows if isAquariusDb(r['database'])]
        otherRows = [
            r for r in uploadRows
            if not isHdbDb(r['database']) and not isAquariusDb(r['database'])
        ]

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Upload.runUpload: total={len(uploadRows)} hdb={len(hdbRows)} "
                f"aquarius={len(aquariusRows)} other={len(otherRows)} "
                f"periodOffset(EOP)={Config.periodOffset} "
                f"agenId={Config.hdbAgenId} overwrite={Config.hdbOverwriteFlag!r} "
                f"dataFlags={Config.hdbDataFlags!r} timeZone={Config.hdbTimeZone!r}",
            )

        if otherRows:
            for r in otherRows:
                Logic.logMessage(
                    "WARN",
                    f"Upload.runUpload: skipping unsupported database "
                    f"{r.get('database')!r} dataId={r.get('dataId')} ts={r.get('timestamp')}",
                )

        # Aquarius: not implemented — inform user, still apply success styling
        if aquariusRows:
            QMessageBox.information(
                mainWindow,
                "Aquarius Write",
                "Aquarius write hasn't been written into the program yet.",
            )
            markUploaded(mainWindow, aquariusRows)
            Logic.logMessage(
                "INFO",
                f"Upload.runUpload: Aquarius stub — marked {len(aquariusRows)} cell(s) "
                f"as success without writing",
            )

        # Only Aquarius / skipped others — no HDB work
        if not hdbRows:
            if aquariusRows or otherRows:
                _finishUploadUi(
                    mainWindow,
                    hdbSuccessRows=[],
                    failedRows=[],
                    aquariusCount=len(aquariusRows),
                    otherSkipped=otherRows,
                    markHdb=False,
                )
            return

        # HDB write on background thread so UI stays responsive
        _setUploadUiBusy(mainWindow, True)

        signals = uploadSignals()
        # Keep reference so signals aren't GC'd before emit
        mainWindow.uploadSignals = signals
        # Capture for closures (immutable snapshots)
        aquariusCount = len(aquariusRows)
        otherSkipped = list(otherRows)

        def onFinished(result):
            try:
                hdbSuccess = list(result.get('successRows') or [])
                failedRows = list(result.get('failedRows') or [])
                _finishUploadUi(
                    mainWindow,
                    hdbSuccessRows=hdbSuccess,
                    failedRows=failedRows,
                    aquariusCount=aquariusCount,
                    otherSkipped=otherSkipped,
                    markHdb=True,
                )
            finally:
                _setUploadUiBusy(mainWindow, False)

        def onFailed(message, isAuthError):
            try:
                Logic.logMessage("ERROR", f"Upload.runUpload background failed: {message}")
                if isAuthError:
                    QMessageBox.warning(mainWindow, "Oracle Login Failed", message)
                else:
                    QMessageBox.warning(
                        mainWindow,
                        "Upload Error",
                        f"HDB upload failed:\n{message}",
                    )
                if aquariusCount:
                    Logic.logMessage(
                        "INFO",
                        f"Upload.runUpload: HDB failed but {aquariusCount} "
                        f"Aquarius stub cell(s) remain marked success",
                    )
            finally:
                _setUploadUiBusy(mainWindow, False)

        signals.finished.connect(onFinished)
        signals.failed.connect(onFailed)
        worker = uploadWorker(hdbRows, signals)
        QThreadPool.globalInstance().start(worker)

        Logic.logMessage(
            "INFO",
            f"Upload.runUpload: started background HDB write for {len(hdbRows)} value(s)",
        )
    except Exception as e:
        _setUploadUiBusy(mainWindow, False)
        Logic.logException("Upload.runUpload failed", e)
        QMessageBox.warning(mainWindow, "Upload Error", f"Failed to start upload:\n{e}")
