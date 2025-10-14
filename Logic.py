import os
import sys
import datetime
import configparser
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QTimer, QByteArray, QStandardPaths
from PyQt6.QtGui import QGuiApplication, QColor, QBrush, QStyleHints, QFontDatabase, QFont
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QWidget, QTreeView, QSplitter

def resourcePath(relativePath):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False): # Bundled mode
        basePath = sys._MEIPASS
    else: # Dev mode
        basePath = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(basePath, relativePath))

appRoot = resourcePath('') 
sortState = {} 
utcOffset = "" 
debug = False
retroFont = False
qaqcEnabled = True
rawData = False
fontSize = 10 # Default app-wide retro font size

def buildTimestamps(startDateStr, endDateStr, intervalStr):
    if debug == True: print("[DEBUG] buildTimestamps called with start: {}, end: {}, interval: {}".format(startDateStr, endDateStr, intervalStr))

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
    
    if debug == True: print("[DEBUG] Generated {} timestamps, sample first 3: {}".format(len(timestamps), timestamps[:3]))

    return timestamps

def gapCheck(timestamps, data, dataID=''):
    if debug == True: print("[DEBUG] gapCheck for dataID '{}': timestamps len={}, data len={}".format(dataID, len(timestamps), len(data)))

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
        if debug == True: print("[DEBUG] Removed {} extra/mismatched rows from '{}': ts {}".format(len(removed), dataID, removed))

    if debug == True: print("[DEBUG] Post-gapCheck len={}, sample first 3: {}".format(len(newData), newData[:3]))

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
    
    # Build processed headers
    processedHeaders = []

    for i, h in enumerate(buildHeader):
        headerText = h.strip() # Strip raw header
        intervalStr = intervals[i].upper()
        
        dictRow = getDataDictionaryItem(dataDictionaryTable, headerText)

        if dictRow != -1:
            siteItem = dataDictionaryTable.item(dictRow, 1) 
            datatypeItem = dataDictionaryTable.item(dictRow, 2) 
            baseLabel = (siteItem.text().strip() + ' ' + datatypeItem.text().strip()) if siteItem and datatypeItem else headerText
        else:
            baseLabel = headerText
        
        fullLabel = baseLabel + ' \n' + intervalStr

        if dictRow != -1:
            fullLabel += ' \n' + h

        processedHeaders.append(fullLabel)
    
    # Headers: Processed only (no Date prepend)
    headers = processedHeaders
    
    # Conditional skip for main table (skip date col 0)
    skipDateCol = dataDictionaryTable is not None  # True for main (has dict), False for dict itself
    
    numCols = len(headers)
    numRows = len(data)
    table.setRowCount(numRows)
    table.setColumnCount(numCols)
    table.setHorizontalHeaderLabels(headers)
    
    # Vertical: Timestamps for main table only (dict table no dates)
    if dataDictionaryTable:
        timestamps = [row.split(',')[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        table.verticalHeader().setMinimumWidth(120)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(True)
    else:
        table.verticalHeader().setVisible(False) # Hide for dict
    
    # Load config once outside loop
    config = configparser.ConfigParser()
    config.read(getConfigPath())
    rawData = config['Settings'].getboolean('rawData', False) if 'Settings' in config else False
    qaqcToggle = config['Settings'].getboolean('qaqc', True) if 'Settings' in config else True
    
    # Populate data (conditional skip, center all)
    for rowIDx, row_str in enumerate(data):
        rowData = row_str.split(',')[1:] if skipDateCol else row_str.split(',') # Skip date for main
        
        for colIDx in range(min(numCols, len(rowData))):
            cellText = rowData[colIDx].strip() if colIDx < len(rowData) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

            if not rawData and cellText.strip(): # Apply formatting if not raw
                item.setText(valuePrecision(cellText))

            table.setItem(rowIDx, colIDx, item)
    
    # Resize all columns to fit headers + data
    for col in range(numCols):
        table.resizeColumnToContents(col)
    
    # dataIds for QAQC: raw buildHeader
    dataIds = buildHeader
    
    # Apply QAQC if toggled
    if qaqcToggle:
        qaqc(table, dataDictionaryTable, dataIds)
    else:
        # Clear colors if off (transparent for stylesheet)
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)

                if item:
                    item.setBackground(QColor(0, 0, 0, 0)) # Transparent

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
    
    now = datetime.now() # Current time for future check
    
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
            
            # Reset foreground to system default first
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            
            cellText = item.text().strip()

            if cellText == '': # Missing data blue (only if in dict and ts <= now)
                tsItem = table.verticalHeaderItem(r)

                if tsItem:
                    tsStr = tsItem.text()

                    try:
                        tsDt = datetime.strptime(tsStr, '%m/%d/%y %H:%M:00')

                        if tsDt <= now:
                            item.setBackground(QColor(100, 195, 247)) # Light blue for past/present missing
                    except ValueError:
                        pass # Skip invalid ts
                continue
            
            try:
                val = float(cellText)
            except ValueError:
                continue # Skip non-numeric
            
            # Min/Max colors (apply regardless of ts, for model future data)
            if expectedMin is not None and val < expectedMin:
                item.setBackground(QColor(249, 240, 107)) # Light Yellow  
                item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(QColor(0, 0, 0))) # Black text                            
            elif expectedMax is not None and val > expectedMax:
                item.setBackground(QColor(249, 194, 17)) # Yellow
                item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(QColor(0, 0, 0))) # Black text  
            elif cutoffMin is not None and val < cutoffMin:
                item.setBackground(QColor(255, 163, 72)) # Orange
            elif cutoffMax is not None and val > cutoffMax:
                item.setBackground(QColor(192, 28, 40)) # Red
            
            # Rate of change (apply regardless)
            if rateOfChange is not None and prevVal is not None:
                if abs(val - prevVal) > rateOfChange:
                    item.setBackground(QColor(246, 97, 81)) # Red

            # Repeat (apply regardless)
            if prevVal is not None and val == prevVal:
                item.setBackground(QColor(87, 227, 137)) # Green 
                item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(QColor(0, 0, 0))) # Black text                

            prevVal = val                 
           
