import queue
import time
from collections import defaultdict
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QCoreApplication, QTimer
from PyQt6.QtGui import QColor, QBrush, QFont, QFontMetrics
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QSizePolicy, QProgressDialog
from core import Logic, USBR, USGS, Aquarius, Config, Utils, QueryUtils
from DataDoctor import uiMain

class sortWorkerSignals(QObject):
    sortDone = pyqtSignal(list, bool)

class sortWorker(QRunnable):
    def __init__(self, rows, col, ascending):
        super().__init__()
        self.signals = sortWorkerSignals()
        self.rows = rows
        self.col = col
        self.ascending = ascending

    def run(self):
        def sortKey(row):
            try:
                return float(row[self.col + 1])
            except ValueError:
                return 0
        self.rows.sort(key=sortKey, reverse=not self.ascending)
        self.signals.sortDone.emit(self.rows, self.ascending)

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
        groupLabels = {} if db == 'AQUARIUS' else None
        usbrGroups = defaultdict(list)
        for origIndex, dataID, SDID, itemDb, interval, mrid in self.groupItems:
            usbrGroups[(itemDb, interval, mrid)].append((origIndex, dataID, SDID))
        try:
            for (itemDb, interval, mrid), items in usbrGroups.items():
                SDIDs = [item[2] for item in items]
                result = {}
                if db.startswith('USBR'):
                    try:
                        svr = itemDb.split('-')[1].lower() if '-' in itemDb else 'lchdb'
                        table = 'M' if mrid != '0' else 'R'
                        apiInterval = interval
                        result = USBR.apiRead(svr, SDIDs, self.startDate, self.endDate, apiInterval, mrid, table)
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: USBR result for SDIDs {SDIDs}: {result}")
                    except Exception as e:
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: USBR apiRead failed for SDIDs {SDIDs}: {e}")
                        result = {}
                elif db == 'AQUARIUS' and self.isInternal:
                    try:
                        result = Aquarius.apiRead(SDIDs, self.startDate, self.endDate, interval)
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: Aquarius result for SDIDs {SDIDs}: {result}")
                    except Exception as e:
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: Aquarius apiRead failed for SDIDs {SDIDs}: {e}")
                        result = {}
                elif db == 'USGS-NWIS':
                    try:
                        result = USGS.apiRead(SDIDs, interval, self.startDate, self.endDate)
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: USGS result for SDIDs {SDIDs}: {result}")
                    except Exception as e:
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: USGS apiRead failed for SDIDs {SDIDs}: {e}")
                        result = {}
                else:
                    if Config.debug:
                        print(f"[DEBUG] queryWorker: Unknown db skipped: {db}")
                    continue
                for idx, (origIndex, dataID, SDID) in enumerate(items):
                    if SDID in result and result[SDID]:
                        if db == 'AQUARIUS':
                            outputData = result.get(SDID, {}).get('data', [])
                            groupLabels[dataID] = result.get(SDID, {}).get('label', dataID)
                            if Config.debug:
                                print(f"[DEBUG] queryWorker: Aquarius label for {dataID}: {groupLabels[dataID]}")
                        else:
                            outputData = result.get(SDID, [])
                        alignedData = gapCheck(self.timestamps, outputData, dataID)
                        values = [line.split(',')[1] if line else '' for line in alignedData]
                        groupResult[dataID] = values
                    else:
                        groupResult[dataID] = self.defaultBlanks
                        if db == 'AQUARIUS':
                            groupLabels[dataID] = dataID
                        if Config.debug:
                            print(f"[DEBUG] queryWorker: No data for SDID {SDID} in {db}")
            if Config.debug:
                print(f"[DEBUG] queryWorker: Completed group {self.groupKey} with {len(groupResult)} items")
        except Exception as e:
            if Config.debug:
                print(f"[DEBUG] queryWorker: Failed for group {self.groupKey}: {e}")
            for _, dataID, _ in items:
                groupResult[dataID] = self.defaultBlanks
                if db == 'AQUARIUS':
                    groupLabels[dataID] = dataID
        self.signals.resultSignal.emit((self.groupKey, groupResult, groupLabels))

