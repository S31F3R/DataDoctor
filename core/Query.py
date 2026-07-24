# Query.py

import queue
import time
from collections import defaultdict
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QCoreApplication, QTimer
from PyQt6.QtGui import QColor, QBrush, QFontMetrics
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QSizePolicy, QProgressDialog
from core import Logic, USBR, USGS, Aquarius, Config, QueryUtils

class sortWorkerSignals(QObject):
    sortDone = pyqtSignal(list, bool)

class sortWorker(QRunnable):
    def __init__(self, rows, col, ascending, byTimestamp=False):
        super().__init__()
        self.signals = sortWorkerSignals()
        self.rows = rows
        self.col = col
        self.ascending = ascending
        self.byTimestamp = byTimestamp

    def run(self):
        try:
            def sortKey(row):
                # row = {'ts': str, 'cells': [cellDict|None, ...]}
                if self.byTimestamp:
                    try:
                        return datetime.strptime(row['ts'], '%m/%d/%y %H:%M:00')
                    except ValueError:
                        return datetime.min
                try:
                    cell = row['cells'][self.col] if self.col < len(row['cells']) else None
                    text = cell['text'] if cell else ''
                    return float(text)
                except (ValueError, TypeError, KeyError):
                    return 0
            self.rows.sort(key=sortKey, reverse=not self.ascending)
            self.signals.sortDone.emit(self.rows, self.ascending)
        except Exception as e:
            Logic.logException("sortWorker.run failed", e)

def captureTableRows(table):
    """Capture row data including formatting so sort/undo preserve overlay and QAQC state."""
    rows = []
    for rowIdx in range(table.rowCount()):
        timestamp = table.verticalHeaderItem(rowIdx).text() if table.verticalHeaderItem(rowIdx) else ''
        cells = []
        for c in range(table.columnCount()):
            item = table.item(rowIdx, c)
            if item:
                cells.append({
                    'text': item.text(),
                    'userData': item.data(Qt.ItemDataRole.UserRole),
                    'bg': item.background(),
                    'fg': item.foreground(),
                    'fgRole': item.data(Qt.ItemDataRole.ForegroundRole),
                    'align': item.textAlignment(),
                })
            else:
                cells.append(None)
        rows.append({'ts': timestamp, 'cells': cells})
    return rows

class queryWorkerSignals(QObject):
    progressSignal = pyqtSignal(int, str)
    resultSignal = pyqtSignal(tuple)

class queryWorker(QRunnable):
    def __init__(self, groupKey, groupItems, signals, startDate, endDate, isInternal, timestamps, defaultBlanks):
        super().__init__()
        self.groupKey = groupKey
        self.groupItems = groupItems
        self.signals = signals
        self.startDate = startDate
        self.endDate = endDate
        self.isInternal = isInternal
        self.timestamps = timestamps
        self.defaultBlanks = defaultBlanks

    def run(self):
        db, _, _ = self.groupKey
        groupResult = {}
        # Aquarius + USGS OGC: labels used for column headers (Site Name / AQ label)
        groupLabels = {} if db in ('AQUARIUS', 'USGS-NWIS') else None
        groupRawResponses = {}  # Always dict to support USBR metadata
        usbrGroups = defaultdict(list)

        try:
            for origIndex, dataID, SDID, itemDb, interval, mrid in self.groupItems:
                usbrGroups[(itemDb, interval, mrid)].append((origIndex, dataID, SDID))
            for (itemDb, interval, mrid), items in usbrGroups.items():
                SDIDs = [item[2] for item in items]
                result = {} # Initialize result here to avoid UnboundLocalError

                if db.startswith('USBR'):
                    try:
                        svr = itemDb.split('-')[1].lower() if '-' in itemDb else 'lchdb'
                        table = 'M' if mrid != '0' else 'R'
                        apiInterval = interval

                        # If internal, switch to sqlRead
                        if self.isInternal:
                            result = USBR.sqlRead(svr, SDIDs, self.startDate, self.endDate, apiInterval, mrid, table)
                        else: # External use apiRead
                            result = USBR.apiRead(svr, SDIDs, self.startDate, self.endDate, apiInterval, mrid, table)
                        
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"queryWorker: USBR result for SDIDs {SDIDs}: {result}")
                    except Exception as e:
                        Logic.logException(f"queryWorker: USBR read failed for SDIDs {SDIDs}", e)
                        result = {}
                elif db == 'AQUARIUS' and self.isInternal:
                    try:
                        result = Aquarius.apiRead(SDIDs, self.startDate, self.endDate, interval)
                        
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"queryWorker: Aquarius result for SDIDs {SDIDs}: {result}")
                    except Exception as e:
                        Logic.logException(f"queryWorker: Aquarius apiRead failed for SDIDs {SDIDs}", e)
                        result = {}
                elif db == 'USGS-NWIS':
                    try:
                        result = USGS.apiRead(SDIDs, interval, self.startDate, self.endDate)

                        if Config.debug:
                            Logic.logMessage("DEBUG", f"queryWorker: USGS result for SDIDs {SDIDs}: {result}")
                    except Exception as e:
                        Logic.logException(f"queryWorker: USGS apiRead failed for SDIDs {SDIDs}", e)
                        result = {}
                else:
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"queryWorker: Unknown db skipped: {db}")
                    continue
                for idx, (origIndex, dataID, SDID) in enumerate(items):
                    if SDID in result and result[SDID]:
                        res = result[SDID]

                        if isinstance(res, dict):
                            outputData = res.get('data', [])
                            if 'rawResponse' in res:
                                groupRawResponses[dataID] = res['rawResponse']
                        else:
                            outputData = res
                            groupRawResponses[dataID] = res # Use full dataID as key for USBR
                        if db == 'AQUARIUS' and groupLabels is not None:
                            groupLabels[dataID] = result.get(SDID, {}).get('label', dataID)

                            if Config.debug:
                                Logic.logMessage("DEBUG", f"queryWorker: Aquarius label for {dataID}: {groupLabels[dataID]}")
                        elif db == 'USGS-NWIS' and groupLabels is not None:
                            # Site Name from OGC series/location meta (public + internal)
                            raw = res.get('rawResponse') if isinstance(res, dict) else None
                            siteName = ''
                            if isinstance(raw, dict):
                                siteName = (raw.get('seriesMeta') or {}).get('Site Name') or ''
                            groupLabels[dataID] = siteName.strip() if siteName else ''

                            if Config.debug:
                                Logic.logMessage("DEBUG", f"queryWorker: USGS Site Name for {dataID}: {groupLabels[dataID]!r}")
                        alignedData = gapCheck(self.timestamps, outputData, dataID)
                        values = [line.split(',')[1] if line else '' for line in alignedData]
                        groupResult[dataID] = values
                    else:
                        groupResult[dataID] = self.defaultBlanks

                        if groupLabels is not None:
                            groupLabels[dataID] = dataID if db == 'AQUARIUS' else ''
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"queryWorker: No data for SDID {SDID} in {db}")
            if Config.debug:
                Logic.logMessage("DEBUG", f"queryWorker: Completed group {self.groupKey} with {len(groupResult)} items")
        except Exception as e:
            Logic.logException(f"queryWorker: Failed for group {self.groupKey}", e)
            for _, dataID, _, _, _, _ in self.groupItems:
                groupResult[dataID] = self.defaultBlanks

                if groupLabels is not None:
                    groupLabels[dataID] = dataID if db == 'AQUARIUS' else ''
        try:
            self.signals.resultSignal.emit((self.groupKey, groupResult, groupLabels, groupRawResponses))
        except Exception as e:
            Logic.logException(f"queryWorker: Failed to emit result for group {self.groupKey}", e)

