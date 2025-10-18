import os
import sys
import datetime
import configparser
import QueryUSBR
import QueryUSGS
import QueryAquarius
import json
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QStandardPaths, QDir, QTimer
from PyQt6.QtGui import QGuiApplication, QColor, QBrush, QFontDatabase, QFont, QFontMetrics
from PyQt6.QtWidgets import (QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QWidget, 
                            QTreeView, QSplitter, QMessageBox, QStyleOptionHeader, QSizePolicy,
                            QHeaderView)
from collections import defaultdict

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

def buildTable(table, data, buildHeader, dataDictionaryTable, intervals, lookupIds=None, labelsDict=None):
    table.clear()

    if not data:
        if debug: print("[DEBUG] buildTable: No data to display.")
        return

    if isinstance(buildHeader, str):
        buildHeader = [h.strip() for h in buildHeader.split(',')]

    processedHeaders = []

    for i, h in enumerate(buildHeader):
        dataID = h.strip()
        intervalStr = intervals[i].upper()
        dictRow = getDataDictionaryItem(dataDictionaryTable, lookupIds[i] if lookupIds else dataID)

        if dictRow != -1:
            siteItem = dataDictionaryTable.item(dictRow, 1)
            datatypeItem = dataDictionaryTable.item(dictRow, 2)
            baseLabel = (siteItem.text().strip() + ' ' + datatypeItem.text().strip()) if siteItem and datatypeItem else dataID
            fullLabel = baseLabel + ' \n' + intervalStr + ' \n' + dataID
        else:
            if labelsDict and dataID in labelsDict and 'AQUARIUS' in (dataDictionaryTable.parent().objectName() if dataDictionaryTable else ''):
                apiFull = labelsDict[dataID]
                parts = apiFull.split('\n')

                if len(parts) >= 2:
                    label, location = parts[1].strip(), parts[0].strip()
                    fullLabel = label + ' \n' + location + ' \n' + dataID
                else:
                    fullLabel = dataID + ' \n' + intervalStr
            else:
                fullLabel = dataID + ' \n' + intervalStr

        processedHeaders.append(fullLabel)

    headers = processedHeaders
    skipDateCol = dataDictionaryTable is not None
    numCols = len(headers)
    numRows = len(data)
    table.setRowCount(numRows)
    table.setColumnCount(numCols)
    table.setHorizontalHeaderLabels(headers)

    if dataDictionaryTable:
        timestamps = [row.split(',')[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        vHeader = table.verticalHeader()
        vHeader.setMinimumWidth(120)
        vHeader.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vHeader.setVisible(True)
    else:
        table.verticalHeader().setVisible(False)
    config = loadConfig()
    rawData = config.get('rawData', False)
    qaqcToggle = config.get('qaqc', True)

    for rowIdx, rowStr in enumerate(data):
        rowData = rowStr.split(',')[1:] if skipDateCol else rowStr.split(',')

        for colIdx in range(min(numCols, len(rowData))):
            cellText = rowData[colIdx].strip() if colIdx < len(rowData) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

            if not rawData and cellText.strip():
                item.setText(valuePrecision(cellText))
            table.setItem(rowIdx, colIdx, item)

    # Ensure sort connection is set early
    table.horizontalHeader().sectionClicked.connect(lambda col: customSortTable(table, col, dataDictionaryTable))

    # Custom auto-size for columns based on data and header character count
    font = table.font()
    metrics = QFontMetrics(font)
    header = table.horizontalHeader()
    vHeader = table.verticalHeader()
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setMinimumSize(0, 0)
    table.resize(table.size())
    table.update()

    # Set vertical header minimum with padding
    if dataDictionaryTable:
        maxTimeWidth = max(metrics.horizontalAdvance(ts) for ts in timestamps)
        vHeader.setMinimumWidth(max(120, maxTimeWidth) + 10)

    # Set column widths based on max of cell content and header character count
    charToPx = 8 # Approx pixels per char for 12pt font

    for c in range(numCols):
        cellValues = [row.split(',')[c+1].strip() if c+1 < len(row.split(',')) else "0.00" for row in data]
        maxCellWidth = max(metrics.horizontalAdvance(val) for val in cellValues) if cellValues else 50

        # Calculate header width based on max character count per line
        headerLines = headers[c].split('\n')
        maxHeaderLen = max(len(line) for line in headerLines) if headerLines else 0
        headerWidth = maxHeaderLen * charToPx

        # Adjust max width
        finalWidth = max(maxCellWidth, headerWidth)

        if headerWidth > maxCellWidth:
            paddingIncrease = headerWidth - maxCellWidth
            finalWidth = maxCellWidth + paddingIncrease
        else:
            finalWidth = maxCellWidth + 15

        table.setColumnWidth(c, finalWidth)

    # Set row heights based on font metrics with dynamic adjustment
    rowHeight = metrics.height() + 10
    sampleItem = QTableWidgetItem("189.5140")
    sampleItem.setFont(font)
    sampleCellHeight = sampleItem.sizeHint().height()

    if sampleCellHeight <= 0:
        sampleCellHeight = metrics.height()

    tallestCellHeight = 0

    for r in range(numRows):
        for c in range(numCols):
            item = table.item(r, c)

            if item and item.text().strip():
                height = item.sizeHint().height()

                if height > 0:
                    tallestCellHeight = max(tallestCellHeight, height)
    if tallestCellHeight == 0:
        tallestCellHeight = metrics.height()

    adjustedRowHeight = max(rowHeight, tallestCellHeight + 2)
    
    if debug: print(f"[DEBUG] Sample cell height: {sampleCellHeight}, Tallest cell height: {tallestCellHeight}")

    for r in range(numRows):
        table.setRowHeight(r, adjustedRowHeight)

    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    vHeader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.update()
    table.horizontalScrollBar().setValue(0)
    visibleWidth = table.columnWidth(1)

    if debug: print(f"[DEBUG] Custom resized {numCols} columns. Text width for col 1: {metrics.horizontalAdvance(headers[1])}, Visible width: {visibleWidth}, Row height: {adjustedRowHeight}")

    dataIds = buildHeader

    if qaqcToggle:
        qaqc(table, dataDictionaryTable, dataIds)
    else:
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item: item.setBackground(QColor(0, 0, 0, 0))
    
def buildDataDictionary(table):
    table.clear() # Clear table

    with open(resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
        data = [line.strip().split(',') for line in f.readlines()] # Read CSV
    if not data:
        if debug: print("[DEBUG] DataDictionary.csv empty")
        return

    table.setRowCount(len(data) - 1) # Skip header
    table.setColumnCount(len(data[0])) # Set columns

    for c, header in enumerate(data[0]):
        item = QTableWidgetItem(header.strip()) # Set header
        table.setHorizontalHeaderItem(c, item)

    for r in range(1, len(data)):
        for c in range(len(data[r])):
            value = data[r][c].strip()
            item = QTableWidgetItem(value) # Set cell
            table.setItem(r-1, c, item)

    for c in range(table.columnCount()):
        table.resizeColumnToContents(c) # Auto-size to header
        
    if debug: print(f"[DEBUG] Built DataDictionary with {table.rowCount()} rows, {table.columnCount()} columns")

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
    quickLookName = cbQuickLook.currentText()

    if not quickLookName:
        return

    listQueryList.clear()
    userQuickLookPath = os.path.join(getQuickLookDir(), f'{quickLookName}.txt')
    exampleQuickLookPath = resourcePath(f'quickLook/{quickLookName}.txt')
    quickLookPath = userQuickLookPath if os.path.exists(userQuickLookPath) else exampleQuickLookPath

    try:
        with open(quickLookPath, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()

            if content:
                data = content.split(',')
                for itemText in data:
                    listQueryList.addItem(itemText.strip())

    except FileNotFoundError:
        print(f"Quick look '{quickLookName}' not found.")

def loadConfig():
    convertConfigToJson() # Convert if needed
    configPath = getConfigPath() # Get JSON path
    settings = {
        'colorMode': 'light',
        'lastExportPath': '',
        'debugMode': False,
        'utcOffset': -7,
        'periodOffset': True,
        'retroFont': True,
        'qaqc': True,
        'rawData': False,
        'lastQuickLook': ''
    }
    if os.path.exists(configPath):
        try:
            with open(configPath, 'r', encoding='utf-8') as configFile:
                config = json.load(configFile) # Read JSON
            settings['colorMode'] = config.get('colorMode', settings['colorMode']) # Load color
            settings['lastExportPath'] = config.get('lastExportPath', settings['lastExportPath']) # Load export path
            settings['debugMode'] = config.get('debugMode', settings['debugMode']) # Load debug
            settings['utcOffset'] = config.get('utcOffset', settings['utcOffset']) # Load UTC

            if isinstance(settings['utcOffset'], str):
                try:
                    offsetPart = settings['utcOffset'].split(' | ')[0].replace('UTC', '').split(':')[0] # Parse UTC
                    settings['utcOffset'] = int(offsetPart)
                except ValueError:
                    settings['utcOffset'] = -7 # Fallback

            settings['periodOffset'] = config.get('hourTimestampMethod', 'EOP') == 'EOP' # Load period
            settings['retroFont'] = config.get('retroFont', settings['retroFont']) # Load retro
            settings['qaqc'] = config.get('qaqc', settings['qaqc']) # Load QAQC
            settings['rawData'] = config.get('rawData', settings['rawData']) # Load raw
            settings['lastQuickLook'] = config.get('lastQuickLook', settings['lastQuickLook']) # Load quick look
            if debug: print("[DEBUG] Loaded settings from user.config")
        except Exception as e:
            if debug: print(f"[ERROR] Failed to load user.config: {e}")
    else:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2) # Write default JSON
        if debug: print("[DEBUG] Created default user.config")
    return settings

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        if debug: print("[DEBUG] exportTableToCSV: Empty table-no export")
        return

    # Get full settings from config (merges defaults, preserves all keys)
    settings = loadConfig()
    if debug: print(f"[DEBUG] exportTableToCSV: Loaded full settings: {settings}")    
    lastPath = settings.get('lastExportPath', os.path.expanduser("~/Documents"))

    # Normalize loaded path to platform slashes/abs (handles cross-save)
    lastPath = os.path.normpath(os.path.abspath(lastPath)) if lastPath else None
    if debug: print(f"[DEBUG] exportTableToCSV: Normalized lastPath: {lastPath}")

    # Force Documents if lastPath exmpty/invalid
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.normpath(os.path.expanduser("~/Documents"))
        if debug: print("[DEBUG] exportTableToCSV: Used fallback Documents path")

    defaultDir = lastPath

    # Timestamped default name (yyyy-mm-dd HH:mm:ss Export.csv)
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.normpath(os.path.join(defaultDir, defaultName))
    if debug: print(f"[DEBUG] exportTableToCSV: Suggested path: {suggestedPath}")

    # Instantiate dialog for control (non-static)
    dlg = QFileDialog(None)
    dlg.setWindowTitle("Save CSV As")
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setNameFilter("CSV files (*.csv)")
    dlg.selectFile(defaultName)
    dlg.setDirectory(QDir.fromNativeSeparators(defaultDir))  
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True) # Force Qt-based for font control (cross-platform)

    if retroFont:
        applyRetroFont(dlg, 9) # Apply smaller retro font recursively
        dlg.resize(1200, 600) # Set custom size only for retro
        dlg.setViewMode(QFileDialog.ViewMode.Detail) # Ensure details view for columns
        
        # Force sidebar width via splitter (adjust 150 as needed for your font/setup)
        splitter = dlg.findChild(QSplitter)

        if splitter:
            splitter.setSizes([150, dlg.width() - 150]) # Sidebar 150px, main the rest
            if debug: print("[DEBUG] exportTableToCSV: Adjusted splitter sizes")
        
        # Optional: Auto-resize main view columns (sidebar fixed, so skipped for it)
        mainView = dlg.findChild(QTreeView, "fileview") # Main view (may vary; fallback to first)

        if not mainView:
            mainView = dlg.findChild(QTreeView) # Fallback if named differently
        if mainView:
            header = mainView.header()

            for i in range(header.count()):                        
                mainView.resizeColumnToContents(i) # Auto-size main columns                
            if debug: print("[DEBUG] exportTableToCSV: Resized main view columns")

    if dlg.exec():
        filePath = dlg.selectedFiles()[0]
        if debug: print(f"[DEBUG] exportTableToCSV: User canceled dialog")
    else:
        return # User canceled

    # Build CSV
    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = ['Date/Time,' + ','.join(headers)] # Header with Timestamp
    if debug: print(f"[DEBUG] exportTableToCSV: Built headers: {csvLines[0]}")

    # Add timestamps as first column
    timestamps = [table.verticalHeaderItem(r).text() if table.verticalHeaderItem(r) else '' for r in range(table.rowCount())]
    
    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(timestamps[r] + ',' + ','.join(rowData))

    # Write
    try:
        with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\n'.join(csvLines))

        if debug: print(f"[DEBUG] exportTableToCSV: Successfully wrote CSV to {filePath}")
    except Exception as e:
        if debug: print(f"[DEBUG] exportTableToCSV: Failed to write CSV: {e}")
        return

    # Save last path to full settings (dir only, preserve others)
    exportDir = os.path.normpath(os.path.dirname(filePath))
    if debug: print("[DEBUG] exportTableToCSV: Updating lastExportPath to {exportDir}")
    settings['lastExportPath'] = exportDir
    if debug: print("[DEBUG] exportTableToCSV: Full settings after update: {settings}")

    configPath = getConfigPath()

    try:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2)
        if debug: print("[DEBUG] exportTableToCSV: Updated user.config with new lastExportPath-full file preserved")
    except Exception as e:
        if debug: print(f"[DEBUG] exportTableToCSV: Failed to update user.config: {e}")       

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
    table.setSortingEnabled(False)
    numRows = len(sortedRows)
    for rowIdx, row in enumerate(sortedRows):
        table.setVerticalHeaderItem(rowIdx, QTableWidgetItem(row[0]))
        for c in range(table.columnCount()):
            cellText = row[c + 1] if c + 1 < len(row) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(rowIdx, c, item)
    if debug: print("[DEBUG] Updated table after sort; widths not locked.")
    headerLabels = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    dataIds = [label.split('\n')[-1].strip() for label in headerLabels]
    qaqc(table, dataDictionaryTable, dataIds)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

def timestampSortTable(table, dataDictionaryTable):
    if debug: print("[DEBUG] timestampSortTable: Starting sort by timestamps.")
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
    if debug: print("[DEBUG] Timestamp sort worker started.")

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
    configDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation) # Get config dir

    if not os.path.exists(configDir):
        os.makedirs(configDir) # Create if missing
    return os.path.join(configDir, "user.config") # Return JSON config path

