import os
import sys
import datetime
import configparser
import time
import QueryUSBR
import QueryUSGS
import QueryAquarius
import json
import queue
from datetime import datetime, timedelta
from PyQt6.QtCore import (Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QStandardPaths, QDir, QTimer, 
                         QEventLoop, QCoreApplication)
from PyQt6.QtGui import QGuiApplication, QColor, QBrush, QFontDatabase, QFont, QFontMetrics
from PyQt6.QtWidgets import (QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QWidget,
                            QTreeView, QSplitter, QMessageBox, QSizePolicy, QHeaderView, QProgressDialog,
                            QApplication)
                            
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
    if debug: print("[DEBUG] buildTimestamps called with start: {}, end: {}, interval: {}".format(startDateStr, endDateStr, intervalStr))

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

    if debug: print("[DEBUG] Generated {} timestamps, sample first 3: {}".format(len(timestamps), timestamps[:3]))
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

def buildTable(table, data, buildHeader, dataDictionaryTable, intervals, lookupIds=None, labelsDict=None, databases=None):
    if debug: print("[DEBUG] buildTable: Starting with {} rows, {} headers".format(len(data), len(buildHeader)))
    table.clear()

    if not data:
        if debug: print("[DEBUG] buildTable: No data to display.")
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
                    if debug: print(f"[DEBUG] buildTable: USGS in dict, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{baseLabel} \n{intervalStr}"
                    if debug: print(f"[DEBUG] buildTable: USGS in dict but non-USGS format, header {i}: {fullLabel}")

            elif database == 'AQUARIUS' and labelsDict and dataId in labelsDict:
                apiFull = labelsDict[dataId]
                parts = apiFull.split('\n')
                label = parts[0].strip() if len(parts) >= 1 else dataId  # Label is first line
                location = parts[1].strip() if len(parts) >= 2 else dataId  # Location is second line
                fullLabel = f"{label} \n{location}"
                if debug: print(f"[DEBUG] buildTable: Aquarius in dict, header {i}: {fullLabel}")
            else:
                if mrid and mrid != '0':
                    fullLabel = f"{baseLabel} \n{dataId}-{mrid}"
                    if debug: print(f"[DEBUG] buildTable: USBR in dict with MRID, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{baseLabel} \n{dataId}"
                    if debug: print(f"[DEBUG] buildTable: USBR in dict, header {i}: {fullLabel}")
        else:
            if database == 'USGS-NWIS':
                parts = dataId.split('-')

                if len(parts) == 3 and parts[0].isdigit() and (parts[1].isdigit() or (len(parts[1]) == 32 and parts[1].isalnum())) and parts[2].isdigit():
                    fullLabel = f"{parts[0]}-{parts[2]} \n{intervalStr}"
                    if debug: print(f"[DEBUG] buildTable: Parsed USGS header {i}: {fullLabel}")
                else:
                    fullLabel = f"{dataId} \n{intervalStr}"
                    if debug: print(f"[DEBUG] buildTable: USGS not in dict, header {i}: {fullLabel}")
            elif database == 'AQUARIUS' and labelsDict and dataId in labelsDict:
                apiFull = labelsDict[dataId]
                parts = apiFull.split('\n')
                label = parts[0].strip() if len(parts) >= 1 else dataId  # Label is first line
                location = parts[1].strip() if len(parts) >= 2 else dataId  # Location is second line
                fullLabel = f"{label} \n{location}"
                if debug: print(f"[DEBUG] buildTable: Aquarius not in dict, header {i}: {fullLabel}")
            else:
                if mrid and mrid != '0':
                    fullLabel = f"{dataId}-{mrid} \n{intervalStr}"
                    if debug: print(f"[DEBUG] buildTable: USBR not in dict with MRID, header {i}: {fullLabel}")
                else:
                    fullLabel = f"{dataId} \n{intervalStr}"
                    if debug: print(f"[DEBUG] buildTable: USBR not in dict, header {i}: {fullLabel}")

        processedHeaders.append(fullLabel)

    headers = processedHeaders
    skipDateCol = dataDictionaryTable is not None
    numCols = len(headers)
    numRows = len(data)

    # Warn for large datasets
    if numRows > 10000:
        reply = QMessageBox.warning(None, "Large Dataset Warning",
                                   f"Query returned {numRows} rows, which may slow down the UI. Consider a smaller date range or coarser interval (e.g., HOUR instead of INSTANT:1). Continue?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            if debug: print(f"[DEBUG] buildTable: User canceled due to large dataset ({numRows} rows)")
            return
        
    if debug: print(f"[DEBUG] buildTable: Setting table to {numRows} rows, {numCols} columns")
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

    config = loadConfig()
    rawData = config.get('rawData', False)
    qaqcToggle = config.get('qaqc', True)

    # Pre-compute column widths using raw data (before valuePrecision)
    font = table.font()
    metrics = QFontMetrics(font)
    columnWidths = []
    sampleRows = min(1000, numRows) # Sample up to 1000 rows
    if debug: print(f"[DEBUG] buildTable: Sampling {sampleRows} rows for column widths")

    for c in range(numCols):
        cellValues = [row.split(',')[c+1].strip() if c+1 < len(row.split(',')) else "0.00" for row in data[:sampleRows]]
        nonEmptyValues = [val for val in cellValues if val] # Filter empty strings

        if nonEmptyValues:
            maxCellWidth = max(metrics.horizontalAdvance(val) for val in nonEmptyValues)
        else:
            maxCellWidth = metrics.horizontalAdvance("0.00") # Fallback for empty column
            if debug: print(f"[DEBUG] buildTable col {c}: No non-empty values, using fallback width {maxCellWidth}")

        headerLines = headers[c].split('\n')
        headerWidth = max(metrics.horizontalAdvance(line.strip()) for line in headerLines) if headerLines else 0
        if debug: print(f"[DEBUG] buildTable col {c}: maxCellWidth={maxCellWidth}, headerWidth={headerWidth}")
        finalWidth = max(maxCellWidth, headerWidth)

        if headerWidth > maxCellWidth:
            paddingIncrease = headerWidth - maxCellWidth
            finalWidth = maxCellWidth + paddingIncrease + 10
        else:
            finalWidth += 20

        columnWidths.append(finalWidth)

    # Disable updates for faster population
    table.setUpdatesEnabled(False)
    if debug: print("[DEBUG] buildTable: Disabled table updates for population")

    for rowIdx, rowStr in enumerate(data):
        rowData = rowStr.split(',')[1:] if skipDateCol else rowStr.split(',')
        for colIdx in range(min(numCols, len(rowData))):
            cellText = rowData[colIdx].strip() if colIdx < len(rowData) else ''
            item = QTableWidgetItem(cellText)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

            if not rawData and cellText.strip():
                item.setText(valuePrecision(cellText))

            table.setItem(rowIdx, colIdx, item)

    table.setUpdatesEnabled(True)
    if debug: print("[DEBUG] buildTable: Re-enabled table updates after population")
    table.horizontalHeader().sectionClicked.connect(lambda col: customSortTable(table, col, dataDictionaryTable))
    header = table.horizontalHeader()
    vHeader = table.verticalHeader()
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setMinimumSize(0, 0)
    table.update()
    header.setStretchLastSection(False)
    if debug: print("[DEBUG] buildTable: Set stretchLastSection=False to prevent last column expansion.")

    if dataDictionaryTable:
        maxTimeWidth = max(metrics.horizontalAdvance(ts) for ts in timestamps)
        vHeader.setMinimumWidth(max(120, maxTimeWidth) + 10)

    # Apply pre-computed column widths
    for c in range(numCols):
        table.setColumnWidth(c, columnWidths[c])
        if debug: print(f"[DEBUG] buildTable: Set column {c} width to {columnWidths[c]}")

    # Use fixed row height based on font metrics
    rowHeight = metrics.height() + 10
    sampleItem = QTableWidgetItem("189.5140")
    sampleItem.setFont(font)
    sampleCellHeight = sampleItem.sizeHint().height()

    if sampleCellHeight <= 0:
        sampleCellHeight = metrics.height()

    adjustedRowHeight = max(rowHeight, sampleCellHeight + 2)

    if debug: print(f"[DEBUG] buildTable: Sample cell height: {sampleCellHeight}, Adjusted row height: {adjustedRowHeight}")
    vHeader.setDefaultSectionSize(adjustedRowHeight)
    if debug: print(f"[DEBUG] buildTable: Set default row height to {adjustedRowHeight}")
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    vHeader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.update()
    table.horizontalScrollBar().setValue(0)
    visibleWidth = table.columnWidth(1) if numCols > 1 else 0
    if debug and numCols > 1: print(f"[DEBUG] buildTable: Custom resized {numCols} columns. Text width for col 1: {metrics.horizontalAdvance(headers[1])}, Visible width: {visibleWidth}, Row height: {adjustedRowHeight}")
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
    if not qaqcEnabled:
        if debug: print("[DEBUG] qaqc: Skipped, QAQC disabled in config")
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item: item.setBackground(QColor(0, 0, 0, 0))
        return

    now = datetime.now()

    for col, lookupId in enumerate(lookupIds):
        if debug: print("[DEBUG] qaqc: Processing column {} for lookupId {}".format(col, lookupId))
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

        if debug: print("[DEBUG] qaqc: Processed column {} for lookupId {}".format(col, lookupId))          
           
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
        if debug: print("[DEBUG] loadQuickLook: No quick look selected")
        return

    listQueryList.clear()
    userQuickLookPath = os.path.join(getQuickLookDir(), '{}.txt'.format(quickLookName))
    exampleQuickLookPath = resourcePath('quickLook/{}.txt'.format(quickLookName))
    quickLookPath = userQuickLookPath if os.path.exists(userQuickLookPath) else exampleQuickLookPath

    try:
        with open(quickLookPath, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()
        if content:
            data = content.split(',')

            for itemText in data:
                parts = itemText.strip().split('|')

                if len(parts) == 3:
                    dataID, interval, database = parts
                    if interval == 'INSTANT':
                        if database.startswith('USBR-'):
                            interval = 'INSTANT:60'
                        elif database == 'USGS-NWIS':
                            interval = 'INSTANT:15'
                        elif database == 'AQUARIUS':
                            interval = 'INSTANT:1'

                    listQueryList.addItem('{}|{}|{}'.format(dataID, interval, database))
                    if debug: print("[DEBUG] loadQuickLook: Added item {}".format('{}|{}|{}'.format(dataID, interval, database)))
    except FileNotFoundError:
        print("[WARN] Quick look '{}' not found.".format(quickLookName))

    if debug: print("[DEBUG] loadQuickLook: Loaded '{}' with {} items".format(quickLookName, listQueryList.count()))

def loadConfig():
    convertConfigToJson() # Convert if needed
    configPath = getConfigPath() # Get JSON path
    settings = {
        'lastExportPath': '',
        'debugMode': False,
        'utcOffset': 'UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London',
        'periodOffset': True,
        'retroMode': True,
        'qaqc': True,
        'rawData': False,
        'lastQuickLook': ''
    }
    if os.path.exists(configPath):
        try:
            with open(configPath, 'r', encoding='utf-8') as configFile:
                config = json.load(configFile) # Read JSON

            if debug: print("[DEBUG] Loaded config: {}".format(config))

            # Migrate integer utcOffset and retroFont
            utcOffset = config.get('utcOffset', settings['utcOffset'])

            if isinstance(utcOffset, (int, float)):
                if debug: print("[DEBUG] Migrating integer utcOffset {} to full string".format(utcOffset))
                offsetMap = {
                    -12: "UTC-12:00 | Baker Island",
                    -11: "UTC-11:00 | American Samoa",
                    -10: "UTC-10:00 | Hawaii",
                    -9.5: "UTC-09:30 | Marquesas Islands",
                    -9: "UTC-09:00 | Alaska",
                    -8: "UTC-08:00 | Pacific Time (US & Canada)",
                    -7: "UTC-07:00 | Mountain Time (US & Canada)/Arizona",
                    -6: "UTC-06:00 | Central Time (US & Canada)",
                    -5: "UTC-05:00 | Eastern Time (US & Canada)",
                    -4: "UTC-04:00 | Atlantic Time (Canada)",
                    -3.5: "UTC-03:30 | Newfoundland",
                    -3: "UTC-03:00 | Brasilia",
                    -2: "UTC-02:00 | Mid-Atlantic",
                    -1: "UTC-01:00 | Cape Verde Is.",
                    0: "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London",
                    1: "UTC+01:00 | Central European Time : Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
                    2: "UTC+02:00 | Eastern European Time : Athens, Bucharest, Istanbul",
                    3: "UTC+03:00 | Moscow, St. Petersburg, Volgograd",
                    3.5: "UTC+03:30 | Tehran",
                    4: "UTC+04:00 | Abu Dhabi, Muscat",
                    4.5: "UTC+04:30 | Kabul",
                    5: "UTC+05:00 | Islamabad, Karachi, Tashkent",
                    5.5: "UTC+05:30 | Chennai, Kolkata, Mumbai, New Delhi",
                    5.75: "UTC+05:45 | Kathmandu",
                    6: "UTC+06:00 | Astana, Dhaka",
                    6.5: "UTC+06:30 | Yangon (Rangoon)",
                    7: "UTC+07:00 | Bangkok, Hanoi, Jakarta",
                    8: "UTC+08:00 | Beijing, Chongqing, Hong Kong, Urumqi",
                    8.75: "UTC+08:45 | Eucla",
                    9: "UTC+09:00 | Osaka, Sapporo, Tokyo",
                    9.5: "UTC+09:30 | Adelaide, Darwin",
                    10: "UTC+10:00 | Brisbane, Canberra, Melbourne, Sydney",
                    10.5: "UTC+10:30 | Lord Howe Island",
                    11: "UTC+11:00 | Solomon Is., New Caledonia",
                    12: "UTC+12:00 | Auckland, Wellington",
                    12.75: "UTC+12:45 | Chatham Islands",
                    13: "UTC+13:00 | Samoa",
                    14: "UTC+14:00 | Kiritimati"
                }
                utcOffset = offsetMap.get(utcOffset, settings['utcOffset']) # Map to string or default
                config['utcOffset'] = utcOffset # Update config
                if debug: print("[DEBUG] Migrated utcOffset to: {}".format(utcOffset))

            if 'retroFont' in config:
                if debug: print("[DEBUG] Migrating retroFont to retroMode")
                config['retroMode'] = config.pop('retroFont') # Rename key
                if debug: print("[DEBUG] Migrated retroMode to: {}".format(config['retroMode']))

            if 'colorMode' in config:
                if debug: print("[DEBUG] Removing obsolete colorMode")
                config.pop('colorMode') # Remove key

            # Write updated config back to file
            with open(configPath, 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)

            settings['lastExportPath'] = config.get('lastExportPath', settings['lastExportPath']) # Load export path
            settings['debugMode'] = config.get('debugMode', settings['debugMode']) # Load debug
            settings['utcOffset'] = utcOffset # Load full UTC string
            if debug: print("[DEBUG] utcOffset loaded as: {}".format(settings['utcOffset']))
            settings['periodOffset'] = config.get('hourTimestampMethod', 'EOP') == 'EOP' # Load period
            settings['retroMode'] = config.get('retroMode', settings['retroMode']) # Load retro
            settings['qaqc'] = config.get('qaqc', settings['qaqc']) # Load QAQC
            settings['rawData'] = config.get('rawData', settings['rawData']) # Load raw
            settings['lastQuickLook'] = config.get('lastQuickLook', settings['lastQuickLook']) # Load quick look
            if debug: print("[DEBUG] Loaded settings from user.config: {}".format(settings))
        except Exception as e:
            if debug: print("[ERROR] Failed to load user.config: {}".format(e))
    else:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2) # Write default JSON
        if debug: print("[DEBUG] Created default user.config with settings: {}".format(settings))

    return settings

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        if debug: print("[DEBUG] exportTableToCSV: Empty table-no export")
        return

    # Get full settings from config (merges defaults, preserves all keys)
    settings = loadConfig()
    if debug: print("[DEBUG] exportTableToCSV: Loaded full settings: {}".format(settings))
    lastPath = settings.get('lastExportPath', os.path.expanduser("~/Documents"))

    # Normalize loaded path to platform slashes/abs (handles cross-save)
    lastPath = os.path.normpath(os.path.abspath(lastPath)) if lastPath else None
    if debug: print("[DEBUG] exportTableToCSV: Normalized lastPath: {}".format(lastPath))

    # Force Documents if lastPath empty/invalid
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.normpath(os.path.expanduser("~/Documents"))
    if debug: print("[DEBUG] exportTableToCSV: Used fallback Documents path")

    defaultDir = lastPath

    # Timestamped default name (yyyy-mm-dd HH:mm:ss Export.csv)
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.normpath(os.path.join(defaultDir, defaultName))
    if debug: print("[DEBUG] exportTableToCSV: Suggested path: {}".format(suggestedPath))

    # Instantiate dialog for control (non-static)
    dlg = QFileDialog(None)
    dlg.setWindowTitle("Save CSV As")
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setNameFilter("CSV files (*.csv)")
    dlg.selectFile(defaultName)
    dlg.setDirectory(QDir.fromNativeSeparators(defaultDir))
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True) # Force Qt-based for font control (cross-platform)

    if retroMode:
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
    else:
        if debug: print("[DEBUG] exportTableToCSV: User canceled dialog")
        return # User canceled

    # Build CSV
    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = ['Date/Time,' + ','.join(headers)] # Header with Timestamp
    if debug: print("[DEBUG] exportTableToCSV: Built headers: {}".format(csvLines[0]))

    # Add timestamps as first column
    timestamps = [table.verticalHeaderItem(r).text() if table.verticalHeaderItem(r) else '' for r in range(table.rowCount())]

    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(timestamps[r] + ',' + ','.join(rowData))

    # Write
    try:
        with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\n'.join(csvLines))
        if debug: print("[DEBUG] exportTableToCSV: Successfully wrote CSV to {}".format(filePath))
    except Exception as e:
        if debug: print("[DEBUG] exportTableToCSV: Failed to write CSV: {}".format(e))
        return

    # Save last path to full settings (dir only, preserve others)
    exportDir = os.path.normpath(os.path.dirname(filePath))
    if debug: print("[DEBUG] exportTableToCSV: Updating lastExportPath to {}".format(exportDir))
    settings['lastExportPath'] = exportDir
    if debug: print("[DEBUG] exportTableToCSV: Full settings after update: {}".format(settings))
    configPath = getConfigPath()

    try:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2)
        if debug: print("[DEBUG] exportTableToCSV: Updated user.config with new lastExportPath-full file preserved")
    except Exception as e:
        if debug: print("[DEBUG] exportTableToCSV: Failed to update user.config: {}".format(e))  

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
    global debug, utcOffset, periodOffset, retroMode, qaqcEnabled, rawData # Update globals
    debug = settings['debugMode'] # Set debug
    utcOffset = settings['utcOffset'] # Set UTC
    periodOffset = settings['periodOffset'] # Set period
    retroMode = settings['retroMode'] # Set retro
    qaqcEnabled = settings['qaqc'] # Set QAQC
    rawData = settings['rawData'] # Set raw
    if debug: print("[DEBUG] Globals reloaded from user.config")

def applyRetroFont(widget, pointSize=10):
    if retroMode:
        fontPath = resourcePath('ui/fonts/PressStart2P-Regular.ttf') # Load from path
        fontId = QFontDatabase.addApplicationFont(fontPath)

        if fontId != -1:
            fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
            retroFontObj = QFont(fontFamily, pointSize)
            retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing for crisp retro
            widget.setFont(retroFontObj)

            for child in widget.findChildren(QWidget): # Recursive to all children
                child.setFont(retroFontObj)
                
            if debug: print("[DEBUG] Applied retro font to widget: {}".format(widget.objectName()))
        else:
            if debug: print("[ERROR] Failed to load retro font from {}".format(fontPath))
    else:
        widget.setFont(QFont()) # System default font

        for child in widget.findChildren(QWidget): # Recursive to all children
            child.setFont(QFont())

        if debug: print("[DEBUG] Reverted widget {} to system font".format(widget.objectName()))

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
    if debug: print("[DEBUG] executeQuery: isInternal={}, items={}".format(isInternal, len(queryItems)))

    if isInternal:
        queryItems = [item for item in queryItems if item[2] != 'USGS-NWIS']
    if not queryItems:
        QMessageBox.warning(mainWindow, "No Valid Items", "No valid internal query items (USGS skipped).")
        return

    # Set up progress dialog   
    progressDialog = QProgressDialog(f"Querying data... (0/0 complete)", "Cancel", 0, 100, mainWindow)
    progressDialog.setWindowModality(Qt.WindowModality.WindowModal)
    progressDialog.setAutoReset(False)
    progressDialog.setAutoClose(False)
    progressDialog.setFixedSize(400, 100) # Lock size for messages, prevent resizing
    progressDialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.MSWindowsFixedSizeDialogHint) # Lock position
    progressDialog.show() # Force immediate display
    progressDialog.setValue(10)
    progressDialog.repaint() # Force initial render
    if debug: print("[DEBUG] executeQuery: Initialized and showed progress dialog")

    queryItems.sort(key=lambda x: x[4])
    firstInterval = queryItems[0][1]
    firstDb = queryItems[0][2]    

    if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
        firstInterval = 'INSTANT:60'
    elif firstInterval == 'INSTANT' and firstDb == 'USGS-NWIS':
        firstInterval = 'INSTANT:15'
    elif firstInterval == 'INSTANT' and firstDb == 'AQUARIUS':
        firstInterval = 'INSTANT:1'

    timestamps = buildTimestamps(startDate, endDate, firstInterval)

    if not timestamps:
        progressDialog.cancel()
        QMessageBox.warning(mainWindow, "Date Error", "Invalid dates or interval.")
        return

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

        groupKey = (db.split('-')[0] if db.startswith('USBR-') else db, None, None) # Group all USBR into one thread
        SDID = dataID.split('-')[0] if db.startswith('USBR-') and '-' in dataID else dataID
        groups[groupKey].append((origIndex, dataID, SDID, db, interval, mrid))

    # Threading setup
    pool = QThreadPool.globalInstance()
    resultQueue = queue.Queue() # Thread-safe queue for results
    maxDbThreads = 3 # One thread per unique database type (AQUARIUS, USBR, USGS)
    numGroups = len(groups)
    numThreads = min(maxDbThreads, numGroups) # One thread per group, up to maxDbThreads
    if debug: print(f"[DEBUG] Starting {numThreads} threads for {numGroups} groups in background")

    class QueryWorkerSignals(QObject):
        progressSignal = pyqtSignal(int, str) # For dialog updates
        resultSignal = pyqtSignal(tuple) # (groupKey, groupResult, groupLabels)        

    # Define local QRunnable subclass for query groups
    class QueryWorker(QRunnable):
        def __init__(self, groupKey, groupItems, signals):
            super().__init__()
            self.groupKey = groupKey
            self.groupItems = groupItems
            self.signals = signals

        def run(self):
            db, _, _ = self.groupKey
            groupResult = {}
            groupLabels = {} if db == 'AQUARIUS' else None

            # Group items by db and interval for separate USBR queries
            usbrGroups = defaultdict(list)
            for origIndex, dataID, SDID, itemDb, interval, mrid in self.groupItems:
                usbrGroups[(itemDb, interval, mrid)].append((origIndex, dataID, SDID))

            try:
                for (itemDb, interval, mrid), items in usbrGroups.items():
                    SDIDs = [item[2] for item in items]
                    if db.startswith('USBR'):
                        svr = itemDb.split('-')[1].lower() if '-' in itemDb else 'lchdb'
                        table = 'M' if mrid != '0' else 'R'
                        apiInterval = interval
                        result = QueryUSBR.apiRead(svr, SDIDs, startDate, endDate, apiInterval, mrid, table)
                    elif db == 'AQUARIUS' and isInternal:
                        result = QueryAquarius.apiRead(SDIDs, startDate, endDate, interval)
                    elif db == 'USGS-NWIS' and not isInternal:
                        result = QueryUSGS.apiRead(SDIDs, interval, startDate, endDate)
                    else:
                        if debug: print(f"[DEBUG] QueryWorker: Unknown db skipped: {db}")     
                        continue

                    for idx, (origIndex, dataID, SDID) in enumerate(items):
                        if SDID in result:
                            if db == 'AQUARIUS':
                                outputData = result[SDID]['data']
                                groupLabels[dataID] = result[SDID].get('label', dataID)
                            else:
                                outputData = result[SDID]

                            alignedData = gapCheck(timestamps, outputData, dataID)
                            values = [line.split(',')[1] if line else '' for line in alignedData]
                            groupResult[dataID] = values
                        else:
                            groupResult[dataID] = defaultBlanks                

                if debug: print(f"[DEBUG] QueryWorker: Completed group {self.groupKey} with {len(groupResult)} items")          
            except Exception as e:
                if debug: print(f"[DEBUG] QueryWorker: Failed for group {self.groupKey}: {e}")          
                for _, dataID, _ in items:
                    groupResult[dataID] = defaultBlanks # Fallback blanks on error

            self.signals.resultSignal.emit((self.groupKey, groupResult, groupLabels)) 

    # Start workers
    threadsStarted = 0
    valueDict = {}
    collected = 0
    eventLoop = QEventLoop() # For processing timer signals

    def handleResult(result):
        nonlocal collected, valueDict, timer
        groupKey, groupResult, groupLabels = result
        # Check if groupResult is all blanks
        if all(all(v == '' for v in values) for values in groupResult.values()):
            if debug: print(f"[DEBUG] executeQuery: Skipping empty group {groupKey}, no data")
            return
        if collected < numGroups: # Prevent double-processing
            valueDict.update(groupResult)
            if groupLabels and labelsDict is not None:
                labelsDict.update(groupLabels)
            collected += 1
            if debug: print(f"[DEBUG] executeQuery: Collected results for group {groupKey} with {len(groupResult)} items ({collected}/{numGroups})")
            if debug: print(f"[DEBUG] executeQuery: groupResult keys: {list(groupResult.keys())}")
            if not progressDialog.wasCanceled():
                current = progressDialog.value()
                progressDialog.setValue(min(70 + int(20 * collected / numGroups), 80)) # Gradual 70-80%
                progressDialog.setLabelText(f"Completed {groupKey[0]} query ({collected}/{numGroups})")
                progressDialog.repaint() # Force redraw
                progressDialog.updateGeometry() # Stabilize position
                if debug: print(f"[DEBUG] executeQuery: Progress set to {min(70 + int(20 * collected / numGroups), 80)}%")
                QCoreApplication.processEvents()
                QTimer.singleShot(500, lambda: progressDialog.setLabelText(f"Merging data... ({collected}/{numGroups})") if not progressDialog.wasCanceled() else None)

    for i, groupKey in enumerate(groups.keys()):
        signals = QueryWorkerSignals()
        worker = QueryWorker(groupKey, groups[groupKey], signals)
        signals.resultSignal.connect(lambda result, i=i: (resultQueue.put(result), handleResult(result))) # Per-worker connect
        pool.start(worker)
        threadsStarted += 1
        if debug: print(f"[DEBUG] Started backgroundworker {i} for group {groupKey}")

    if not progressDialog.wasCanceled():
        progressDialog.setValue(10) # Fixed base after all workers start
        progressDialog.setLabelText(f"Querying data... (0/{numGroups} complete)") # Fix initial label
        progressDialog.repaint() # Force initial render
        if debug: print(f"[DEBUG] executeQuery: All workers started, progress at 10%")

    QCoreApplication.processEvents() # Pump for dialog

    # Non-blocking wait with timer for progress and queue check
    timeoutSeconds = 60 # 1 minute for faster progress
    startTime = time.time()
    progressBase = 10 # Start gradual progress at 10% after workers start
    timer = QTimer()
    timer.setSingleShot(False) # Repeat until done

    def updateProgress():
        nonlocal startTime, collected
        elapsed = time.time() - startTime
        if collected >= numGroups:
            timer.stop()
            if debug: print("[DEBUG] executeQuery: Timer stopped in updateProgress, all groups collected")
            if not progressDialog.wasCanceled():
                progressDialog.setValue(70) # Queries complete
                progressDialog.setLabelText(f"Merging data... ({collected}/{numGroups})")
                progressDialog.repaint() # Force redraw
                progressDialog.updateGeometry() # Stabilize position
                if debug: print("[DEBUG] executeQuery: Queries complete, progress at 70%")
            QCoreApplication.processEvents()
            return
        if not progressDialog.wasCanceled():
            # Process queue in timer to catch results
            while not resultQueue.empty():
                try:
                    result = resultQueue.get_nowait()
                    handleResult(result)
                    if debug: print(f"[DEBUG] executeQuery: Processed queued result in timer, collected {collected}/{numGroups}, queue size {resultQueue.qsize()}")
                except queue.Empty:
                    break
            progress = progressBase + int((elapsed / timeoutSeconds) * 80) # Gradual 10-90%
            progressDialog.setValue(min(progress, 69)) # Cap at 69%
            progressDialog.setLabelText(f"Querying data... ({collected}/{numGroups} complete)")
            progressDialog.repaint() # Force redraw
            progressDialog.updateGeometry() # Stabilize position
            if debug: print(f"[DEBUG] executeQuery: Timer update, progress {progress}%, collected {collected}/{numGroups}")
        QCoreApplication.processEvents() # Pump for responsiveness

    timer.timeout.connect(updateProgress)
    timer.start(100) # Faster updates, every 100ms
    if debug: print("[DEBUG] executeQuery: Started timer for progress updates")

    # Wait for all results or cancellation
    while collected < numGroups and not progressDialog.wasCanceled():
        if pool.activeThreadCount() > 0:
            time.sleep(0.05) # Short sleep to allow timer
        QCoreApplication.processEvents() # Process timer and signals

    timer.stop() # Ensure timer stops
    if debug: print("[DEBUG] executeQuery: Timer stopped, wait loop ended")
    QCoreApplication.processEvents()

    if progressDialog.wasCanceled():
        if debug: print("[DEBUG] executeQuery: User canceled via progress dialog")
        progressDialog.cancel()
        return

    if debug: print(f"[DEBUG] executeQuery: All {collected} groups merged")
    progressDialog.setLabelText("Merging results...")
    progressDialog.setValue(85) # Update before heavy merge
    progressDialog.repaint()
    QCoreApplication.processEvents()
    if debug: print(f"[DEBUG] executeQuery: Merging valueDict with {len(valueDict)} keys")

    # Ensure all dataIDs are in valueDict
    originalDataIds = [item[0] for item in queryItems]
    originalIntervals = [item[1] for item in queryItems]
    databases = [item[2] for item in queryItems]
    lookupIds = [item[0].split('-')[0] if item[2].startswith('USBR-') and '-' in item[0] else item[0] for item in queryItems]
    data = []

    for r in range(len(timestamps)):
        rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
        data.append("{},{}".format(timestamps[r], ','.join(rowValues)))
        if r % 100 == 0: # Update progress every 100 rows
            progressDialog.setLabelText(f"Building table... ({r}/{len(timestamps)} rows)")
            progressDialog.setValue(85 + int(15 * r / len(timestamps))) # Gradual 85-100%
            progressDialog.repaint()
            QCoreApplication.processEvents()
            if debug: print(f"[DEBUG] executeQuery: Building row {r}/{len(timestamps)}")
    if debug: print(f"[DEBUG] executeQuery: Built {len(data)} rows for table")

    if not progressDialog.wasCanceled():
        progressDialog.setLabelText("Building table...")
        if debug: print("[DEBUG] executeQuery: Updating progress dialog for table building")
        QCoreApplication.processEvents() # Pump event loop before table building
        mainWindow.mainTable.clear()
        buildTable(mainWindow.mainTable, data, originalDataIds, dataDictionaryTable, originalIntervals, lookupIds, labelsDict, databases)
        progressDialog.setValue(100) # Complete
        progressDialog.repaint() # Force redraw
        if debug: print("[DEBUG] executeQuery: Table built, progress dialog completed")
        QCoreApplication.processEvents() # Pump event loop after table building

    if progressDialog.wasCanceled():
        if debug: print("[DEBUG] executeQuery: User canceled during table building")
        progressDialog.cancel()
        return

    if mainWindow.tabWidget.indexOf(mainWindow.tabMain) == -1:
        mainWindow.tabWidget.addTab(mainWindow.tabMain, 'Data Query')

    if debug: print("[DEBUG] Query executed and table updated.")
    progressDialog.cancel() # Close dialog
    QCoreApplication.processEvents() # Ensure cleanup renders