def buildTimestamps(startDateStr, endDateStr, intervalStr):
    if Config.debug:
        Logic.logMessage("DEBUG", "buildTimestamps called with start: {}, end: {}, interval: {}".format(startDateStr, endDateStr, intervalStr))
    try:
        start = datetime.strptime(startDateStr, '%Y-%m-%d %H:%M')
        end = datetime.strptime(endDateStr, '%Y-%m-%d %H:%M')
    except ValueError as e:
        Logic.logMessage("ERROR", "Invalid date format in buildTimestamps: {}".format(e))
        return []
    if intervalStr == 'HOUR':
        delta = timedelta(hours=1)
        start = start.replace(minute=0, second=0)
    elif intervalStr.startswith('INSTANT:'):
        try:
            minutes = int(intervalStr.split(':')[1])
            delta = timedelta(minutes=minutes)
            start = start.replace(second=0)
            if minutes == 1:
                pass
            elif minutes == 15:
                minute = (start.minute // 15) * 15
                start = start.replace(minute=minute)
            elif minutes == 60:
                start = start.replace(minute=0)
            else:
                Logic.logMessage("ERROR", "Unsupported INSTANT interval: {}".format(intervalStr))
                return []
        except (IndexError, ValueError) as e:
            Logic.logMessage("ERROR", "Invalid INSTANT interval format: {}".format(e))
            return []
    elif intervalStr == 'DAY':
        delta = timedelta(days=1)
        start = start.replace(hour=0, minute=0, second=0)
    else:
        Logic.logMessage("ERROR", "Unknown intervalStr: {}".format(intervalStr))
        return []
    timestamps = []
    current = start
    # Inclusive end so a full-interval end time (e.g. 14:00 on HOUR) is not dropped
    while current <= end:
        ts = current.strftime('%m/%d/%y %H:%M:00')
        timestamps.append(ts)
        current += delta
        if delta.total_seconds() <= 0:
            break
    if Config.debug:
        Logic.logMessage("DEBUG", "Generated {} timestamps, sample first 3: {}".format(len(timestamps), timestamps[:3]))
    return timestamps

def gapCheck(timestamps, data, dataID=''):
    if Config.debug:
        Logic.logMessage("DEBUG", "gapCheck for dataID '{}': timestamps len={}, data len={}".format(dataID, len(timestamps), len(data)))
    if not timestamps:
        return data
    try:
        expectedDateTimes = [datetime.strptime(ts, '%m/%d/%y %H:%M:00') for ts in timestamps]
    except ValueError as e:
        Logic.logMessage("ERROR", "Invalid timestamp format in timestamps: {}".format(e))
        return data
    newData = []
    removed = []
    i = 0
    for expectedDateTime in expectedDateTimes:
        found = False
        while i < len(data):
            line = data[i]
            if not line:
                i += 1
                continue
            parts = line.split(',')
            if len(parts) < 2:                
                Logic.logMessage("WARN", "Malformed data row skipped: '{}' for '{}'".format(line, dataID))
                i += 1
                continue
            actualTimestampStr = parts[0].strip()
            try:
                actualDateTime = datetime.strptime(actualTimestampStr, '%m/%d/%y %H:%M:%S')
            except ValueError:
                Logic.logMessage("WARN", "Invalid ts skipped: '{}' in '{}' for '{}'".format(actualTimestampStr, line, dataID))  
                i += 1
                continue
            if actualDateTime == expectedDateTime:
                if not actualTimestampStr.endswith(':00'):
                    actualTimestampStr = actualDateTime.strftime('%m/%d/%y %H:%M:00')
                    line = actualTimestampStr + ',' + ','.join(parts[1:])
                newData.append(line)
                found = True
                i += 1
                break
            elif actualDateTime < expectedDateTime:
                removed.append(actualTimestampStr)
                i += 1
            else:
                break
        if not found:
            tsStr = expectedDateTime.strftime('%m/%d/%y %H:%M:00')
            newData.append(tsStr + ',')
    while i < len(data):
        line = data[i]
        parts = line.split(',')
        if len(parts) > 0:
            removed.append(parts[0].strip())
        i += 1
    if removed:
        if Config.debug:
            Logic.logMessage("DEBUG", "Removed {} extra/mismatched rows from '{}': ts {}".format(len(removed), dataID, removed))
    if Config.debug:
        Logic.logMessage("DEBUG", "Post-gapCheck len={}, sample first 3: {}".format(len(newData), newData[:3]))
    return newData

def combineParameters(data, newData):
    if len(data) != len(newData):
        return data
    for d in range(len(newData)):
        parseLine = newData[d].split(',')
        data[d] = f'{data[d]},{parseLine[1]}'
    return data

def getDataDictionaryItem(table, dataId, idIndex=None):
    """Find dictionary row for dataId. Prefer idIndex from buildDataDictionaryIndex()."""
    if idIndex is not None:
        return idIndex.get(dataId.strip() if dataId else '', -1)
    idCol = getColByName(table, 'dataID')

    if idCol == -1:
        return -1
    target = dataId.strip() if dataId else ''
    for r in range(table.rowCount()):
        item = table.item(r, idCol)

        if item and item.text().strip() == target:
            return r
    return -1

def buildDataDictionaryIndex(table):
    """
    One-pass map dataID -> row index for O(1) lookups.
    Scanning 40k rows per series column was a major cost on wide queries.
    """
    index = {}
    if table is None:
        return index
    idCol = getColByName(table, 'dataID')
    if idCol == -1:
        return index
    for r in range(table.rowCount()):
        item = table.item(r, idCol)
        if item:
            key = item.text().strip()
            if key and key not in index:
                index[key] = r
    return index

def getColByName(table, name):
    """Find a DataDictionary column by header name (case-insensitive).

    SQLite headers are often lowercase (e.g. datatype); callers may use camelCase (dataType).
    """
    nameLower = name.strip().lower()
    for c in range(table.columnCount()):
        header = table.horizontalHeaderItem(c)

        if header and header.text().strip().lower() == nameLower:
            return c
    if Config.debug:
        Logic.logMessage("DEBUG", f"Available DataDictionary columns: {[table.horizontalHeaderItem(c).text().strip() for c in range(table.columnCount()) if table.horizontalHeaderItem(c)]}")
    Logic.logMessage("WARN", f"Column not found in DataDictionary: {name}")

    return -1

def usgsHeaderFromSiteName(siteName, intervalStr, fallback=None):
    """
    USGS column header from monitoring-location Site Name.
    Split on comma: part 0 = top line, part 1 = bottom line.
    Falls back to None when Site Name is empty so caller can use old logic.
    """
    if not siteName or not str(siteName).strip():
        return None
    parts = [p.strip() for p in str(siteName).split(',') if p.strip()]
    if not parts:
        return None
    if len(parts) >= 2:
        return f"{parts[0]} \n{parts[1]}"
    # Single segment: name on top, interval underneath
    return f"{parts[0]} \n{intervalStr}"

def buildTable(table, data, buildHeader, dataDictionaryTable, intervals, lookupIds=None, labelsDict=None, databases=None, queryItems=None, progressDialog=None):
    if Config.debug:
        Logic.logMessage("DEBUG", "buildTable: Starting with {} rows, {} headers".format(len(data), len(buildHeader)))
    table.clear()

    if not data:
        if Config.debug:
            Logic.logMessage("DEBUG", "buildTable: No data to display.")
        return
    if isinstance(buildHeader, str):
        buildHeader = [h.strip() for h in buildHeader.split(',')]
    processedHeaders = []
    # O(1) dictionary row lookup (40k linear scans per column freezes wide queries)
    dictIndex = buildDataDictionaryIndex(dataDictionaryTable) if dataDictionaryTable else {}

    for i, h in enumerate(buildHeader):
        dataId = h.strip()
        intervalStr = intervals[i].upper()

        if intervalStr.startswith('INSTANT:'):
            intervalStr = 'INSTANT'
        database = databases[i] if databases and i < len(databases) else None
        dictKey = lookupIds[i] if lookupIds else dataId
        dictRow = getDataDictionaryItem(dataDictionaryTable, dictKey, idIndex=dictIndex)
        mrid = None

        if database and database.startswith('USBR-') and '-' in dataId:
            parts = dataId.rsplit('-', 1)
            dataId = parts[0]
            mrid = parts[1] if len(parts) > 1 else '0'
        if dictRow != -1:
            commonCol = getColByName(dataDictionaryTable, 'commonName')
            commonItem = dataDictionaryTable.item(dictRow, commonCol) if commonCol != -1 else None
            baseLabel = commonItem.text().strip() if commonItem else dataId

            if database == 'USGS-NWIS':
                # Prefer live Site Name from API meta (public + internal OGC)
                siteName = labelsDict.get(dataId) if labelsDict else None
                # Also try original header key (buildHeader entry) if dataId was rewritten
                if not siteName and labelsDict and h.strip() in labelsDict:
                    siteName = labelsDict.get(h.strip())
                fullLabel = usgsHeaderFromSiteName(siteName, intervalStr)
                if fullLabel:
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"buildTable: USGS in dict via Site Name, header {i}: {fullLabel}")
                else:
                    parts = dataId.split('-')

                    if len(parts) == 3 and parts[0].isdigit() and (parts[1].isdigit() or (len(parts[1]) == 32 and parts[1].isalnum())) and parts[2].isdigit():
                        fullLabel = f"{parts[0]}-{parts[2]} \n{intervalStr}"

                        if Config.debug:
                            Logic.logMessage("DEBUG", f"buildTable: USGS in dict, header {i}: {fullLabel}")
                    else:
                        fullLabel = f"{baseLabel} \n{intervalStr}"
                        
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"buildTable: USGS in dict but non-USGS format, header {i}: {fullLabel}")
            elif database == 'AQUARIUS':
                fullLabel = f"{baseLabel} \n{dataId}"

                if Config.debug:
                    Logic.logMessage("DEBUG", f"buildTable: Aquarius in dict, using dict label, header {i}: {fullLabel}")
            else:
                # USBR / HDB: commonName - dataType
                dataTypeCol = getColByName(dataDictionaryTable, 'dataType')
                dataTypeItem = dataDictionaryTable.item(dictRow, dataTypeCol) if dataTypeCol != -1 else None
                dataType = dataTypeItem.text().strip() if dataTypeItem and dataTypeItem.text().strip() else ''
                nameLabel = f"{baseLabel} - {dataType}" if dataType else baseLabel

                if mrid and mrid != '0':
                    fullLabel = f"{nameLabel} \n{dataId}-{mrid}"

                    if Config.debug:
                        Logic.logMessage("DEBUG", f"buildTable: USBR in dict with MRID, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{nameLabel} \n{dataId}"

                    if Config.debug:
                        Logic.logMessage("DEBUG", f"buildTable: USBR in dict, header {i}: {fullLabel}")
        else:
            if database == 'USGS-NWIS':
                siteName = labelsDict.get(dataId) if labelsDict else None
                if not siteName and labelsDict and h.strip() in labelsDict:
                    siteName = labelsDict.get(h.strip())
                fullLabel = usgsHeaderFromSiteName(siteName, intervalStr)
                if fullLabel:
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"buildTable: USGS Site Name header {i}: {fullLabel}")
                else:
                    parts = dataId.split('-')

                    if len(parts) == 3 and parts[0].isdigit() and (parts[1].isdigit() or (len(parts[1]) == 32 and parts[1].isalnum())) and parts[2].isdigit():
                        fullLabel = f"{parts[0]}-{parts[2]} \n{intervalStr}"

                        if Config.debug:
                            Logic.logMessage("DEBUG", f"buildTable: Parsed USGS header {i}: {fullLabel}")
                    else:
                        fullLabel = f"{dataId} \n{intervalStr}"

                        if Config.debug:
                            Logic.logMessage("DEBUG", f"buildTable: USGS not in dict, header {i}: {fullLabel}")
            elif database == 'AQUARIUS' and labelsDict and dataId in labelsDict:
                apiFull = labelsDict[dataId]
                parts = apiFull.split('\n')
                label = parts[0].strip() if len(parts) >= 1 else dataId
                location = parts[1].strip() if len(parts) >= 2 else dataId
                fullLabel = f"{label} \n{location}"

                if Config.debug:
                    Logic.logMessage("DEBUG", f"buildTable: Aquarius not in dict, using API label, header {i}: {fullLabel}")
            else:
                if mrid and mrid != '0':
                    fullLabel = f"{dataId}-{mrid} \n{intervalStr}"

                    if Config.debug:
                        Logic.logMessage("DEBUG", f"buildTable: USBR not in dict with MRID, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{dataId} \n{intervalStr}"

                    if Config.debug:
                        Logic.logMessage("DEBUG", f"buildTable: USBR not in dict, header {i}: {fullLabel}")
        processedHeaders.append(fullLabel)
    headers = processedHeaders
    skipDateCol = dataDictionaryTable is not None
    numCols = len(headers)
    numRows = len(data)
    totalCells = numRows * numCols

    if Config.debug:
        Logic.logMessage("DEBUG", f"buildTable: Setting table to {numRows} rows, {numCols} columns ({totalCells} cells)")

    # Freeze UI work before allocating — Windows marks Not Responding if this blocks too long
    wasSorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.blockSignals(True)
    table.setUpdatesEnabled(False)

    table.setRowCount(numRows)
    table.setColumnCount(numCols)
    table.setHorizontalHeaderLabels(headers)
    table.show()

    header = table.horizontalHeader()
    vHeader = table.verticalHeader()
    # NEVER ResizeToContents on large tables — Qt walks every row (multi-minute freeze)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    vHeader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    timestamps = []
    if dataDictionaryTable:
        timestamps = [row.split(',', 1)[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        vHeader.setVisible(True)
        # Fixed min width from sample only (not ResizeToContents)
        font = table.font()
        metrics = QFontMetrics(font)
        sampleTs = timestamps[0] if timestamps else "01/01/26 00:00:00"
        vHeader.setMinimumWidth(max(120, metrics.horizontalAdvance(sampleTs) + 16))
    else:
        table.verticalHeader().setVisible(False)
        font = table.font()
        metrics = QFontMetrics(font)

    columnWidths = []
    sampleRows = min(100, numRows)  # small sample; width does not need full scan
    sampleSplit = []
    for row in data[:sampleRows]:
        parts = row.split(',')
        sampleSplit.append(parts[1:] if skipDateCol and len(parts) > 1 else parts)

    for c in range(numCols):
        nonEmptyValues = []
        for parts in sampleSplit:
            if c < len(parts):
                val = parts[c].strip()
                if val:
                    nonEmptyValues.append(val)
        if nonEmptyValues:
            maxCellWidth = max(metrics.horizontalAdvance(val) for val in nonEmptyValues)
        else:
            maxCellWidth = metrics.horizontalAdvance("0.00")
        headerLines = headers[c].split('\n')
        headerWidth = max(metrics.horizontalAdvance(line.strip()) for line in headerLines) if headerLines else 0
        finalWidth = max(maxCellWidth, headerWidth)
        if headerWidth > maxCellWidth:
            finalWidth = maxCellWidth + (headerWidth - maxCellWidth) + 10
        else:
            finalWidth += 20
        columnWidths.append(finalWidth)

    if Config.debug:
        Logic.logMessage("DEBUG", "buildTable: Disabled updates+sorting+signals for population")

    align = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
    rawData = Config.rawData
    # Yield often enough that Windows does not show "Not Responding"
    yieldEvery = 200 if totalCells > 200000 else 500 if numRows > 2000 else 1000
    progressBase = 90
    progressSpan = 8  # 90–98 during cell fill

    for rowIdx, rowStr in enumerate(data):
        # split once on first comma for ts already used; cells after first comma
        if skipDateCol:
            comma = rowStr.find(',')
            rowData = rowStr[comma + 1:].split(',') if comma >= 0 else []
        else:
            rowData = rowStr.split(',')

        for colIdx in range(min(numCols, len(rowData))):
            cellText = rowData[colIdx].strip() if colIdx < len(rowData) else ''
            if not rawData and cellText:
                display = Logic.valuePrecision(cellText)
            else:
                display = cellText
            item = QTableWidgetItem(display)
            item.setTextAlignment(align)
            table.setItem(rowIdx, colIdx, item)

        if rowIdx % yieldEvery == 0 or rowIdx == numRows - 1:
            if progressDialog is not None:
                pct = progressBase + int(progressSpan * (rowIdx + 1) / max(numRows, 1))
                progressDialog.setLabelText(
                    f"Building table... ({rowIdx + 1}/{numRows} rows, {numCols} cols)"
                )
                progressDialog.setValue(min(pct, 98))
                progressDialog.repaint()
            # Keep table updates OFF — re-enabling mid-fill forces expensive paints
            QCoreApplication.processEvents()
            if progressDialog is not None and progressDialog.wasCanceled():
                break

    for c in range(numCols):
        table.setColumnWidth(c, columnWidths[c])

    rowHeight = metrics.height() + 10
    adjustedRowHeight = max(rowHeight, metrics.height() + 2)
    vHeader.setDefaultSectionSize(adjustedRowHeight)

    table.blockSignals(False)
    table.setUpdatesEnabled(True)
    # Leave sorting off for very large tables (click-to-sort still works via customSort)
    if totalCells < 100000:
        table.setSortingEnabled(wasSorting)
    else:
        table.setSortingEnabled(False)

    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setMinimumSize(0, 0)
    table.horizontalScrollBar().setValue(0)

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"buildTable: Population done. cells={totalCells}, sortEnabled={table.isSortingEnabled()}"
        )

    # QAQC is applied by executeQuery after overlay/delta modifyTable so we do not
    # color twice on huge tables. dictIndex available on table for reuse if needed.
    table._dataDictIndex = dictIndex  # lightweight attach for executeQuery

    if Config.debug:
        Logic.logMessage("DEBUG", "buildTable: complete (QAQC deferred to executeQuery)")

def qaqc(table, dataDictionaryTable, lookupIds, dictIndex=None, progressDialog=None):
    if not Config.qaqcEnabled:
        if Config.debug:
            Logic.logMessage("DEBUG", "qaqc: Skipped, QAQC disabled in config")
        # Do NOT walk every cell to clear backgrounds — empty default is fine and
        # was a multi-minute no-op on million-cell tables.
        return

    if dictIndex is None and dataDictionaryTable is not None:
        dictIndex = buildDataDictionaryIndex(dataDictionaryTable)

    # Column indices once (not 5× getColByName per series column)
    expectedMinCol = getColByName(dataDictionaryTable, 'expectedMin') if dataDictionaryTable else -1
    expectedMaxCol = getColByName(dataDictionaryTable, 'expectedMax') if dataDictionaryTable else -1
    cutoffMinCol = getColByName(dataDictionaryTable, 'cuttoffMin') if dataDictionaryTable else -1
    cutoffMaxCol = getColByName(dataDictionaryTable, 'cutoffMax') if dataDictionaryTable else -1
    rateOfChangeCol = getColByName(dataDictionaryTable, 'rateOfChange') if dataDictionaryTable else -1

    now = datetime.now()
    numCols = min(table.columnCount(), len(lookupIds) if lookupIds is not None else table.columnCount())
    numRows = table.rowCount()
    blackBrush = QBrush(QColor(0, 0, 0))
    blueMissing = QColor(100, 195, 247)

    table.setUpdatesEnabled(False)
    table.blockSignals(True)

    for col in range(numCols):
        lookupId = lookupIds[col] if lookupIds is not None and col < len(lookupIds) else None
        if Config.debug:
            Logic.logMessage("DEBUG", "qaqc: Processing column {} for lookupId {}".format(col, lookupId))
        rowIndex = getDataDictionaryItem(dataDictionaryTable, lookupId, idIndex=dictIndex) if lookupId is not None else -1
        expectedMin = None
        expectedMax = None
        cutoffMin = None
        cutoffMax = None
        rateOfChange = None

        if rowIndex != -1 and dataDictionaryTable is not None:
            def _floatAt(r, c):
                if c == -1:
                    return None
                it = dataDictionaryTable.item(r, c)
                if not it or not it.text().strip():
                    return None
                try:
                    return float(it.text().strip())
                except ValueError:
                    return None
            expectedMin = _floatAt(rowIndex, expectedMinCol)
            expectedMax = _floatAt(rowIndex, expectedMaxCol)
            cutoffMin = _floatAt(rowIndex, cutoffMinCol)
            cutoffMax = _floatAt(rowIndex, cutoffMaxCol)
            rateOfChange = _floatAt(rowIndex, rateOfChangeCol)

        prevVal = None
        for r in range(numRows):
            item = table.item(r, col)

            if not item:
                continue
            cellText = item.text().strip()

            if cellText == '':
                tsItem = table.verticalHeaderItem(r)

                if tsItem:
                    tsStr = tsItem.text()
                    try:
                        tsDt = datetime.strptime(tsStr, '%m/%d/%y %H:%M:00')
                        if tsDt <= now:
                            item.setBackground(blueMissing)
                    except ValueError:
                        pass
                continue
            try:
                val = float(cellText)
            except ValueError:
                continue
            if rowIndex != -1:
                if expectedMin is not None and val < expectedMin:
                    item.setBackground(QColor(249, 240, 107))
                    item.setData(Qt.ItemDataRole.ForegroundRole, blackBrush)
                elif expectedMax is not None and val > expectedMax:
                    item.setBackground(QColor(249, 194, 17))
                    item.setData(Qt.ItemDataRole.ForegroundRole, blackBrush)
                elif cutoffMin is not None and val < cutoffMin:
                    item.setBackground(QColor(255, 163, 72))
                elif cutoffMax is not None and val > cutoffMax:
                    item.setBackground(QColor(192, 28, 40))
            if rateOfChange is not None and prevVal is not None:
                if abs(val - prevVal) > rateOfChange:
                    item.setBackground(QColor(246, 97, 81))
            if prevVal is not None and val == prevVal:
                item.setBackground(QColor(87, 227, 137))
                item.setData(Qt.ItemDataRole.ForegroundRole, blackBrush)
            prevVal = val

        if progressDialog is not None and (col % 5 == 0 or col == numCols - 1):
            progressDialog.setLabelText(f"Applying QAQC colors... ({col + 1}/{numCols} series)")
            progressDialog.setValue(98)
            progressDialog.repaint()
            QCoreApplication.processEvents()

        if Config.debug:
            Logic.logMessage("DEBUG", "qaqc: Processed column {} for lookupId {}".format(col, lookupId))

    table.blockSignals(False)
    table.setUpdatesEnabled(True)

def customSortTable(table, col, dataDictionaryTable):
    try:
        pool = QThreadPool.globalInstance()

        if pool.activeThreadCount() > 0:
            return
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = table.horizontalHeader()
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

        if col not in Config.sortState:
            Config.sortState[col] = True
        else:
            Config.sortState[col] = not Config.sortState[col]
        ascending = Config.sortState[col]
        rows = captureTableRows(table)
        worker = sortWorker(rows, col, ascending, byTimestamp=False)
        worker.signals.sortDone.connect(lambda sortedRows, asc: updateTableAfterSort(table, sortedRows, asc, dataDictionaryTable, col))
        pool.start(worker)
        header.setSortIndicator(col, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)
    except Exception as e:
        Logic.logException(f"customSortTable failed for col {col}", e)
        try:
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        except Exception:
            pass

def updateTableAfterSort(table, sortedRows, ascending, dataDictionaryTable, col):
    """Restore rows after sort, preserving cell UserRole and colors (overlay / QAQC)."""
    try:
        table.setSortingEnabled(False)

        for rowIdx, row in enumerate(sortedRows):
            table.setVerticalHeaderItem(rowIdx, QTableWidgetItem(row['ts']))
            cells = row.get('cells', [])

            for c in range(table.columnCount()):
                cell = cells[c] if c < len(cells) else None

                if cell is None:
                    table.setItem(rowIdx, c, None)
                    continue
                item = QTableWidgetItem(cell.get('text', ''))
                align = cell.get('align')
                if align is not None:
                    item.setTextAlignment(align)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                userData = cell.get('userData')
                if userData is not None:
                    item.setData(Qt.ItemDataRole.UserRole, userData)
                bg = cell.get('bg')
                if bg is not None:
                    item.setBackground(bg)
                fg = cell.get('fg')
                if fg is not None:
                    item.setForeground(fg)
                fgRole = cell.get('fgRole')
                if fgRole is not None:
                    item.setData(Qt.ItemDataRole.ForegroundRole, fgRole)
                table.setItem(rowIdx, c, item)
        if Config.debug:
            Logic.logMessage("DEBUG", "Updated table after sort; preserved cell formatting and UserRole data.")
    except Exception as e:
        Logic.logException("updateTableAfterSort failed", e)
    finally:
        try:
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        except Exception:
            pass

def timestampSortTable(table, dataDictionaryTable):
    try:
        if Config.debug:
            Logic.logMessage("DEBUG", "timestampSortTable: Starting sort by timestamps.")
        pool = QThreadPool.globalInstance()

        if pool.activeThreadCount() > 0:
            return
        rows = captureTableRows(table)
        worker = sortWorker(rows, -1, True, byTimestamp=True)
        worker.signals.sortDone.connect(lambda sortedRows, asc: updateTableAfterSort(table, sortedRows, asc, dataDictionaryTable, -1))
        pool.start(worker)

        if Config.debug:
            Logic.logMessage("DEBUG", "Timestamp sort worker started.")
    except Exception as e:
        Logic.logException("timestampSortTable failed", e)

def executeQuery(mainWindow, queryItems, startDate, endDate, isInternal, dataDictionaryTable, deltaChecked=False, overlayChecked=False):
    progressDialog = None
    try:
        Config.deltaChecked = deltaChecked
        Config.overlayChecked = overlayChecked

        if Config.debug:
            Logic.logMessage("DEBUG", "executeQuery: isInternal={}, items={}, deltaChecked={}, overlayChecked={}".format(isInternal, len(queryItems), deltaChecked, overlayChecked))
        if not isInternal:
            queryItems = [item for item in queryItems if item[2] != 'AQUARIUS']
        if Config.debug:
            Logic.logMessage("DEBUG", "executeQuery: Filtered AQUARIUS for public query, remaining items={}".format(len(queryItems)))
        if not queryItems:
            QMessageBox.warning(mainWindow, "No Valid Items", "No valid query items (AQUARIUS not allowed in public queries).")

            if Config.debug:
                Logic.logMessage("DEBUG", "executeQuery: No valid items after filtering, aborting")
            return
        progressDialog = QProgressDialog(f"Querying data... (0/{len(set(item[2] for item in queryItems))} complete)", "Cancel", 0, 100, mainWindow)
        progressDialog.setWindowModality(Qt.WindowModality.WindowModal)
        progressDialog.setAutoReset(False)
        progressDialog.setAutoClose(False)
        progressDialog.setFixedSize(400, 100)
        progressDialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.MSWindowsFixedSizeDialogHint)
        progressDialog.show()
        progressDialog.setValue(10)
        progressDialog.repaint()

        if Config.debug:
            Logic.logMessage("DEBUG", "executeQuery: Initialized and showed progress dialog")

        # Convert to datetime for rounding if necessary
        if not isinstance(startDate, datetime):
            startDate = datetime.strptime(startDate, '%Y-%m-%d %H:%M')
        if not isinstance(endDate, datetime):
            endDate = datetime.strptime(endDate, '%Y-%m-%d %H:%M')
        if Config.debug:
            Logic.logMessage("DEBUG", f"executeQuery: Ensured dates are datetime for rounding: start={startDate}, end={endDate}")
        queryItems.sort(key=lambda x: x[4])
        firstInterval = queryItems[0][1]
        firstDb = queryItems[0][2]

        if firstInterval == 'INSTANT':
            if firstDb.startswith('USBR-'):
                firstInterval = 'INSTANT:60'
            elif firstDb == 'USGS-NWIS':
                firstInterval = 'INSTANT:15'
            elif firstDb == 'AQUARIUS':
                firstInterval = 'INSTANT:1'

        # Round down startDate to nearest firstInterval
        startDate = roundDownToInterval(startDate, firstInterval)

        # Convert back to str for buildTimestamps
        startDateStr = startDate.strftime('%Y-%m-%d %H:%M')
        endDateStr = endDate.strftime('%Y-%m-%d %H:%M')
        timestamps = buildTimestamps(startDateStr, endDateStr, firstInterval)

        if not timestamps:
            progressDialog.cancel()
            QMessageBox.warning(mainWindow, "Date Error", "Invalid dates or interval.")
            return
        progressDialog.setValue(20)
        progressDialog.repaint()
        QCoreApplication.processEvents()

        if Config.debug:
            Logic.logMessage("DEBUG", "executeQuery: Setup complete, progress at 20%")
        defaultBlanks = [''] * len(timestamps)
        labelsDict = {} # Always dict, populated only if isInternal
        groups = defaultdict(list)

        for dataID, interval, db, mrid, origIndex in queryItems:
            if interval == 'INSTANT':
                if db.startswith('USBR-'):
                    interval = 'INSTANT:60'
                elif db == 'USGS-NWIS':
                    interval = 'INSTANT:15'
                elif db == 'AQUARIUS':
                    interval = 'INSTANT:1'
            groupKey = (db.split('-')[0] if db.startswith('USBR-') else db, None, None)
            baseDataID = dataID.split('-')[0] if db.startswith('USBR-') and '-' in dataID else dataID
            groups[groupKey].append((origIndex, dataID, baseDataID, db, interval, mrid))
        pool = QThreadPool.globalInstance()
        resultQueue = queue.Queue()
        maxDbThreads = 3
        numGroups = len(groups)
        numThreads = min(maxDbThreads, numGroups)

        if Config.debug:
            Logic.logMessage("DEBUG", f"Starting {numThreads} threads for {numGroups} groups in background")
        threadsStarted = 0
        valueDict = {}
        rawResponses = {}
        collected = 0
        processedGroups = set()

        def handleResult(result):
            nonlocal collected
            groupKey, groupResult, groupLabels, groupRawResponses = result

            if groupKey in processedGroups:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"executeQuery: Duplicate group {groupKey}, skipping")
                return
            processedGroups.add(groupKey)

            # Always keep rawResponses + labels (Site Name headers) even when values blank
            if groupRawResponses:
                rawResponses.update(groupRawResponses)
            if groupLabels and labelsDict is not None:
                labelsDict.update(groupLabels)

                if Config.debug:
                    Logic.logMessage("DEBUG", f"executeQuery: Updated labelsDict with {list(groupLabels.keys())}")

            if all(all(v == '' for v in values) for values in groupResult.values()):
                if Config.debug:
                    Logic.logMessage("DEBUG", f"executeQuery: Skipping empty group {groupKey}, no data (meta keys kept: {list(groupRawResponses.keys()) if groupRawResponses else []})")
                collected += 1

                if not progressDialog.wasCanceled():
                    progressDialog.setValue(20 + int(50 * collected / numGroups))
                    progressDialog.setLabelText(f"Completed {groupKey[0]} query ({collected}/{numGroups})")
                    progressDialog.repaint()
                    QCoreApplication.processEvents()
                return
            valueDict.update(groupResult)
            collected += 1

            if Config.debug:
                Logic.logMessage("DEBUG", f"executeQuery: Collected results for group {groupKey} with {len(groupResult)} items ({collected}/{numGroups})")
            if not progressDialog.wasCanceled():
                progressDialog.setValue(20 + int(50 * collected / numGroups))
                progressDialog.setLabelText(f"Completed {groupKey[0]} query ({collected}/{numGroups})")
                progressDialog.repaint()
                QCoreApplication.processEvents()
        for i, groupKey in enumerate(groups.keys()):
            signals = queryWorkerSignals()

            # Pass str dates to queryWorker if it expects str; assuming it does based on original
            worker = queryWorker(groupKey, groups[groupKey], signals, startDateStr, endDateStr, isInternal, timestamps, defaultBlanks)
            signals.resultSignal.connect(lambda result, i=i: [Logic.logMessage("DEBUG", f"executeQuery: Signal received for group {result[0]}") if Config.debug else None, resultQueue.put(result), handleResult(result)][-1])
            pool.start(worker)
            threadsStarted += 1

            if Config.debug:
                Logic.logMessage("DEBUG", f"Started background worker {i} for group {groupKey}")
        if not progressDialog.wasCanceled():
            progressDialog.setLabelText(f"Querying data... (0/{numGroups} complete)")
            progressDialog.repaint()
        timeoutSeconds = 600
        startTime = time.time()
        timer = QTimer()
        timer.setSingleShot(False)

        def checkQueueAndProgress():
            nonlocal collected
            elapsed = time.time() - startTime

            if collected >= numGroups and resultQueue.empty() and pool.activeThreadCount() == 0 or elapsed > timeoutSeconds:
                timer.stop()

                if elapsed > timeoutSeconds:
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"executeQuery: Timeout after {timeoutSeconds} seconds, collected {collected}/{numGroups}")      
                    Logic.logMessage("WARN", f"Query timeout after {timeoutSeconds} seconds; some data may be missing")
                    progressDialog.cancel()
                    QMessageBox.warning(mainWindow, "Query Timeout", "Query timed out; some data may be missing.")
                return
            if not progressDialog.wasCanceled():
                while not resultQueue.empty():
                    try:
                        result = resultQueue.get_nowait()

                        if Config.debug:
                            Logic.logMessage("DEBUG", f"executeQuery: Retrieved result from queue: {result[0]}")
                        handleResult(result)
                    except queue.Empty:
                        break
                progressDialog.setLabelText(f"Querying data... ({collected}/{numGroups} complete)")
                progressDialog.repaint()
                QCoreApplication.processEvents()
        timer.timeout.connect(checkQueueAndProgress)
        timer.start(100)

        if Config.debug:
            Logic.logMessage("DEBUG", "executeQuery: Started timer for progress updates")
        while (collected < numGroups or not resultQueue.empty() or pool.activeThreadCount() > 0) and not progressDialog.wasCanceled():
            time.sleep(0.05)
            QCoreApplication.processEvents()
        if collected >= numGroups:
            while not resultQueue.empty():
                try:
                    result = resultQueue.get_nowait()

                    if Config.debug:
                        Logic.logMessage("DEBUG", f"executeQuery: Processed extra queued result, collected {collected}/{numGroups}, queue size {resultQueue.qsize()}")
                    handleResult(result)
                except queue.Empty:
                    break
            maxRetries = 5
            retryCount = 0

            while not resultQueue.empty() and retryCount < maxRetries:
                try:
                    result = resultQueue.get_nowait()

                    if Config.debug:
                        Logic.logMessage("DEBUG", f"executeQuery: Processed final queued result, collected {collected}/{numGroups}, queue size {resultQueue.qsize()}")
                    handleResult(result)
                except queue.Empty:
                    break
                retryCount += 1
            if retryCount >= maxRetries:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"executeQuery: Max retries ({maxRetries}) reached for final queue flush, queue size {resultQueue.qsize()}")
        timer.stop()

        if Config.debug:
            Logic.logMessage("DEBUG", f"executeQuery: Timer stopped, wait loop ended, final collected {collected}/{numGroups}, queue size {resultQueue.qsize()}, active threads {pool.activeThreadCount()}")
        QCoreApplication.processEvents()

        if progressDialog.wasCanceled():
            if Config.debug:
                Logic.logMessage("DEBUG", f"executeQuery: User canceled via progress dialog")
            progressDialog.cancel()
            return
        if Config.debug:
            Logic.logMessage("DEBUG", f"executeQuery: All {collected} groups merged")
        progressDialog.setLabelText("Merging results...")
        progressDialog.setValue(70)
        progressDialog.repaint()
        QCoreApplication.processEvents()

        for dataID, _, _, _, _ in queryItems:
            if dataID not in valueDict:
                valueDict[dataID] = defaultBlanks

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Added empty result for dataID {dataID}")
        originalDataIds = [item[0] for item in queryItems]
        originalIntervals = [item[1] for item in queryItems]
        databases = [item[2] for item in queryItems]
        lookupIds = [item[0].split('-')[0] if item[2].startswith('USBR-') and '-' in item[0] else item[0] for item in queryItems]
        data = []
        numTs = len(timestamps)
        # Progress/UI yield cadence — every 10 rows + per-row debug made huge tables look hung
        progressEvery = 500 if numTs > 2000 else 100 if numTs > 200 else 25

        for r in range(numTs):
            rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
            data.append("{},{}".format(timestamps[r], ','.join(rowValues)))

            if r % progressEvery == 0 or r == numTs - 1:
                progressDialog.setLabelText(f"Building rows... ({r + 1}/{numTs} rows)")
                progressDialog.setValue(70 + int(20 * (r + 1) / max(numTs, 1)))
                progressDialog.repaint()
                QCoreApplication.processEvents()
                if Config.debug and (r % max(progressEvery * 5, 1) == 0 or r == numTs - 1):
                    Logic.logMessage("DEBUG", f"executeQuery: Building row {r + 1}/{numTs}")
        if Config.debug:
            Logic.logMessage("DEBUG", f"executeQuery: Built {len(data)} rows for table")
        if not progressDialog.wasCanceled():
            progressDialog.setLabelText("Building table...")
            progressDialog.setValue(90)
            progressDialog.repaint()
            QCoreApplication.processEvents()
            mainWindow.mainTable.clear()
            mainWindow.mainTable.setRowCount(0)
            mainWindow.mainTable.setColumnCount(0) # Fully reset table to prevent freeze on column count change
            QCoreApplication.processEvents() # Ensure UI refresh after reset

            # Add tab before building table
            if mainWindow.tabWidget.indexOf(mainWindow.tabMain) == -1:
                mainWindow.tabWidget.addTab(mainWindow.tabMain, 'Data Query')

            # Build the table (progress yields so Windows does not show Not Responding)
            buildTable(
                mainWindow.mainTable,
                data,
                originalDataIds,
                dataDictionaryTable,
                originalIntervals,
                lookupIds,
                labelsDict,
                databases,
                queryItems=queryItems,
                progressDialog=progressDialog,
            )
            if progressDialog.wasCanceled():
                if Config.debug:
                    Logic.logMessage("DEBUG", "executeQuery: canceled during buildTable")
                return

            # Remap Aquarius rawResponses keys to API labels. USGS stays keyed by DataID
            # so context-menu lookup by lookupId still works after Site Name headers.
            if Config.debug:
                Logic.logMessage("DEBUG", f"executeQuery: Remapping rawResponses keys, labelsDict type={type(labelsDict)}, keys={list(labelsDict.keys()) if labelsDict else []}")
            if labelsDict:
                remapped = {}
                for k, v in rawResponses.items():
                    isUsgsMeta = isinstance(v, dict) and (v.get('kind') in ('ogc', 'legacy') or 'seriesMeta' in v)
                    if isUsgsMeta:
                        remapped[k] = v
                    else:
                        remapped[labelsDict.get(k, k)] = v
                rawResponses = remapped

            # Store rawResponses for details / context menu
            mainWindow.storeQueryData(rawResponses, 'internal' if isInternal else 'public')

            if Config.debug:
                Logic.logMessage("DEBUG", f"Stored {len(rawResponses)} rawResponses for Aquarius")

            # Modify table if query tools are checked
            if deltaChecked or overlayChecked:
                if progressDialog is not None:
                    progressDialog.setLabelText("Applying overlay/delta...")
                    progressDialog.setValue(97)
                    progressDialog.repaint()
                    QCoreApplication.processEvents()
                QueryUtils.modifyTable(
                    mainWindow.mainTable,
                    deltaChecked,
                    overlayChecked,
                    databases,
                    queryItems,
                    labelsDict,
                    lookupIds,
                    mainWindow=mainWindow,
                    progressDialog=progressDialog,
                )

                # QAQC on final displayed columns, then overlay color overrides (mismatch / missing only)
                finalLookupIds = []
                for meta in getattr(mainWindow, 'columnMetadata', []) or []:
                    lid = meta.get('lookupId')
                    if isinstance(lid, list):
                        # Overlay/delta: QAQC against primary series rules
                        finalLookupIds.append(lid[0] if lid else '')
                    else:
                        finalLookupIds.append(lid if lid is not None else '')

                if Config.qaqcEnabled and finalLookupIds:
                    if progressDialog is not None:
                        progressDialog.setLabelText("Applying QAQC colors...")
                        progressDialog.setValue(98)
                        progressDialog.repaint()
                        QCoreApplication.processEvents()
                    dictIndex = getattr(mainWindow.mainTable, '_dataDictIndex', None)
                    qaqc(
                        mainWindow.mainTable,
                        dataDictionaryTable,
                        finalLookupIds,
                        dictIndex=dictIndex,
                        progressDialog=progressDialog,
                    )
                if overlayChecked:
                    if progressDialog is not None:
                        progressDialog.setLabelText("Applying overlay colors...")
                        progressDialog.setValue(99)
                        progressDialog.repaint()
                        QCoreApplication.processEvents()
                    QueryUtils.applyOverlayColorOverrides(
                        mainWindow.mainTable, progressDialog=progressDialog
                    )
            else:    
                mainWindow.columnMetadata = []
                mergedDataIds = [[id] for id in originalDataIds] # Derived from originalDataIds
                mergedDbs = [[db] for db in databases] # List for consistency
                mergedQueryInfos = [[f"{item[0]}|{item[1]}|{item[2]}"] for item in queryItems] # List of lists
                mergedHeaders = originalDataIds # Or processedHeaders if set earlier

                for col in range(len(mergedHeaders)):  
                    dataId = mergedDataIds[col][0] if mergedDataIds[col] else None
                    db = mergedDbs[col][0]
                    lookupId = labelsDict.get(dataId, dataId) if db == 'AQUARIUS' else dataId
                    metadata = {
                        'type': 'normal',
                        'dataIds': mergedDataIds[col], 
                        'dbs': mergedDbs[col], 
                        'queryInfos': mergedQueryInfos[col], 
                        'lookupId': lookupId  
                    }

                    mainWindow.columnMetadata.append(metadata)

                if Config.debug:
                    Logic.logMessage("DEBUG", "executeQuery: Set columnMetadata for non-overlay with lists: {repr(mainWindow.columnMetadata)}")

                # QAQC once on final columns (not inside buildTable)
                if Config.qaqcEnabled:
                    if progressDialog is not None:
                        progressDialog.setLabelText("Applying QAQC colors...")
                        progressDialog.setValue(98)
                        progressDialog.repaint()
                        QCoreApplication.processEvents()
                    dictIndex = getattr(mainWindow.mainTable, '_dataDictIndex', None)
                    qaqc(
                        mainWindow.mainTable,
                        dataDictionaryTable,
                        lookupIds,
                        dictIndex=dictIndex,
                        progressDialog=progressDialog,
                    )

            # After QAQC/overlay: blue box + black text for HDB r_base fills (no interval)
            if progressDialog is not None:
                progressDialog.setLabelText("Applying HDB r_base colors...")
                progressDialog.setValue(99)
                progressDialog.repaint()
                QCoreApplication.processEvents()
            QueryUtils.applyUsbrRbaseFallbackColors(
                mainWindow.mainTable, mainWindow, progressDialog=progressDialog
            )

            progressDialog.setValue(100)
            progressDialog.repaint()
            QCoreApplication.processEvents()
        if Config.debug:
            Logic.logMessage("DEBUG", f"executeQuery: Table built, progress dialog completed")
        if progressDialog.wasCanceled():
            if Config.debug:
                Logic.logMessage("DEBUG", f"executeQuery: User canceled during table building")
            progressDialog.cancel()
            return
        if mainWindow.tabWidget.indexOf(mainWindow.tabMain) == -1:
            mainWindow.tabWidget.addTab(mainWindow.tabMain, 'Data Query')
        if Config.debug:
            Logic.logMessage("DEBUG", "Query executed and table updated.")

        # Store last delta and overlay states for refresh using globals
        Config.lastDeltaChecked = deltaChecked
        Config.lastOverlayChecked = overlayChecked

        if Config.debug:
            Logic.logMessage("DEBUG", f"executeQuery: Stored lastDeltaChecked={deltaChecked}, lastOverlayChecked={overlayChecked}")
        progressDialog.cancel()

        # Show Data Query tab at index 0, moving if necessary
        index = mainWindow.tabWidget.indexOf(mainWindow.tabMain)

        if Config.debug:
            Logic.logMessage("DEBUG", f"tabMain index during executeQuery: {index}")
        if index != 0:
            if index != -1:
                mainWindow.tabWidget.removeTab(index)

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Removed tabMain from index {index} to move to 0")
            mainWindow.tabWidget.insertTab(0, mainWindow.tabMain, mainWindow.dataQueryTitle)
            mainWindow.tabWidget.setCurrentIndex(0)

            if Config.debug:
                Logic.logMessage("DEBUG", "Inserted tabMain at index 0 after query")
        QCoreApplication.processEvents()

    except Exception as e:
        Logic.logException("executeQuery failed", e)
        try:
            from core.Oracle import OracleAuthError
            title = "Oracle Login Failed" if isinstance(e, OracleAuthError) else "Query Error"
            QMessageBox.warning(mainWindow, title, str(e) if isinstance(e, OracleAuthError) else f"Query failed:\n{e}")
        except Exception:
            try:
                QMessageBox.warning(mainWindow, "Query Error", f"Query failed:\n{e}")
            except Exception:
                pass
    finally:
        if progressDialog is not None:
            try:
                progressDialog.close()
            except Exception:
                pass


def roundDownToInterval(dt, interval):
    """Round down datetime to the nearest specified interval."""
    if interval == 'HOUR' or interval == 'INSTANT:60':
        # Round down to nearest hour
        dt = dt.replace(minute=0, second=0, microsecond=0)
    elif interval == 'INSTANT:1':
        # Round down to nearest minute
        dt = dt.replace(second=0, microsecond=0)
    elif interval == 'INSTANT:15':
        # Round down to nearest 15-minute interval
        try:
            n = 15
            minutesDown = (dt.minute // n) * n
            dt = dt.replace(minute=minutesDown, second=0, microsecond=0)
        except ValueError:
            if Config.debug:
                Logic.logMessage("WARN", f"Error rounding INSTANT:15, no rounding applied")
            return dt
    else:
        # For other intervals, no manipulation needed
        if Config.debug:
            Logic.logMessage("DEBUG", f"Interval {interval} does not require rounding, returning unchanged")
        return dt
    
    if Config.debug:
        Logic.logMessage("DEBUG", f"Rounded down {dt} to {interval}")
    return dt