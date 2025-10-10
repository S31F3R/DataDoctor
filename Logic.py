import os
import sys
import datetime
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QTimer, QByteArray
from PyQt6.QtGui import QGuiApplication, QColor
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog

sortState = {}  # Global dict for per-col sort state (col: ascending)

def buildTimestamps(startDateStr, endDateStr, intervalStr):
    print("[DEBUG] buildTimestamps called with start: {}, end: {}, interval: {}".format(startDateStr, endDateStr, intervalStr))

    try:
        start = datetime.strptime(startDateStr, '%Y-%m-%d %H:%M')
        end = datetime.strptime(endDateStr, '%Y-%m-%d %H:%M')
    except ValueError as e:
        print("[ERROR] Invalid date format in buildTimestamps: {}".format(e))
        return []
    
    if intervalStr == 'HOUR':
        delta = timedelta(hours=1)

        # Truncate start down to top of hour
        start = start.replace(minute=0, second=0)
    elif intervalStr == 'INSTANT':
        delta = timedelta(minutes=15)

        # Truncate down to nearest 15min
        minute = (start.minute // 15) * 15
        start = start.replace(minute=minute, second=0)
    elif intervalStr == 'DAY':
        delta = timedelta(days=1)

        # Truncate down to midnight
        start = start.replace(hour=0, minute=0, second=0)
    else:
        print("[ERROR] Unknown intervalStr: {}".format(intervalStr))
        return []
    
    timestamps = []
    current = start
    
    while current < end:
        ts_str = current.strftime('%m/%d/%y %H:%M:00')
        timestamps.append(ts_str)
        current += delta
    
    print("[DEBUG] Generated {} timestamps, sample first 3: {}".format(len(timestamps), timestamps[:3]))
    return timestamps

def gapCheck(timestamps, data, dataID=''):
    print("[DEBUG] gapCheck for dataID '{}': timestamps len={}, data len={}".format(dataID, len(timestamps), len(data)))

    if not timestamps:
        return data

    # Parse expected ts
    try:
        expectedDateTimes = [datetime.strptime(ts, '%m/%d/%y %H:%M:00') for ts in timestamps]
    except ValueError as e:
        print("[ERROR] Invalid timestamp format in timestamps: {}".format(e))
        return data

    newData = []
    removed = []  # Collect details for warn
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
                # Match, add (ensure :00 seconds if not)
                if not actualTimestampStr.endswith(':00'):
                    actualTimestampStr = actualDateTime.strftime('%m/%d/%y %H:%M:00')
                    line = actualTimestampStr + ',' + ','.join(parts[1:])
                newData.append(line)
                found = True
                i += 1

                break
            elif actualDateTime < expectedDateTime:
                # Extra/early, remove
                removed.append(actualTimestampStr)
                i += 1
            else:
                # Future/mismatch, insert gap and break to next exp
                break
        if not found:
            # Gap, insert blank
            tsStr = expectedDateTime.strftime('%m/%d/%y %H:%M:00')
            newData.append(tsStr + ',')
    # Any remaining data are extras
    while i < len(data):
        line = data[i]
        parts = line.split(',')
        if len(parts) > 0:
            removed.append(parts[0].strip())
        i += 1
    if removed:
        print("[WARN] Removed {} extra/mismatched rows from '{}': ts {}".format(len(removed), dataID, removed))
    print("[DEBUG] Post-gapCheck len={}, sample first 3: {}".format(len(newData), newData[:3]))

    return newData

def combineParameters(data, newData):
    if len(data) != len(newData):
        return data  # Mismatch—skip
    for d in range(len(newData)):
        parseLine = newData[d].split(',')
        data[d] = f'{data[d]},{parseLine[1]}'
    return data

def buildTable(table, data, buildHeader, dataDictionaryTable):
    table.clear()

    if not data:
        return
    
    # Set up table structure (extra column for timestamp)
    table.setRowCount(len(data))
    table.setColumnCount(len(buildHeader) + 1)

    # Build header with center alignment (col 0 = timestamp)
    timestampHeader = QTableWidgetItem("Timestamp")
    timestampHeader.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
    table.setHorizontalHeaderItem(0, timestampHeader)

    for c in range(len(buildHeader)):
        item = QTableWidgetItem(str(buildHeader[c]))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        table.setHorizontalHeaderItem(c, item)

    # Populate data rows with center alignment
    for r in range(len(data)):
        rowData = data[r].split(',')

        for c in range(len(rowData)):
            item = QTableWidgetItem(rowData[c])
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setHorizontalHeaderItem(c + 1, item)

    # Assume buildHeader is list; split if str
    if isinstance(buildHeader, str):
        buildHeader = [h.strip() for h in buildHeader.split(',')]

    # Build processed headers with dict lookup (list for efficiency)
    processedHeaders = []

    for h in buildHeader:
        headerText = h.strip()  # Strip raw header

        if dataDictionaryTable:
            dictRow = getDataDictionaryItem(dataDictionaryTable, headerText)

            if dictRow != 'null':
                labelItem = dataDictionaryTable.item(dictRow, 2)

                if labelItem:
                    parseLabel = labelItem.text().split(':')

                    if len(parseLabel) > 1:
                        parseLabel[1] = parseLabel[1][1:].strip()  # Strip label part
                        headerText = f'{parseLabel[0].strip()} \n{parseLabel[1]} \n{headerText}'
        processedHeaders.append(headerText)

    # Headers: Processed only (no Date prepend)
    headers = processedHeaders

    # Conditional skip for main table (skip date col 0)
    skipDateCol = dataDictionaryTable  # True for main, False for dict
    numCols = len(headers)
    numRows = len(data)
    table.setRowCount(numRows)
    table.setColumnCount(numCols)
    table.setHorizontalHeaderLabels(headers)  # Full list

    # Vertical: Timestamps for main table only (dict table no dates)
    if dataDictionaryTable:
        timestamps = [row.split(',')[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        table.verticalHeader().setMinimumWidth(120)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(True)
    else:
        table.verticalHeader().setVisible(False)  # Hide for dict

    # Populate data (conditional skip, center all)
    for rowIDx, row_str in enumerate(data):
        rowData = row_str.split(',')[1:] if skipDateCol else row_str.split(',')  # Skip date for main

        for colIDx in range(min(numCols, len(rowData))):
            cellText = rowData[colIDx].strip() if colIDx < len(rowData) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(rowIDx, colIDx, item)

    # Resize all columns to fit headers + data
    for col in range(numCols):
        table.resizeColumnToContents(col)

    # Warm-up dummy sort to trigger initial reflow (no shift on first real click)
    header = table.horizontalHeader()
    table.setSortingEnabled(False)  # Disable for dummy
    QTimer.singleShot(0, lambda: [
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder),  # Dummy ASC on col 0
        table.sortItems(0, Qt.SortOrder.AscendingOrder),  # Dummy sort (no change)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder),  # Clear with ASC
        table.setSortingEnabled(True)  # Re-enable
    ])  # Queued for next loop cycle (settles layout)

    # Connect custom sort (syncs timestamps)
    table.horizontalHeader().sectionClicked.connect(lambda col: customSortTable(table, col, dataDictionaryTable))
    
def buildDataDictionary(table):
    data = []
    csv_path = resourcePath('DataDictionary.csv')

    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            readfile = f.readlines()
            if readfile:
                header = readfile[0].strip().split(',')
                data = [line.strip() for line in readfile[1:]]
    except FileNotFoundError:
        print("DataDictionary.csv missing—create empty.")
        header = ['ID', 'Description', 'Label']  # Default header

    buildTable(table, data, header, None)

def getDataDictionaryItem(table, dataID):
    data_id_clean = dataID.strip()  # Clean input

    # Optional: Strip common prefixes (e.g., 'SDID', 'site') if API adds them
    for prefix in ['', 'SDID', 'site', 'uid']:  # Add more if needed
        if data_id_clean.startswith(prefix):
            data_id_clean = data_id_clean[len(prefix):].strip()
            break

    for r in range(table.rowCount()):
        id_item = table.item(r, 0)
        if id_item:
            csv_id = id_item.text().strip()

            # Same prefix strip for CSV
            csv_id_clean = csv_id
            for prefix in ['', 'SDID', 'site', 'uid']:
                if csv_id_clean.startswith(prefix):
                    csv_id_clean = csv_id_clean[len(prefix):].strip()
                    break
            if csv_id_clean == data_id_clean:
                return r
    return 'null'

def qaqc(mainTable, dataDictionaryTable, dataID):
    if not dataID:
        return

    # Loop directly over dataID (list of IDs)
    for p, idVal in enumerate(dataID):       
        tempIndex = getDataDictionaryItem(dataDictionaryTable, idVal) 
        rowIndex = int(tempIndex) if tempIndex is not None and tempIndex != 'null' else None            

        if rowIndex is None: 
            continue # No match, skip entire column
        else:
            # Extract thresholds from dictionary row
            expectedMin = float(dataDictionaryTable.item(rowIndex, 3).text()) if dataDictionaryTable.item(rowIndex, 3).text() else 0
            expectedMax = float(dataDictionaryTable.item(rowIndex, 4).text()) if dataDictionaryTable.item(rowIndex, 4).text() else float('inf')
            cutoffMin = float(dataDictionaryTable.item(rowIndex, 5).text()) if dataDictionaryTable.item(rowIndex, 5).text() else expectedMin
            cutoffMax = float(dataDictionaryTable.item(rowIndex, 6).text()) if dataDictionaryTable.item(rowIndex, 6).text() else expectedMax
            roc = float(dataDictionaryTable.item(rowIndex, 7).text()) if dataDictionaryTable.item(rowIndex, 7).text() else 0

            colIndex = p + 1 # Offset by 1 for timestamp col

            # Check each row in mainTable (skip header)
            for row in range(1, mainTable.rowCount()):   
                item = mainTable.item(row, colIndex)                

                if not item:
                    continue

                cellText = item.text()
                colored = False # Flag for text color

                if not cellText:
                    item.setBackground(QColor(100, 195, 247)) # Missing (blue)
                    colored = True
                else:
                    try:
                        val = float(cellText)

                        # Cutoffs (red/orange)
                        if val > cutoffMax:
                            item.setBackground(QColor(192, 28, 40)) # Red
                            colored = True
                        elif val < cutoffMin:
                            item.setBackground(QColor(255, 163, 72)) # Orange
                            colored = True

                        # Expected (yellow)
                        elif val > expectedMax:
                            item.setBackground(QColor(245, 194, 17)) # Yellow
                            colored = True
                        elif val < expectedMin:
                            item.setBackground(QColor(249, 240, 107)) # Light Yellow
                            colored = True

                        # ROC (red)
                        prevVal = None
                        prevItem = mainTable.item(row - 1, colIndex) if row > 1 else None

                        if prevItem:
                            try:
                                prevVal = float(prevItem.text())

                                if abs(val - prevVal) > roc:
                                    item.setBackground(QColor(246, 97, 81)) # Red
                                    colored = True
                            except ValueError: 
                                pass

                        # Repeat (green)
                        if prevVal is not None and val == prevVal:
                            item.setBackground(QColor(87, 227, 137)) # Green
                            colored = True
                        prevVal = val
                    except ValueError:
                        pass  # Non-numeric: no color

                if colored:
                    # White for all except yellow (black for yellow readability)
                    if item.background().color() in [QColor(245, 194, 17), QColor(249, 240, 107)]:  # Yellows
                        item.setForeground(QColor("black"))
                    else:
                        item.setForeground(QColor("white"))

            # Re-center after any mod
            if item: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)                          

def loadAllQuickLooks(cbQuickLook):     
    cbQuickLook.clear()
    cbQuickLook.addItem(None)  # Blank first

    quicklook_dir = resourcePath('quickLook')

    if os.path.exists(quicklook_dir):
        for file in os.listdir(quicklook_dir):
            if file.endswith('.txt'):
                cbQuickLook.addItem(file.split('.txt')[0])
                  
def saveQuickLook(textQuickLookName, listQueryList):
    name = textQuickLookName.toPlainText().strip() if hasattr(textQuickLookName, 'toPlainText') else str(textQuickLookName).strip()
    if not name:
        print("Warning: Empty quick look name—skipped.")
        return

    data = [listQueryList.item(x).text() for x in range(listQueryList.count())]
    quicklook_path = resourcePath(f'quickLook/{name}.txt')
    os.makedirs(os.path.dirname(quicklook_path), exist_ok=True)  # Ensure dir

    with open(quicklook_path, 'w', encoding='utf-8-sig') as f:
        f.write(','.join(data))

def loadQuickLook(cbQuickLook, listQueryList):
    name = cbQuickLook.currentText()

    if not name:
        return

    quicklook_path = resourcePath(f'quickLook/{name}.txt')
    listQueryList.clear()
    try:
        with open(quicklook_path, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()
            if content:
                data = content.split(',')
                for item_text in data:
                    listQueryList.addItem(item_text.strip())
    except FileNotFoundError:
        print(f"Quick look '{name}' not found.")  

def loadConfig():
    config = ['light']  # Default color
    config_path = resourcePath('config.ini')

    try:
        with open(config_path, 'r', encoding='utf-8-sig') as f:
            config = [line.strip() for line in f.readlines()]
            if not config:  # Empty file
                config = ['light']
    except FileNotFoundError:
        # Create if missing
        with open(config_path, 'w', encoding='utf-8-sig') as f:
            f.write('light\n')
            
    # Ensure path entry (index 1)
    while len(config) < 2:
        config.append('')  # Empty path default
    return config

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        print("Empty table—no export.")
        return

    # Get last path from config (default to Documents)
    config = loadConfig()
    lastPath = config[1] if len(config) > 1 else os.path.expanduser("~/Documents")

    # Force Documents if lastPath empty/invalid
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.expanduser("~/Documents")
    defaultDir = lastPath

    # Timestamped default name (yyyy-mm-dd HH:mm:ss Export.csv)
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    default_name = f"{timestamp} Export.csv"
    suggested_path = os.path.join(defaultDir, default_name)
    filePath, _ = QFileDialog.getSaveFileName(None, "Save CSV As", suggested_path, "CSV files (*.csv)")

    if not filePath:
        return  # User canceled

    # Build CSV (your original logic)
    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = [','.join(headers)]

    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(','.join(rowData))

    # Write
    with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(csvLines))

    # Save last path to config (dir only)
    export_dir = os.path.dirname(filePath)
    if len(config) < 2:
        config.append(export_dir)  # Extend if short
    else:
        config[1] = export_dir  # Assign
    with open(resourcePath('config.ini'), 'w', encoding='utf-8-sig') as f:
        f.write(f"{config[0]}\n{export_dir}\n")  # color\npath

    print(f"Exported to {filePath}")

def resourcePath(relativePath):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):  # Bundled mode
        basePath = sys._MEIPASS
    else:  # Dev mode
        basePath = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(basePath, relativePath))