def loadAllQuickLooks(cbQuickLook):     
    cbQuickLook.clear()
    quickLookPaths = []

    # User-specific first
    userDir = getQuickLookDir()

    for file in os.listdir(userDir):
        if file.endswith(".txt"):
            quickLookPaths.append(os.path.join(userDir, file))

    # Then append examples (no duplicates – check names)
    exampleDir = getExampleQuickLookDir()

    for file in os.listdir(exampleDir):
        if file.endswith(".txt"):
            examplePath = os.path.join(exampleDir, file)

            if not os.path.exists(os.path.join(userDir, file)): # Avoid dupes
                quickLookPaths.append(examplePath)
    
    # Add to combo (use basename without .txt)
    for path in quickLookPaths:
        name = os.path.basename(path).replace('.txt', '')
        cbQuickLook.addItem(name)
                  
def saveQuickLook(textQuickLookName, listQueryList):
    name = textQuickLookName.toPlainText().strip() if hasattr(textQuickLookName, 'toPlainText') else str(textQuickLookName).strip()

    if not name:
        print("Warning: Empty quick look name—skipped.")
        return

    data = [listQueryList.item(x).text() for x in range(listQueryList.count())]
    quicklookPath = os.path.join(getQuickLookDir(), f'{name}.txt')
    os.makedirs(os.path.dirname(quicklookPath), exist_ok=True) # Ensure dir

    with open(quicklookPath, 'w', encoding='utf-8-sig') as f:
        f.write(','.join(data))