def getQuickLookDir():
    quickLookDir = os.path.join(getConfigDir(), "quickLook")

    if not os.path.exists(quickLookDir):
        os.makedirs(quickLookDir)

    return quickLookDir

def reloadGlobals():
    settings = loadConfig() # Load JSON settings
    global debug, utcOffset, periodOffset, retroFont, qaqcEnabled, rawData # Update globals
    debug = settings['debugMode'] # Set debug
    utcOffset = settings['utcOffset'] # Set UTC
    periodOffset = settings['periodOffset'] # Set period
    retroFont = settings['retroFont'] # Set retro
    qaqcEnabled = settings['qaqc'] # Set QAQC
    rawData = settings['rawData'] # Set raw

    if debug: print("[DEBUG] Globals reloaded from user.config")

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

def setQueryDateRange(window, radioButton, dteStartDate, dteEndDate): 
    now = datetime.now()
    
    if radioButton == window.rbCustomDateTime: # Custom: Enable edits, use existing or 72h default
        dteStartDate.setEnabled(True)
        dteEndDate.setEnabled(True)
        if dteStartDate.dateTime() >= dteEndDate.dateTime(): # Ensure valid range
            dteStartDate.setDateTime(now - timedelta(hours=72))
            dteEndDate.setDateTime(now)
    elif radioButton == window.rbPrevDayToCurrent: # Yesterday 01:00 to now
        dteStartDate.setEnabled(False)
        dteEndDate.setEnabled(False)
        yesterday = now - timedelta(days=1)
        dteStartDate.setDateTime(yesterday.replace(hour=1, minute=0, second=0))
        dteEndDate.setDateTime(now)
    elif radioButton == window.rbPrevWeekToCurrent: # 7 days ago 01:00 to now
        dteStartDate.setEnabled(False)
        dteEndDate.setEnabled(False)
        weekAgo = now - timedelta(days=7)
        dteStartDate.setDateTime(weekAgo.replace(hour=1, minute=0, second=0))
        dteEndDate.setDateTime(now)
    else:
        if debug: print("[DEBUG] Unknown radio button in setQueryDateRange")

