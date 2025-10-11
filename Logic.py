import os
import sys
import datetime
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QTimer, QByteArray
from PyQt6.QtGui import QGuiApplication, QColor, QBrush
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog

sortState = {} # Global dict for per-col sort state (col: ascending)

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
        ts = current.strftime('%m/%d/%y %H:%M:00')
        timestamps.append(ts)
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
    removed = [] # Collect details for warn
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
        return data # Mismatch—skip

    for d in range(len(newData)):
        parseLine = newData[d].split(',')
        data[d] = f'{data[d]},{parseLine[1]}'

    return data

def buildTable(table, data, buildHeader, dataDictionaryTable, intervals, lookupIds=None):
    table.clear()
    
    if not data:
        return  
  
    # Assume buildHeader is list; split if str
    if isinstance(buildHeader, str):
        buildHeader = [h.strip() for h in buildHeader.split(',')]
    
    # Build prateOfChangeessed headers with dict lookup and \nINTERVAL
    prateOfChangeessedHeaders = []

    for i, h in enumerate(buildHeader):
        headerText = h.strip() # Strip raw header
        intervalStr = intervals[i].upper()
        
        dictRow = getDataDictionaryItem(dataDictionaryTable, headerText)

        if dictRow != -1:
            siteItem = dataDictionaryTable.item(dictRow, 1) # Site col1
            datatypeItem = dataDictionaryTable.item(dictRow, 2) # Datatype col2
            baseLabel = (siteItem.text().strip() + ' ' + datatypeItem.text().strip()) if siteItem and datatypeItem else headerText
        else:
            baseLabel = headerText
        
        fullLabel = baseLabel + ' \n' + intervalStr

        if dictRow != -1:
            fullLabel += ' \n' + h

        prateOfChangeessedHeaders.append(fullLabel)
    
    # Headers: PrateOfChangeessed only (no Date prepend)
    headers = prateOfChangeessedHeaders
    
    # Conditional skip for main table (skip date col 0)
    skipDateCol = dataDictionaryTable is not None  # True for main (has dict), False for dict itself? Wait, adjust if needed - assuming dataDictionaryTable is passed for main, None or False for others
    
    numCols = len(headers)
    numRows = len(data)
    table.setRowCount(numRows)
    table.setColumnCount(numCols)
    table.setHorizontalHeaderLabels(headers) # Full list
    
    # Vertical: Timestamps for main table only (dict table no dates)
    if dataDictionaryTable:
        timestamps = [row.split(',')[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        table.verticalHeader().setMinimumWidth(120)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(True)
    else:
        table.verticalHeader().setVisible(False) # Hide for dict
    
    # Populate data (conditional skip, center all)
    for rowIDx, row_str in enumerate(data):
        rowData = row_str.split(',')[1:] if skipDateCol else row_str.split(',') # Skip date for main
        
        for colIDx in range(min(numCols, len(rowData))):
            cellText = rowData[colIDx].strip() if colIDx < len(rowData) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(rowIDx, colIDx, item)
    
    # Resize all columns to fit headers + data
    for col in range(numCols):
        table.resizeColumnToContents(col)
    
    # dataIds for QAQC: raw buildHeader
    dataIds = buildHeader
    
    # QAQC colors
    qaqc(table, dataDictionaryTable, dataIds)
    
    # Warm-up dummy sort to trigger initial reflow (no shift on first real click)
    header = table.horizontalHeader()
    table.setSortingEnabled(False) # Disable for dummy
    QTimer.singleShot(0, lambda: [
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder), # Dummy ASC on col 0
        table.sortItems(0, Qt.SortOrder.AscendingOrder), # Dummy sort (no change)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder), # Clear with ASC
        table.setSortingEnabled(True) # Re-enable
    ])  
    
    # Connect custom sort (syncs timestamps)
    table.horizontalHeader().sectionClicked.connect(lambda col: customSortTable(table, col, dataDictionaryTable))
    
def buildDataDictionary(table):
    table.clear()

    with open(resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
        data = [line.strip().split(',') for line in f.readlines()]
    
    if not data:
        return
    
    table.setRowCount(len(data) - 1) # Skip header
    table.setColumnCount(len(data[0]))
    
    # Set headers
    for c, header in enumerate(data[0]):
        item = QTableWidgetItem(header.strip())
        table.setHorizontalHeaderItem(c, item)
    
    # Populate, trim spaces
    for r in range(1, len(data)):
        for c in range(len(data[r])):
            value = data[r][c].strip()
            item = QTableWidgetItem(value)
            table.setItem(r-1, c, item)

def getDataDictionaryItem(table, dataId):
    for r in range(table.rowCount()):
        item = table.item(r, 0)

        if item and item.text().strip() == dataId.strip():
            return r
            
    return -1 # Not found

def qaqc(table, dataDictionaryTable, lookupIds):
    if not dataDictionaryTable:
        return
    
    for col, lookupId in enumerate(lookupIds):
        rowIndex = getDataDictionaryItem(dataDictionaryTable, lookupId)

        if rowIndex == -1:
            continue # Skip QAQC for non-dict
        
        # Expected min/max etc. (with strip)
        expectedMin = None
        expectedMinItem = dataDictionaryTable.item(rowIndex, 3)
        
        if expectedMinItem and expectedMinItem.text().strip():
            expectedMin = float(expectedMinItem.text().strip())
        
        expectedMax = None
        expectedMaxItem = dataDictionaryTable.item(rowIndex, 4)

        if expectedMaxItem and expectedMaxItem.text().strip():
            expectedMax = float(expectedMaxItem.text().strip())
        
        cutoffMin = None
        cutoffMinItem = dataDictionaryTable.item(rowIndex, 5)

        if cutoffMinItem and cutoffMinItem.text().strip():
            cutoffMin = float(cutoffMinItem.text().strip())
        
        cutoffMax = None
        cutoffMaxItem = dataDictionaryTable.item(rowIndex, 6)

        if cutoffMaxItem and cutoffMaxItem.text().strip():
            cutoffMax = float(cutoffMaxItem.text().strip())
        
        rateOfChange = None
        rateOfChangeItem = dataDictionaryTable.item(rowIndex, 7)

        if rateOfChangeItem and rateOfChangeItem.text().strip():
            rateOfChange = float(rateOfChangeItem.text().strip())
        
        # Iterate over rows for colors
        prevVal = None

        for r in range(table.rowCount()):
            item = table.item(r, col)
            if not item:
                continue
            
            cellText = item.text().strip()

            if cellText == '': # Missing data blue (only if in dict)
                item.setBackground(QColor(100, 195, 247)) # Light blue
                continue
            
            try:
                val = float(cellText)
            except ValueError:
                continue # Skip non-numeric
            
            # Min/Max colors
            if expectedMin is not None and val < expectedMin:
                item.setBackground(QColor(249, 240, 107)) # Light Yellow                              
            elif expectedMax is not None and val > expectedMax:
                item.setBackground(QColor(249, 194, 17)) # Yellow
            elif cutoffMin is not None and val < cutoffMin:
                item.setBackground(QColor(255, 163, 72)) # Orange
            elif cutoffMax is not None and val > cutoffMax:
                item.setBackground(QColor(192, 28, 40)) # Red
            
            # Rate of change
            if rateOfChange is not None and prevVal is not None:
                if abs(val - prevVal) > rateOfChange:
                    item.setBackground(QColor(246, 97, 81)) # Red

            # Repeat (green)
            if prevVal is not None and val == prevVal:
                item.setBackground(QColor(87, 227, 137)) # Green                

            prevVal = val         
           
def loadAllQuickLooks(cbQuickLook):     
    cbQuickLook.clear()
    cbQuickLook.addItem(None) # Blank first

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
    os.makedirs(os.path.dirname(quicklook_path), exist_ok=True) # Ensure dir

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
    config = ['light'] # Default color
    configPath = resourcePath('config.ini')

    try:
        with open(configPath, 'r', encoding='utf-8-sig') as f:
            config = [line.strip() for line in f.readlines()]

            if not config: # Empty file
                config = ['light']

    except FileNotFoundError:
        # Create if missing
        with open(configPath, 'w', encoding='utf-8-sig') as f:
            f.write('light\n')
            
    # Ensure path entry (index 1)
    while len(config) < 2:
        config.append('') # Empty path default

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
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.join(defaultDir, defaultName)
    filePath, _ = QFileDialog.getSaveFileName(None, "Save CSV As", suggestedPath, "CSV files (*.csv)")

    if not filePath:
        return # User canceled

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
    exportDir = os.path.dirname(filePath)

    if len(config) < 2:
        config.append(exportDir) # Extend if short
    else:
        config[1] = exportDir # Assign
    with open(resourcePath('config.ini'), 'w', encoding='utf-8-sig') as f:
        f.write(f"{config[0]}\n{exportDir}\n") # color\npath

    print(f"Exported to {filePath}")

def resourcePath(relativePath):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False): # Bundled mode
        basePath = sys._MEIPASS
    else: # Dev mode
        basePath = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(basePath, relativePath))