def loadQuickLook(cbQuickLook, listQueryList):
    name = cbQuickLook.currentText()

    if not name:
        return

    quicklookPath = resourcePath(f'quickLook/{name}.txt')
    listQueryList.clear()

    try:
        with open(quicklookPath, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()

            if content:
                data = content.split(',')
                for item_text in data:
                    listQueryList.addItem(item_text.strip())

    except FileNotFoundError:
        print(f"Quick look '{name}' not found.")  

def loadConfig():
    configPath = getConfigPath()
    config = configparser.ConfigParser()
    config.read(configPath)

    # Defaults
    settings = {
        'colorMode': 'light',
        'lastExportPath': '',
        'debugMode': False,
        'utcOffset': -7, # Default int
        'periodOffset': True, # True for EOP/end
        'retroFont': True,
        'qaqc': True,
        'rawData': False,
        'lastQuickLook': ''
    }

    if 'Settings' in config:
        settings['colorMode'] = config['Settings'].get('colorMode', 'light')
        settings['lastExportPath'] = config['Settings'].get('lastExportPath', '')
        settings['debugMode'] = config['Settings'].getboolean('debugMode', False)
        utcStr = config['Settings'].get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, \nLisbon, London")

        # Parse utcOffset to int (e.g., -7 from "UTC-07:00 | ...")
        try:
            offsetPart = utcStr.split(' | ')[0].replace('UTC', '').split(':')[0] # " -07" or "+00"
            settings['utcOffset'] = int(offsetPart)
        except ValueError:
            settings['utcOffset'] = -7 # Fallback
        hourMethod = config['Settings'].get('hourTimestampMethod', 'EOP')
        settings['periodOffset'] = (hourMethod == 'EOP') # True for end
        settings['retroFont'] = config['Settings'].getboolean('retroFont', True)
        settings['qaqc'] = config['Settings'].getboolean('qaqc', True)
        settings['rawData'] = config['Settings'].getboolean('rawData', False)
        settings['lastQuickLook'] = config['Settings'].get('lastQuickLook', '')

    # Create if missing/empty
    if not os.path.exists(configPath) or not config.sections():
        config['Settings'] = {
            'colorMode': settings['colorMode'],
            'lastExportPath': settings['lastExportPath'],
            'debugMode': str(settings['debugMode']),
            'utcOffset': "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, \nLisbon, London",
            'hourTimestampMethod': 'EOP' if settings['periodOffset'] else 'BOP',
            'retroFont': str(settings['retroFont']),
            'qaqc': str(settings['qaqc']),
            'rawData': str(settings['rawData']),
            'lastQuickLook': settings['lastQuickLook']
        }
        with open(configPath, 'w') as configFile:
            config.write(configFile)

    return settings

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        print("Empty table—no export.")
        return

    # Get last path from config (default to Documents)
    config = configparser.ConfigParser()
    config.read(getConfigPath())
    lastPath = config['Settings'].get('lastExportPath', os.path.expanduser("~/Documents")) if 'Settings' in config else os.path.expanduser("~/Documents")

    # Force Documents if lastPath empty/invalid
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.expanduser("~/Documents")

    defaultDir = lastPath

    # Timestamped default name (yyyy-mm-dd HH:mm:ss Export.csv)
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.join(defaultDir, defaultName)

    # Instantiate dialog for control (non-static)
    dlg = QFileDialog(None)
    dlg.setWindowTitle("Save CSV As")
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setNameFilter("CSV files (*.csv)")
    dlg.selectFile(defaultName)
    dlg.setDirectory(defaultDir)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True) # Force Qt-based for font control (cross-platform)

    if retroFont:
        applyRetroFont(dlg, 9) # Apply smaller retro font recursively
        dlg.resize(800, 600) # Set custom size only for retro
        dlg.setViewMode(QFileDialog.ViewMode.Detail) # Ensure details view for columns
        
        # Force sidebar width via splitter (adjust 150 as needed for your font/setup)
        splitter = dlg.findChild(QSplitter)
        if splitter:
            splitter.setSizes([150, dlg.width() - 150]) # Sidebar 150px, main the rest
        
        # Optional: Auto-resize main view columns (sidebar fixed, so skipped for it)
        mainView = dlg.findChild(QTreeView, "fileview") # Main view (may vary; fallback to first)

        if not mainView:
            mainView = dlg.findChild(QTreeView) # Fallback if named differently
        if mainView:
            header = mainView.header()

            for i in range(header.count()):
                mainView.resizeColumnToContents(i) # Auto-size main columns

    if dlg.exec():
        filePath = dlg.selectedFiles()[0]
    else:
        return # User canceled

    # Build CSV
    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = [',Timestamp,' + ','.join(headers)] # Header with Timestamp

    # Add timestamps as first column
    timestamps = [table.verticalHeaderItem(r).text() if table.verticalHeaderItem(r) else '' for r in range(table.rowCount())]
    
    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(timestamps[r] + ',' + ','.join(rowData))

    # Write
    with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(csvLines))

    # Save last path to config (dir only, preserve others)
    exportDir = os.path.dirname(filePath)
    if 'Settings' not in config:
        config['Settings'] = {}

    config['Settings']['lastExportPath'] = exportDir

    with open(getConfigPath(), 'w') as configFile:
        config.write(configFile) 

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

def getExampleQuickLookDir():
    return resourcePath("quickLook") 

def getConfigDir():
    configDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)

    if not os.path.exists(configDir):
        os.makedirs(configDir)

    return configDir

def getConfigPath():
    return os.path.join(getConfigDir(), "config.ini")

def getQuickLookDir():
    quickLookDir = os.path.join(getConfigDir(), "quickLook")

    if not os.path.exists(quickLookDir):
        os.makedirs(quickLookDir)

    return quickLookDir

def reloadGlobals():
    settings = loadConfig()
    global debug, utcOffset, periodOffset, retroFont, qaqcEnabled, rawData  # Globals
    debug = settings['debugMode']
    utcOffset = settings['utcOffset']
    periodOffset = settings['periodOffset'] # Use in USBR as needed (e.g., if periodOffset: end else begin)
    retroFont = settings['retroFont']
    qaqcEnabled = settings['qaqc']
    rawData = settings['rawData']

def applyRetroFont(widget, pointSize=10):
    fontPath = resourcePath('ui/fonts/PressStart2P-Regular.ttf') # Load from path
    fontId = QFontDatabase.addApplicationFont(fontPath)

    if fontId != -1:
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
        retroFontObj = QFont(fontFamily, pointSize)
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing for crisp retro
        widget.setFont(retroFontObj)
        for child in widget.findChildren(QWidget): # Recursive to all children
            child.setFont(retroFontObj)

def valuePrecision(value):
    """Format value to 2 decimals if <10, 1 if 10-99, 0 if >=100."""
    try:
        v = float(value)

        if v < 1000:
            return '%.2f' % v
        elif 1000 <= v < 10000:
            return '%.1f' % v
        else:
            return '%.0f' % v
    except ValueError:
        return value # Non-numeric as-is

def cleanShutdown():
    pool = QThreadPool.globalInstance()
    pool.waitForDone(5000) # Wait up to 5s for threads to finish (adjust if needed)