def setDefaultButton(window, widget, btnAddQuery, btnQuery): 
    if widget == window.qleDataID: # qleDataID focused: Add Query default
        btnAddQuery.setDefault(True)
        btnQuery.setDefault(False)
    else: # Otherwise: Query Data default
        btnAddQuery.setDefault(False)
        btnQuery.setDefault(True)

def convertConfigToJson():
    oldConfigPath = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation), "config.ini") # Old ini path
    newConfigPath = getConfigPath() # New JSON path

    if os.path.exists(oldConfigPath) and not os.path.exists(newConfigPath):
        config = configparser.ConfigParser()
        config.read(oldConfigPath) # Read old ini

        if debug: print("[DEBUG] Found config.ini, converting to user.config")

        settings = {
            'utcOffset': "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London",
            'retroFont': True,
            'qaqc': True,
            'rawData': False,
            'debugMode': False,
            'tnsNamesLocation': '',
            'hourTimestampMethod': 'EOP',
            'lastQuickLook': '',
            'colorMode': 'light',
            'lastExportPath': ''
        }
        if 'Settings' in config:
            settings['utcOffset'] = config['Settings'].get('utcOffset', settings['utcOffset']) # Preserve UTC
            if debug: print(f"[DEBUG] Converted utcOffset: {settings['utcOffset']}")
            settings['retroFont'] = config['Settings'].getboolean('retroFont', settings['retroFont']) # Preserve retro
            if debug: print(f"[DEBUG] Converted retroFont: {settings['retroFont']}")
            settings['qaqc'] = config['Settings'].getboolean('qaqc', settings['qaqc']) # Preserve QAQC
            if debug: print(f"[DEBUG] Converted qaqc: {settings['qaqc']}")
            settings['rawData'] = config['Settings'].getboolean('rawData', settings['rawData']) # Preserve raw
            if debug: print(f"[DEBUG] Converted rawData: {settings['rawData']}")
            settings['debugMode'] = config['Settings'].getboolean('debugMode', settings['debugMode']) # Preserve debug
            if debug: print(f"[DEBUG] Converted debugMode: {settings['debugMode']}")
            settings['tnsNamesLocation'] = config['Settings'].get('tnsNamesLocation', settings['tnsNamesLocation']) # Preserve TNS
            if debug: print(f"[DEBUG] Converted tnsNamesLocation: {settings['tnsNamesLocation']}")
            settings['hourTimestampMethod'] = config['Settings'].get('hourTimestampMethod', settings['hourTimestampMethod']) # Preserve period
            if debug: print(f"[DEBUG] Converted hourTimestampMethod: {settings['hourTimestampMethod']}")
            settings['lastQuickLook'] = config['Settings'].get('lastQuickLook', settings['lastQuickLook']) # Preserve quick look
            if debug: print(f"[DEBUG] Converted lastQuickLook: {settings['lastQuickLook']}")
            settings['colorMode'] = config['Settings'].get('colorMode', settings['colorMode']) # Preserve color
            if debug: print(f"[DEBUG] Converted colorMode: {settings['colorMode']}")
            settings['lastExportPath'] = config['Settings'].get('lastExportPath', settings['lastExportPath']) # Preserve export path
            if debug: print(f"[DEBUG] Converted lastExportPath: {settings['lastExportPath']}")

        with open(newConfigPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2) # Write JSON

        if debug: print("[DEBUG] Converted config.ini to user.config")
    elif debug:
        print("[DEBUG] No config.ini found or user.config exists, skipping conversion")