def customSortTable(table, col, dataDictionaryTable):
    # Prevent overlap (ignore if sorting already)
    pool = QThreadPool.globalInstance()

    if pool.activeThreadCount() > 0:
        return # Skip during sort

    # Disable selection highlight during sort
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    # Clear indicator to stop Qt double-trigger
    header = table.horizontalHeader()
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder) # Clear (safe enum)

    # Toggle sort order (per-col state)
    if col not in sortState:
        sortState[col] = True # Default ASC for new col
    else:
        sortState[col] = not sortState[col] # Flip on every click
    ascending = sortState[col]

    # Extract rows in main thread (fast, just text)
    numRows = table.rowCount()
    rows = []

    for rowIDx in range(numRows):
        timestamp = table.verticalHeaderItem(rowIDx).text() if table.verticalHeaderItem(rowIDx) else '' # From vertical
        rowData = [table.item(rowIDx, c).text() if table.item(rowIDx, c) else '' for c in range(table.columnCount())]
        rows.append([timestamp] + rowData) # Timestamp first

    # Start pooled worker (auto-managed, no destroy warning)
    pool = QThreadPool.globalInstance()
    worker = sortWorker(rows, col, ascending)
    worker.signals.sortDone.connect(lambda sortedRows, asc: updateTableAfterSort(table, sortedRows, asc, dataDictionaryTable, col))
    pool.start(worker)

    # Set sort indicator immediately (UI feedback)
    header.setSortIndicator(col, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)

def updateTableAfterSort(table, sortedRows, ascending, dataDictionaryTable, col):
    # Re-populate on main thread
    table.setSortingEnabled(False) # Disable default sort
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
        table.setColumnWidth(c, table.columnWidth(c)) # Lock current

    # Re-apply QAQC colors
    headerLabels = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    dataID = [label.split('\n')[-1].strip() for label in headerLabels] # Last line = raw ID
    qaqc(table, dataDictionaryTable, dataID)

    # Re-freeze col 0 (locked, no resize)
    table.setColumnWidth(0, 150)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.setViewportMargins(150, 0, 0, 0)

    # Re-enable selection (after sort, for normal use)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

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