def buildTimestamps(startDateStr, endDateStr, intervalStr):
    if Config.debug:
        print("[DEBUG] buildTimestamps called with start: {}, end: {}, interval: {}".format(startDateStr, endDateStr, intervalStr))
    try:
        start = datetime.strptime(startDateStr, '%Y-%m-%d %H:%M')
        end = datetime.strptime(endDateStr, '%Y-%m-%d %H:%M')
    except ValueError as e:
        print("[ERROR] Invalid date format in buildTimestamps: {}".format(e))
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
                print("[ERROR] Unsupported INSTANT interval: {}".format(intervalStr))
                return []
        except (IndexError, ValueError) as e:
            print("[ERROR] Invalid INSTANT interval format: {}".format(e))
            return []
    elif intervalStr == 'DAY':
        delta = timedelta(days=1)
        start = start.replace(hour=0, minute=0, second=0)
    else:
        print("[ERROR] Unknown intervalStr: {}".format(intervalStr))
        return []
    timestamps = []
    current = start
    while current < end:
        ts = current.strftime('%m/%d/%y %H:%M:00')
        timestamps.append(ts)
        current += delta
    if Config.debug:
        print("[DEBUG] Generated {} timestamps, sample first 3: {}".format(len(timestamps), timestamps[:3]))
    return timestamps

def gapCheck(timestamps, data, dataID=''):
    if Config.debug:
        print("[DEBUG] gapCheck for dataID '{}': timestamps len={}, data len={}".format(dataID, len(timestamps), len(data)))
    if not timestamps:
        return data
    try:
        expectedDateTimes = [datetime.strptime(ts, '%m/%d/%y %H:%M:00') for ts in timestamps]
    except ValueError as e:
        print("[ERROR] Invalid timestamp format in timestamps: {}".format(e))
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
                print("[WARN] Malformed data row skipped: '{}' for '{}'".format(line, dataID))
                i += 1
                continue
            actualTimestampStr = parts[0].strip()
            try:
                actualDateTime = datetime.strptime(actualTimestampStr, '%m/%d/%y %H:%M:%S')
            except ValueError:
                print("[WARN] Invalid ts skipped: '{}' in '{}' for '{}'".format(actualTimestampStr, line, dataID))
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
            print("[DEBUG] Removed {} extra/mismatched rows from '{}': ts {}".format(len(removed), dataID, removed))
    if Config.debug:
        print("[DEBUG] Post-gapCheck len={}, sample first 3: {}".format(len(newData), newData[:3]))
    return newData

def combineParameters(data, newData):
    if len(data) != len(newData):
        return data
    for d in range(len(newData)):
        parseLine = newData[d].split(',')
        data[d] = f'{data[d]},{parseLine[1]}'
    return data