def initializeQueryWindow(window, rbCustomDateTime, dteStartDate, dteEndDate): 
    rbCustomDateTime.setChecked(True) # Default to custom
    dteStartDate.setEnabled(True) # Enable for custom
    dteEndDate.setEnabled(True)
    dteStartDate.setDateTime(datetime.now() - timedelta(hours=72)) # 72h default
    dteEndDate.setDateTime(datetime.now())

def loadLastQuickLook(cbQuickLook): 
    configPath = getConfigPath() # Get JSON path
    config = {} 

    if os.path.exists(configPath):
        try:
            with open(configPath, 'r', encoding='utf-8') as configFile:
                config = json.load(configFile) # Read JSON
            if debug: print(f"[DEBUG] Loaded config for quick look: {config.get('lastQuickLook', 'none')}")
        except Exception as e:
            if debug: print(f"[DEBUG] Failed to load user.config for quick look: {e}")

    if 'lastQuickLook' in config: # Check saved quick look
        lastQuickLook = config['lastQuickLook']
        index = cbQuickLook.findText(lastQuickLook)
        
        if index != -1: # Set if found
            cbQuickLook.setCurrentIndex(index)
            if debug: print(f"[DEBUG] Set cbQuickLook to index {index}: {lastQuickLook}")
        else:
            if debug: print(f"[DEBUG] Last quick look '{lastQuickLook}' not found, setting to -1")
            cbQuickLook.setCurrentIndex(-1) # Fallback
    else:
        cbQuickLook.setCurrentIndex(-1) # No config, blank