def getUtcOffsetInt(utcOffsetStr):
    """Extract UTC offset as float from full string (e.g., 'UTC-09:30 | Marquesas Islands' -> -9.5)."""
    try:
        offsetPart = utcOffsetStr.split(' | ')[0].replace('UTC', '') # Get 'UTC-09:30'
        offsetParts = offsetPart.split(':') # Split on colon
        hours = int(offsetParts[0]) # Extract hours
        minutes = int(offsetParts[1]) if len(offsetParts) > 1 and offsetParts[1] else 0 # Extract minutes
        offset = hours + (minutes / 60.0) * (-1 if hours < 0 else 1) # Convert to float (e.g., -9:30 -> -9.5)
        if debug: print("[DEBUG] getUtcOffsetInt: Parsed '{}' to {} hours".format(utcOffsetStr, offset))
        return offset
    except (ValueError, IndexError) as e:
        if debug: print("[ERROR] getUtcOffsetInt: Failed to parse '{}': {}. Returning 0".format(utcOffsetStr, e))
        return 0.0 # Fallback to UTC+00:00

def setRetroStyles(app, enable, mainTable=None, webQueryList=None, internalQueryList=None):
    """Apply or remove retro mode styles (e.g., scroll bars) dynamically."""
    retroStyles = """
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #00FF00; /* Neon green handle */
            border-radius: 4px;
        }
        QScrollBar:vertical, QScrollBar:horizontal {
            background: #333333; /* Dark track for contrast */
            width: 12px;
            height: 12px;
        }
    """
    if enable:
        # Apply to specific widgets
        for widget in [mainTable, webQueryList, internalQueryList]:
            if widget:
                widget.setStyleSheet(retroStyles)

                if debug: print("[DEBUG] Applied retro scroll bar styles to {}".format(widget.objectName()))

        app.setStyleSheet(app.styleSheet() + retroStyles)

        if debug: print("[DEBUG] Applied retro scroll bar styles globally")
    else:
        # Reset to base stylesheet
        with open(resourcePath('ui/stylesheet.qss'), 'r') as f:
            app.setStyleSheet(f.read())
        for widget in [mainTable, webQueryList, internalQueryList]:
            if widget:
                widget.setStyleSheet("")

                if debug: print("[DEBUG] Cleared retro scroll bar styles from {}".format(widget.objectName()))

        if debug: print("[DEBUG] Reverted to base stylesheet")