def buildTable(table, data, buildHeader, dataDictionaryTable, intervals, lookupIds=None, labelsDict=None, databases=None, queryItems=None):
    if Config.debug:
        print("[DEBUG] buildTable: Starting with {} rows, {} headers".format(len(data), len(buildHeader)))
    table.clear()
    if not data:
        if Config.debug:
            print("[DEBUG] buildTable: No data to display.")
        return
    if isinstance(buildHeader, str):
        buildHeader = [h.strip() for h in buildHeader.split(',')]
    processedHeaders = []
    for i, h in enumerate(buildHeader):
        dataId = h.strip()
        intervalStr = intervals[i].upper()
        if intervalStr.startswith('INSTANT:'):
            intervalStr = 'INSTANT'
        database = databases[i] if databases and i < len(databases) else None
        dictRow = getDataDictionaryItem(dataDictionaryTable, lookupIds[i] if lookupIds else dataId)
        mrid = None
        if database and database.startswith('USBR-') and '-' in dataId:
            parts = dataId.rsplit('-', 1)
            dataId = parts[0]
            mrid = parts[1] if len(parts) > 1 else '0'
        if dictRow != -1:
            siteItem = dataDictionaryTable.item(dictRow, 1)
            baseLabel = siteItem.text().strip() if siteItem else dataId
            if database == 'USGS-NWIS':
                parts = dataId.split('-')
                if len(parts) == 3 and parts[0].isdigit() and (parts[1].isdigit() or (len(parts[1]) == 32 and parts[1].isalnum())) and parts[2].isdigit():
                    fullLabel = f"{parts[0]}-{parts[2]} \n{intervalStr}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USGS in dict, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{baseLabel} \n{intervalStr}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USGS in dict but non-USGS format, header {i}: {fullLabel}")
            elif database == 'AQUARIUS' and labelsDict and dataId in labelsDict:
                apiFull = labelsDict[dataId]
                parts = apiFull.split('\n')
                label = parts[0].strip() if len(parts) >= 1 else dataId
                location = parts[1].strip() if len(parts) >= 2 else dataId
                fullLabel = f"{label} \n{location}"
                if Config.debug:
                    print(f"[DEBUG] buildTable: Aquarius in dict, header {i}: {fullLabel}")
            else:
                if mrid and mrid != '0':
                    fullLabel = f"{baseLabel} \n{dataId}-{mrid}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USBR in dict with MRID, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{baseLabel} \n{dataId}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USBR in dict, header {i}: {fullLabel}")
        else:
            if database == 'USGS-NWIS':
                parts = dataId.split('-')
                if len(parts) == 3 and parts[0].isdigit() and (parts[1].isdigit() or (len(parts[1]) == 32 and parts[1].isalnum())) and parts[2].isdigit():
                    fullLabel = f"{parts[0]}-{parts[2]} \n{intervalStr}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: Parsed USGS header {i}: {fullLabel}")
                else:
                    fullLabel = f"{dataId} \n{intervalStr}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USGS not in dict, header {i}: {fullLabel}")
            elif database == 'AQUARIUS' and labelsDict and dataId in labelsDict:
                apiFull = labelsDict[dataId]
                parts = apiFull.split('\n')
                label = parts[0].strip() if len(parts) >= 1 else dataId
                location = parts[1].strip() if len(parts) >= 2 else dataId
                fullLabel = f"{label} \n{location}"
                if Config.debug:
                    print(f"[DEBUG] buildTable: Aquarius not in dict, header {i}: {fullLabel}")
            else:
                if mrid and mrid != '0':
                    fullLabel = f"{dataId}-{mrid} \n{intervalStr}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USBR not in dict with MRID, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{dataId} \n{intervalStr}"
                    if Config.debug:
                        print(f"[DEBUG] buildTable: USBR not in dict, header {i}: {fullLabel}")
        processedHeaders.append(fullLabel)
    headers = processedHeaders
    skipDateCol = dataDictionaryTable is not None
    numCols = len(headers)
    numRows = len(data)
    if numRows > 10000:
        reply = QMessageBox.warning(None, "Large Dataset Warning",
                                   f"Query returned {numRows} rows, which may slow down the UI. Consider a smaller date range or coarser interval (e.g., HOUR instead of INSTANT:1). Continue?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            if Config.debug:
                print(f"[DEBUG] buildTable: User canceled due to large dataset ({numRows} rows)")
            return
    if Config.debug:
        print(f"[DEBUG] buildTable: Setting table to {numRows} rows, {numCols} columns")
    table.setRowCount(numRows)
    table.setColumnCount(numCols)
    table.setHorizontalHeaderLabels(headers)
    table.show()
    if dataDictionaryTable:
        timestamps = [row.split(',')[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        vHeader = table.verticalHeader()
        vHeader.setMinimumWidth(120)
        vHeader.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vHeader.setVisible(True)
    else:
        table.verticalHeader().setVisible(False)
    font = table.font()
    metrics = QFontMetrics(font)
    columnWidths = []
    sampleRows = min(1000, numRows)
    if Config.debug:
        print(f"[DEBUG] buildTable: Sampling {sampleRows} rows for column widths")
    for c in range(numCols):
        cellValues = [row.split(',')[c+1].strip() if c+1 < len(row.split(',')) else "0.00" for row in data[:sampleRows]]
        nonEmptyValues = [val for val in cellValues if val]
        if nonEmptyValues:
            maxCellWidth = max(metrics.horizontalAdvance(val) for val in nonEmptyValues)
        else:
            maxCellWidth = metrics.horizontalAdvance("0.00")
            if Config.debug:
                print(f"[DEBUG] buildTable col {c}: No non-empty values, using fallback width {maxCellWidth}")
        headerLines = headers[c].split('\n')
        headerWidth = max(metrics.horizontalAdvance(line.strip()) for line in headerLines) if headerLines else 0
        if Config.debug:
            print(f"[DEBUG] buildTable col {c}: maxCellWidth={maxCellWidth}, headerWidth={headerWidth}")
        finalWidth = max(maxCellWidth, headerWidth)
        if headerWidth > maxCellWidth:
            paddingIncrease = headerWidth - maxCellWidth
            finalWidth = maxCellWidth + paddingIncrease + 10
        else:
            finalWidth += 20
        columnWidths.append(finalWidth)
    table.setUpdatesEnabled(False)
    if Config.debug:
        print("[DEBUG] buildTable: Disabled table updates for population")
    for rowIdx, rowStr in enumerate(data):
        rowData = rowStr.split(',')[1:] if skipDateCol else rowStr.split(',')
        for colIdx in range(min(numCols, len(rowData))):
            cellText = rowData[colIdx].strip() if colIdx < len(rowData) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if not Config.rawData and cellText.strip():
                item.setText(Logic.valuePrecision(cellText))
            table.setItem(rowIdx, colIdx, item)
    table.setUpdatesEnabled(True)
    if Config.debug:
        print("[DEBUG] buildTable: Re-enabled table updates after population")
    table.horizontalHeader().sectionClicked.connect(lambda col: customSortTable(table, col, dataDictionaryTable))
    header = table.horizontalHeader()
    vHeader = table.verticalHeader()
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setMinimumSize(0, 0)
    table.update()
    header.setStretchLastSection(False)
    if Config.debug:
        print("[DEBUG] buildTable: Set stretchLastSection=False to prevent last column expansion.")
    if dataDictionaryTable:
        maxTimeWidth = max(metrics.horizontalAdvance(ts) for ts in timestamps)
        vHeader.setMinimumWidth(max(120, maxTimeWidth) + 10)
    for c in range(numCols):
        table.setColumnWidth(c, columnWidths[c])
        if Config.debug:
            print(f"[DEBUG] buildTable: Set column {c} width to {columnWidths[c]}")
    rowHeight = metrics.height() + 10
    sampleItem = QTableWidgetItem("189.5140")
    sampleItem.setFont(font)
    sampleCellHeight = sampleItem.sizeHint().height()
    if sampleCellHeight <= 0:
        sampleCellHeight = metrics.height()
    adjustedRowHeight = max(rowHeight, sampleCellHeight + 2)
    if Config.debug:
        print(f"[DEBUG] buildTable: Sample cell height: {sampleCellHeight}, Adjusted row height: {adjustedRowHeight}")
    vHeader.setDefaultSectionSize(adjustedRowHeight)
    if Config.debug:
        print(f"[DEBUG] buildTable: Set default row height to {adjustedRowHeight}")
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    vHeader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.update()
    table.horizontalScrollBar().setValue(0)
    visibleWidth = table.columnWidth(1) if numCols > 1 else 0
    if Config.debug and numCols > 1:
        print(f"[DEBUG] buildTable: Custom resized {numCols} columns. Text width for col 1: {metrics.horizontalAdvance(headers[1])}, Visible width: {visibleWidth}, Row height: {adjustedRowHeight}")
    dataIds = buildHeader
    if Config.qaqcEnabled:
        qaqc(table, dataDictionaryTable, dataIds)
    else:
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item:
                    item.setBackground(QColor(0, 0, 0, 0))
        if Config.debug:
            print("[DEBUG] buildTable: QAQC skipped, cleared cell backgrounds")

def getDataDictionaryItem(table, dataId):
    for r in range(table.rowCount()):
        item = table.item(r, 0)
        if item and item.text().strip() == dataId.strip():
            return r
    return -1

def qaqc(table, dataDictionaryTable, lookupIds):
    if not Config.qaqcEnabled:
        if Config.debug:
            print("[DEBUG] qaqc: Skipped, QAQC disabled in config")
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item:
                    item.setBackground(QColor(0, 0, 0, 0))
        return
    now = datetime.now()
    for col, lookupId in enumerate(lookupIds):
        if Config.debug:
            print("[DEBUG] qaqc: Processing column {} for lookupId {}".format(col, lookupId))
        rowIndex = getDataDictionaryItem(dataDictionaryTable, lookupId)
        expectedMin = None
        expectedMax = None
        cutoffMin = None
        cutoffMax = None
        rateOfChange = None
        if rowIndex != -1:
            expectedMinItem = dataDictionaryTable.item(rowIndex, 3)
            if expectedMinItem and expectedMinItem.text().strip():
                expectedMin = float(expectedMinItem.text().strip())
            expectedMaxItem = dataDictionaryTable.item(rowIndex, 4)
            if expectedMaxItem and expectedMaxItem.text().strip():
                expectedMax = float(expectedMaxItem.text().strip())
            cutoffMinItem = dataDictionaryTable.item(rowIndex, 5)
            if cutoffMinItem and cutoffMinItem.text().strip():
                cutoffMin = float(cutoffMinItem.text().strip())
            cutoffMaxItem = dataDictionaryTable.item(rowIndex, 6)
            if cutoffMaxItem and cutoffMaxItem.text().strip():
                cutoffMax = float(cutoffMaxItem.text().strip())
            rateOfChangeItem = dataDictionaryTable.item(rowIndex, 7)
            if rateOfChangeItem and rateOfChangeItem.text().strip():
                rateOfChange = float(rateOfChangeItem.text().strip())
        prevVal = None
        for r in range(table.rowCount()):
            item = table.item(r, col)
            if not item:
                continue
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            cellText = item.text().strip()
            if cellText == '':
                tsItem = table.verticalHeaderItem(r)
                if tsItem:
                    tsStr = tsItem.text()
                    try:
                        tsDt = datetime.strptime(tsStr, '%m/%d/%y %H:%M:00')
                        if tsDt <= now:
                            item.setBackground(QColor(100, 195, 247))
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
                    item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(QColor(0, 0, 0)))
                elif expectedMax is not None and val > expectedMax:
                    item.setBackground(QColor(249, 194, 17))
                    item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(QColor(0, 0, 0)))
                elif cutoffMin is not None and val < cutoffMin:
                    item.setBackground(QColor(255, 163, 72))
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
                elif cutoffMax is not None and val > cutoffMax:
                    item.setBackground(QColor(192, 28, 40))
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
                if rateOfChange is not None and prevVal is not None:
                    if abs(val - prevVal) > rateOfChange:
                        item.setBackground(QColor(246, 97, 81))
                        item.setData(Qt.ItemDataRole.ForegroundRole, None)
            if prevVal is not None and val == prevVal:
                item.setBackground(QColor(87, 227, 137))
                item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(QColor(0, 0, 0)))
            prevVal = val
        if Config.debug:
            print("[DEBUG] qaqc: Processed column {} for lookupId {}".format(col, lookupId))