def executeQuery(mainWindow, queryItems, startDate, endDate, isInternal, dataDictionaryTable):
    if debug: print(f"[DEBUG] executeQuery: isInternal={isInternal}, items={len(queryItems)}")

    if isInternal:
        queryItems = [item for item in queryItems if item[2] != 'USGS-NWIS']

        if not queryItems:            
            QMessageBox.warning(mainWindow, "No Valid Items", "No valid internal query items (USGS skipped).")
            return

    queryItems.sort(key=lambda x: x[4])
    firstInterval = queryItems[0][1]
    firstDb = queryItems[0][2]

    if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
        firstInterval = 'HOUR'

    timestamps = buildTimestamps(startDate, endDate, firstInterval)

    if not timestamps:
        QMessageBox.warning(mainWindow, "Date Error", "Invalid dates or interval.")
        return

    defaultBlanks = [''] * len(timestamps)
    labelsDict = {} if isInternal else None
    groups = defaultdict(list)

    for dataID, interval, db, mrid, origIndex in queryItems:
        groupKey = (db, mrid if db.startswith('USBR-') else None, interval)
        SDID = dataID.split('-')[0] if db.startswith('USBR-') and '-' in dataID else dataID
        groups[groupKey].append((origIndex, dataID, SDID))

    valueDict = {}

    for groupKey, groupItems in groups.items():
        db, mrid, interval = groupKey
        SDIDs = [item[2] for item in groupItems]

        try:
            if db.startswith('USBR-'):
                svr = db.split('-')[1].lower()
                table = 'M' if mrid != '0' else 'R'
                result = QueryUSBR.apiRead(svr, SDIDs, startDate, endDate, interval, mrid, table)
            elif db == 'AQUARIUS' and isInternal:
                result = QueryAquarius.apiRead(SDIDs, startDate, endDate, interval)
            elif db == 'USGS-NWIS' and not isInternal:
                result = QueryUSGS.apiRead(SDIDs, interval, startDate, endDate)
            else:
                if debug: print(f"[DEBUG] Unknown db skipped: {db}")
                continue
        except Exception as e:
            QMessageBox.warning(mainWindow, "Query Error", f"Query failed for group {db}: {e}")
            continue
        for idx, (origIndex, dataID, SDID) in enumerate(groupItems):
            if SDID in result:
                if db == 'AQUARIUS':
                    outputData = result[SDID]['data']
                    labelsDict[dataID] = result[SDID].get('label', dataID)
                else:
                    outputData = result[SDID]

                alignedData = gapCheck(timestamps, outputData, dataID)
                values = [line.split(',')[1] if line else '' for line in alignedData]
                valueDict[dataID] = values
            else:
                valueDict[dataID] = defaultBlanks
    originalDataIds = [item[0] for item in queryItems]
    originalIntervals = [item[1] for item in queryItems]
    lookupIds = [item[0].split('-')[0] if item[2].startswith('USBR-') and '-' in item[0] else item[0] for item in queryItems]
    data = []

    for r in range(len(timestamps)):
        rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
        data.append(f"{timestamps[r]},{','.join(rowValues)}")

    mainWindow.mainTable.clear()
    buildTable(mainWindow.mainTable, data, originalDataIds, dataDictionaryTable, originalIntervals, lookupIds, labelsDict)
    
    if mainWindow.tabWidget.indexOf(mainWindow.tabMain) == -1:
        mainWindow.tabWidget.addTab(mainWindow.tabMain, 'Data Query')
    if debug: print("[DEBUG] Query executed and table updated.")