def customSortTable(table, col, dataDictionaryTable):
    # Prevent overlap (ignore if sorting already)
    pool = QThreadPool.globalInstance()

    if pool.activeThreadCount() > 0:
        return  # Skip during sort

    # Disable selection highlight during sort
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    # Clear indicator to stop Qt double-trigger
    header = table.horizontalHeader()
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # Clear (safe enum)

    # Toggle sort order (per-col state)
    if col not in sortState:
        sortState[col] = True  # Default ASC for new col
    else:
        sortState[col] = not sortState[col]  # Flip on every click
    ascending = sortState[col]

    # Extract rows in main thread (fast, just text)
    numRows = table.rowCount()
    rows = []

    for rowIDx in range(numRows):
        timestamp = table.verticalHeaderItem(rowIDx).text() if table.verticalHeaderItem(rowIDx) else ''  # From vertical
        rowData = [table.item(rowIDx, c).text() if table.item(rowIDx, c) else '' for c in range(table.columnCount())]
        rows.append([timestamp] + rowData)  # Timestamp first

    # Start pooled worker (auto-managed, no destroy warning)
    pool = QThreadPool.globalInstance()
    worker = sortWorker(rows, col, ascending)
    worker.signals.sortDone.connect(lambda sortedRows, asc: updateTableAfterSort(table, sortedRows, asc, dataDictionaryTable, col))
    pool.start(worker)

    # Set sort indicator immediately (UI feedback)
    header.setSortIndicator(col, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)