def customSortTable(table, col, dataDictionaryTable):
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
    numRows = table.rowCount()
    rows = []
    for rowIdx in range(numRows):
        timestamp = table.verticalHeaderItem(rowIdx).text() if table.verticalHeaderItem(rowIdx) else ''
        rowData = [table.item(rowIdx, c).text() if table.item(rowIdx, c) else '' for c in range(table.columnCount())]
        rows.append([timestamp] + rowData)
    pool = QThreadPool.globalInstance()
    worker = sortWorker(rows, col, ascending)
    worker.signals.sortDone.connect(lambda sortedRows, asc: updateTableAfterSort(table, sortedRows, asc, dataDictionaryTable, col))
    pool.start(worker)
    header.setSortIndicator(col, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)

def updateTableAfterSort(table, sortedRows, ascending, dataDictionaryTable, col):
    table.setSortingEnabled(False)
    for rowIdx, row in enumerate(sortedRows):
        table.setVerticalHeaderItem(rowIdx, QTableWidgetItem(row[0]))
        for c in range(table.columnCount()):
            cellText = row[c + 1] if c + 1 < len(row) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if not Config.rawData and cellText.strip():
                item.setText(Logic.valuePrecision(cellText))
            table.setItem(rowIdx, c, item)
    if Config.debug:
        print("[DEBUG] Updated table after sort; widths not locked.")
    headerLabels = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    dataIds = [label.split('\n')[-1].strip() for label in headerLabels]
    if Config.qaqcEnabled:
        qaqc(table, dataDictionaryTable, dataIds)
    else:
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item:
                    item.setBackground(QColor(0, 0, 0, 0))
        if Config.debug:
            print("[DEBUG] updateTableAfterSort: QAQC skipped, cleared cell backgrounds")
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