def updateTableAfterSort(table, sortedRows, ascending, dataDictionaryTable, col):
    # Re-populate on main thread
    table.setSortingEnabled(False)  # Disable default sort
    numRows = len(sortedRows)

    for rowIDx, row in enumerate(sortedRows):
        # Vertical: Timestamp
        table.setVerticalHeaderItem(rowIDx, QTableWidgetItem(row[0]))

        # Data cols
        for c in range(table.columnCount()):
            cellText = row[c + 1]
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(rowIDx, c, item)

    # Lock widths before QAQC (no reflow/shift)
    for c in range(table.columnCount()):
        table.setColumnWidth(c, table.columnWidth(c))  # Lock current

    # Re-apply QAQC colors
    headerLabels = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    data_id = [label.split('\n')[-1].strip() for label in headerLabels]  # Last line = raw ID
    qaqc(table, dataDictionaryTable, data_id)

    # Re-freeze col 0 (locked, no resize)
    table.setColumnWidth(0, 150)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.setViewportMargins(150, 0, 0, 0)

    # Re-enable selection (after sort, for normal use)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    # No resize here—locked prevents shift

class sortWorkerSignals(QObject):
    sortDone = pyqtSignal(list, bool)

class sortWorker(QRunnable):
    def __init__(self, rows, col, ascending):
        super(sortWorker, self).__init__()
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