def timestampSortTable(table, dataDictionaryTable):
    if Config.debug:
        print("[DEBUG] timestampSortTable: Starting sort by timestamps.")
    numRows = table.rowCount()
    rows = []
    for rowIdx in range(numRows):
        timestamp = table.verticalHeaderItem(rowIdx).text() if table.verticalHeaderItem(rowIdx) else ''
        rowData = [table.item(rowIdx, c).text() if table.item(rowIdx, c) else '' for c in range(table.columnCount())]
        rows.append([timestamp] + rowData)
    def sortKey(row):
        try:
            return datetime.strptime(row[0], '%m/%d/%y %H:%M:00')
        except ValueError:
            return datetime.min
    rows.sort(key=sortKey)
    pool = QThreadPool.globalInstance()
    worker = sortWorker(rows, -1, True)
    worker.signals.sortDone.connect(lambda sortedRows, asc: updateTableAfterSort(table, sortedRows, asc, dataDictionaryTable, -1))
    pool.start(worker)
    if Config.debug:
        print("[DEBUG] Timestamp sort worker started.")

def executeQuery(mainWindow, queryItems, startDate, endDate, isInternal, dataDictionaryTable, deltaChecked=False, overlayChecked=False):
    Config.deltaChecked = deltaChecked
    Config.overlayChecked = overlayChecked

    if Config.debug:
        print("[DEBUG] executeQuery: isInternal={}, items={}".format(isInternal, len(queryItems)))
    if not isInternal:
        queryItems = [item for item in queryItems if item[2] != 'AQUARIUS']
        if Config.debug:
            print("[DEBUG] executeQuery: Filtered AQUARIUS for public query, remaining items={}".format(len(queryItems)))
    if not queryItems:
        QMessageBox.warning(mainWindow, "No Valid Items", "No valid query items (AQUARIUS not allowed in public queries).")
        if Config.debug:
            print("[DEBUG] executeQuery: No valid items after filtering, aborting")
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
        print("[DEBUG] executeQuery: Initialized and showed progress dialog")
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
    timestamps = buildTimestamps(startDate, endDate, firstInterval)
    if not timestamps:
        progressDialog.cancel()
        QMessageBox.warning(mainWindow, "Date Error", "Invalid dates or interval.")
        return
    progressDialog.setValue(20)
    progressDialog.repaint()
    QCoreApplication.processEvents()
    if Config.debug:
        print("[DEBUG] executeQuery: Setup complete, progress at 20%")
    defaultBlanks = [''] * len(timestamps)
    labelsDict = {} if isInternal else None
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
        SDID = dataID.split('-')[0] if db.startswith('USBR-') and '-' in dataID else dataID
        groups[groupKey].append((origIndex, dataID, SDID, db, interval, mrid))
    pool = QThreadPool.globalInstance()
    resultQueue = queue.Queue()
    maxDbThreads = 3
    numGroups = len(groups)
    numThreads = min(maxDbThreads, numGroups)
    if Config.debug:
        print(f"[DEBUG] Starting {numThreads} threads for {numGroups} groups in background")
    threadsStarted = 0
    valueDict = {}
    collected = 0
    processedGroups = set()

    def handleResult(result):
        nonlocal collected
        groupKey, groupResult, groupLabels = result
        if groupKey in processedGroups:
            if Config.debug:
                print(f"[DEBUG] executeQuery: Duplicate group {groupKey}, skipping")
            return
        processedGroups.add(groupKey)
        if all(all(v == '' for v in values) for values in groupResult.values()):
            if Config.debug:
                print(f"[DEBUG] executeQuery: Skipping empty group {groupKey}, no data")
            collected += 1
            if not progressDialog.wasCanceled():
                progressDialog.setValue(20 + int(50 * collected / numGroups))
                progressDialog.setLabelText(f"Completed {groupKey[0]} query ({collected}/{numGroups})")
                progressDialog.repaint()
                QCoreApplication.processEvents()
            return
        valueDict.update(groupResult)
        if groupLabels and labelsDict is not None:
            labelsDict.update(groupLabels)
            if Config.debug:
                print(f"[DEBUG] executeQuery: Updated labelsDict with {list(groupLabels.keys())}")
        collected += 1
        if Config.debug:
            print(f"[DEBUG] executeQuery: Collected results for group {groupKey} with {len(groupResult)} items ({collected}/{numGroups})")
        if not progressDialog.wasCanceled():
            progressDialog.setValue(20 + int(50 * collected / numGroups))
            progressDialog.setLabelText(f"Completed {groupKey[0]} query ({collected}/{numGroups})")
            progressDialog.repaint()
            QCoreApplication.processEvents()

    for i, groupKey in enumerate(groups.keys()):
        signals = queryWorkerSignals()
        worker = queryWorker(groupKey, groups[groupKey], signals, startDate, endDate, isInternal, timestamps, defaultBlanks)
        signals.resultSignal.connect(lambda result, i=i: [print(f"[DEBUG] executeQuery: Signal received for group {result[0]}") if Config.debug else None, resultQueue.put(result), handleResult(result)][-1])
        pool.start(worker)
        threadsStarted += 1
        if Config.debug:
            print(f"[DEBUG] Started background worker {i} for group {groupKey}")
    if not progressDialog.wasCanceled():
        progressDialog.setValue(20)
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
                    print(f"[DEBUG] executeQuery: Timeout after {timeoutSeconds} seconds, collected {collected}/{numGroups}")
                print(f"[WARN] Query timeout after {timeoutSeconds} seconds; some data may be missing")
                progressDialog.cancel()
                QMessageBox.warning(mainWindow, "Query Timeout", "Query timed out; some data may be missing.")
                return
        if not progressDialog.wasCanceled():
            while not resultQueue.empty():
                try:
                    result = resultQueue.get_nowait()
                    if Config.debug:
                        print(f"[DEBUG] executeQuery: Retrieved result from queue: {result[0]}")
                    handleResult(result)
                except queue.Empty:
                    break
            progressDialog.setLabelText(f"Querying data... ({collected}/{numGroups} complete)")
            progressDialog.repaint()
            QCoreApplication.processEvents()

    timer.timeout.connect(checkQueueAndProgress)
    timer.start(100)
    if Config.debug:
        print("[DEBUG] executeQuery: Started timer for progress updates")
    while (collected < numGroups or not resultQueue.empty() or pool.activeThreadCount() > 0) and not progressDialog.wasCanceled():
        time.sleep(0.05)
        QCoreApplication.processEvents()
    if collected >= numGroups:
        while not resultQueue.empty():
            try:
                result = resultQueue.get_nowait()
                if Config.debug:
                    print(f"[DEBUG] executeQuery: Processed extra queued result, collected {collected}/{numGroups}, queue size {resultQueue.qsize()}")
                handleResult(result)
            except queue.Empty:
                break
        maxRetries = 5
        retryCount = 0
        while not resultQueue.empty() and retryCount < maxRetries:
            try:
                result = resultQueue.get_nowait()
                if Config.debug:
                    print(f"[DEBUG] executeQuery: Processed final queued result, collected {collected}/{numGroups}, queue size {resultQueue.qsize()}")
                handleResult(result)
            except queue.Empty:
                break
            retryCount += 1
        if retryCount >= maxRetries:
            if Config.debug:
                print(f"[DEBUG] executeQuery: Max retries ({maxRetries}) reached for final queue flush, queue size {resultQueue.qsize()}")
    timer.stop()
    if Config.debug:
        print(f"[DEBUG] executeQuery: Timer stopped, wait loop ended, final collected {collected}/{numGroups}, queue size {resultQueue.qsize()}, active threads {pool.activeThreadCount()}")
    QCoreApplication.processEvents()
    if progressDialog.wasCanceled():
        if Config.debug:
            print(f"[DEBUG] executeQuery: User canceled via progress dialog")
        progressDialog.cancel()
        return
    if Config.debug:
        print(f"[DEBUG] executeQuery: All {collected} groups merged")
    progressDialog.setLabelText("Merging results...")
    progressDialog.setValue(70)
    progressDialog.repaint()
    QCoreApplication.processEvents()
    for dataID, _, _, _, _ in queryItems:
        if dataID not in valueDict:
            valueDict[dataID] = defaultBlanks
            if Config.debug:
                print(f"[DEBUG] Added empty result for dataID {dataID}")
    originalDataIds = [item[0] for item in queryItems]
    originalIntervals = [item[1] for item in queryItems]
    databases = [item[2] for item in queryItems]
    lookupIds = [item[0].split('-')[0] if item[2].startswith('USBR-') and '-' in item[0] else item[0] for item in queryItems]
    data = []
    for r in range(len(timestamps)):
        rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
        data.append("{},{}".format(timestamps[r], ','.join(rowValues)))
        if r % 100 == 0:
            progressDialog.setLabelText(f"Building rows... ({r}/{len(timestamps)} rows)")
            progressDialog.setValue(72 + int(28 * r / len(timestamps)))
            progressDialog.repaint()
            QCoreApplication.processEvents()
        if Config.debug:
            print(f"[DEBUG] executeQuery: Building row {r}/{len(timestamps)}")
    if Config.debug:
        print(f"[DEBUG] executeQuery: Built {len(data)} rows for table")
    if not progressDialog.wasCanceled():
        progressDialog.setLabelText("Building table...")
        progressDialog.setValue(70)
        progressDialog.repaint()
        QCoreApplication.processEvents()
        mainWindow.mainTable.clear()

        # Add tab before building table
        if mainWindow.tabWidget.indexOf(mainWindow.tabMain) == -1:
            mainWindow.tabWidget.addTab(mainWindow.tabMain, 'Data Query')

        # Build the table
        buildTable(mainWindow.mainTable, data, originalDataIds, dataDictionaryTable, originalIntervals, lookupIds, labelsDict, databases, queryItems=queryItems)

        # Modify table if query tools are checked
        if deltaChecked or overlayChecked:
            QueryUtils.modifyTable(mainWindow.mainTable, deltaChecked, overlayChecked, databases, queryItems, labelsDict, dataDictionaryTable, originalIntervals, lookupIds, mainWindow=mainWindow)
        else:
            mainWindow.columnMetadata = []
            
            for i in range(mainWindow.mainTable.columnCount()):
                mainWindow.columnMetadata.append({
                    'type': 'normal',
                    'dataIds': [lookupIds[i]],
                    'dbs': [databases[i]],
                    'queryInfos': [f"{queryItems[i][0]}|{queryItems[i][1]}|{queryItems[i][2]}"]
                })
            if Config.debug:
                print("[DEBUG] executeQuery: Set normal columnMetadata with {} entries".format(len(mainWindow.columnMetadata)))

        progressDialog.setValue(72)
        progressDialog.repaint()
        QCoreApplication.processEvents()
    if Config.debug:
        print(f"[DEBUG] executeQuery: Table built, progress dialog completed")
    if progressDialog.wasCanceled():
        if Config.debug:
            print(f"[DEBUG] executeQuery: User canceled during table building")
        progressDialog.cancel()
        return
    if mainWindow.tabWidget.indexOf(mainWindow.tabMain) == -1:
        mainWindow.tabWidget.addTab(mainWindow.tabMain, 'Data Query')
        if Config.debug:
            print("[DEBUG] Query executed and table updated.")
    progressDialog.cancel()
    QCoreApplication.processEvents()