def centerWindowToParent(ui):
    """Center a window relative to its parent (main window), robust for multi-monitor."""
    parent = ui.parent()

    if parent:
        # Get parent's screen for centering (multi-monitor aware)
        parentCenterPoint = parent.geometry().center()
        parentScreen = QGuiApplication.screenAt(parentCenterPoint)

        # Use parent's frame center for precise relative positioning
        parentCenter = parent.frameGeometry().center()

        # Fallback if null (invalid)
        if parentCenter.isNull():
            if parentScreen:
                parentCenter = parentScreen.availableGeometry().center()
            else:
                parentCenter = QGuiApplication.primaryScreen().availableGeometry().center()
    else:
        # No parent: Center on primary
        parentCenter = QGuiApplication.primaryScreen().availableGeometry().center()
    
    # Center child's frame on parent's center
    rect = ui.frameGeometry()
    rect.moveCenter(parentCenter)
    ui.move(rect.topLeft())

def buttonStyle(button):
    """Apply flat, borderless style to a QPushButton with no hover/press effects."""
    button.setStyleSheet("""
        QPushButton {
            border: none;
            background: transparent;
        }
        QPushButton:hover {
            background: transparent;
        }
        QPushButton:pressed {
            background: transparent;
            border: none;
        }
        QPushButton:focus {
            outline: none;
        }
    """)