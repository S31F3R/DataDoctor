import os
import sys
import datetime
import configparser
import json
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QStandardPaths, QDir
from PyQt6.QtGui import QGuiApplication, QFont, QFontDatabase
from PyQt6.QtWidgets import QPushButton, QFileDialog, QWidget, QTreeView, QSplitter
from core import USBR, USGS, Aquarius

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

def buildDataDictionary(table):
    table.clear() # Clear table

    with open(resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
        data = [line.strip().split(',') for line in f.readlines()] # Read CSV
    if not data:
        if debug: 
            print("[DEBUG] DataDictionary.csv empty")
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

def loadAllQuickLooks(cbQuickLook):
    cbQuickLook.clear()
    quickLookPaths = []

    # User-specific Quick Looks from query subfolder
    userDir = getQuickLookDir()

    for file in os.listdir(userDir):
        if file.endswith(".txt"):
            quickLookPaths.append(os.path.join(userDir, file))

            if debug: 
                print("[DEBUG] loadAllQuickLooks: Found user Quick Look: {}".format(file))
    # Append example Quick Looks (no duplicates – check names)
    exampleDir = getExampleQuickLookDir()

    for file in os.listdir(exampleDir):
        if file.endswith(".txt"):
            examplePath = os.path.join(exampleDir, file)
            userPath = os.path.join(userDir, file)

            if not os.path.exists(userPath):  # Avoid dupes
                quickLookPaths.append(examplePath)

                if debug: 
                    print("[DEBUG] loadAllQuickLooks: Added example Quick Look: {}".format(file))

    # Add to combo (use basename without .txt)
    for path in quickLookPaths:
        name = os.path.basename(path).replace('.txt', '')
        cbQuickLook.addItem(name)

        if debug: 
            print("[DEBUG] loadAllQuickLooks: Added {} to cbQuickLook".format(name))

def saveQuickLook(textQuickLookName, listQueryList):
    name = textQuickLookName.toPlainText().strip() if hasattr(textQuickLookName, 'toPlainText') else str(textQuickLookName).strip()
    if not name:
        print("[WARN]: Empty quick look name—skipped.")
        return
    data = [listQueryList.item(x).text() for x in range(listQueryList.count())]
    quicklookPath = os.path.join(getQuickLookDir(), f'{name}.txt')
    os.makedirs(os.path.dirname(quicklookPath), exist_ok=True) # Ensure dir

    try:
        with open(quicklookPath, 'w', encoding='utf-8-sig') as f:
            f.write(','.join(data))
        if debug: 
            print("[DEBUG] saveQuickLook: Saved Quick Look to {}".format(quicklookPath))
    except Exception as e:
        if debug: 
            print("[ERROR] saveQuickLook: Failed to save Quick Look to {}: {}".format(quicklookPath, e))

def loadQuickLook(cbQuickLook, listQueryList):
    quickLookName = cbQuickLook.currentText()
    if not quickLookName:
        if debug: 
            print("[DEBUG] loadQuickLook: No quick look selected")
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

                    # Convert historical INSTANT queries to new format
                    if interval == 'INSTANT':
                        if database.startswith('USBR-'): interval = 'INSTANT:60'
                        elif database == 'USGS-NWIS': interval = 'INSTANT:15'
                        elif database == 'AQUARIUS': interval = 'INSTANT:1'
                    listQueryList.addItem('{}|{}|{}'.format(dataID, interval, database))

                    if debug: 
                        print("[DEBUG] loadQuickLook: Added item {}".format('{}|{}|{}'.format(dataID, interval, database)))
    except FileNotFoundError:
        print("[WARN] Quick look '{}' not found.".format(quickLookName))
    if debug: 
        print("[DEBUG] loadQuickLook: Loaded '{}' with {} items".format(quickLookName, listQueryList.count()))

def loadConfig():
    convertConfigToJson()  # Convert if needed
    configPath = getConfigPath()  # Get JSON path
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
                config = json.load(configFile)  # Read JSON
            if debug: 
                print("[DEBUG] Loaded config: {}".format(config))

            # Migrate integer utcOffset and retroFont
            utcOffset = config.get('utcOffset', settings['utcOffset'])

            if isinstance(utcOffset, (int, float)):
                if debug: 
                    print("[DEBUG] Migrating integer utcOffset {} to full string".format(utcOffset))

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
                if debug: 
                    print("[DEBUG] Migrated utcOffset to: {}".format(utcOffset))
            if 'retroFont' in config:
                if debug: 
                    print("[DEBUG] Migrating retroFont to retroMode")
                config['retroMode'] = config.pop('retroFont') # Rename key
                if debug: 
                    print("[DEBUG] Migrated retroMode to: {}".format(config['retroMode']))
            if 'colorMode' in config:
                if debug: 
                    print("[DEBUG] Removing obsolete colorMode")
                config.pop('colorMode') # Remove key

            # Check os env for existing TNS_ADMIN
            envTns = os.environ.get('TNS_ADMIN')

            # If existing TNS_ADMIN, overwrite config TNS_ADMIN location
            if envTns: 
                config['tnsNamesLocation'] = envTns

            # Write updated config back to file
            with open(configPath, 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)

            # Update settings in program
            settings['lastExportPath'] = config.get('lastExportPath', settings['lastExportPath']) # Load export path
            settings['debugMode'] = config.get('debugMode', settings['debugMode']) # Load debug
            settings['utcOffset'] = utcOffset # Load full UTC string

            if debug: 
                print("[DEBUG] utcOffset loaded as: {}".format(settings['utcOffset']))

            settings['periodOffset'] = config.get('hourTimestampMethod', 'EOP') == 'EOP' # Load period
            settings['retroMode'] = config.get('retroMode', settings['retroMode']) # Load retro
            settings['qaqc'] = config.get('qaqc', settings['qaqc']) # Load QAQC
            settings['rawData'] = config.get('rawData', settings['rawData']) # Load raw
            settings['lastQuickLook'] = config.get('lastQuickLook', settings['lastQuickLook']) # Load quick look

            if debug: 
                print("[DEBUG] Loaded settings from user.config: {}".format(settings))
        except Exception as e:
            if debug: print("[ERROR] Failed to load user.config: {}".format(e))
    else:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2) # Write default JSON
        if debug: 
            print("[DEBUG] Created default user.config with settings: {}".format(settings))
    return settings

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        if debug: 
            print("[DEBUG] exportTableToCSV: Empty table-no export")
        return

    # Get full settings from config (merges defaults, preserves all keys)
    settings = loadConfig()

    if debug: 
        print("[DEBUG] exportTableToCSV: Loaded full settings: {}".format(settings))

    lastPath = settings.get('lastExportPath', os.path.expanduser("~/Documents"))

    # Normalize loaded path to platform slashes/abs (handles cross-save)
    lastPath = os.path.normpath(os.path.abspath(lastPath)) if lastPath else None

    if debug: 
        print("[DEBUG] exportTableToCSV: Normalized lastPath: {}".format(lastPath))
    # Force Documents if lastPath empty/invalid
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.normpath(os.path.expanduser("~/Documents"))
    if debug: 
        print("[DEBUG] exportTableToCSV: Used fallback Documents path")
    defaultDir = lastPath

    # Timestamped default name (yyyy-mm-dd HH:mm:ss Export.csv)
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.normpath(os.path.join(defaultDir, defaultName))

    if debug: 
        print("[DEBUG] exportTableToCSV: Suggested path: {}".format(suggestedPath))

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

    # Force sidebar width via splitter
    splitter = dlg.findChild(QSplitter)

    if splitter:
        splitter.setSizes([150, dlg.width() - 150]) # Sidebar 150px, main the rest
    if debug: 
        print("[DEBUG] exportTableToCSV: Adjusted splitter sizes")

    # Optional: Auto-resize main view columns (sidebar fixed, so skipped for it)
    mainView = dlg.findChild(QTreeView, "fileview") # Main view (may vary; fallback to first)

    if not mainView:
        mainView = dlg.findChild(QTreeView) # Fallback if named differently
    if mainView:
        header = mainView.header()

        for i in range(header.count()):
            mainView.resizeColumnToContents(i) # Auto-size main columns
    if debug: 
        print("[DEBUG] exportTableToCSV: Resized main view columns")
    if dlg.exec():
        filePath = dlg.selectedFiles()[0]
    else:
        if debug: 
            print("[DEBUG] exportTableToCSV: User canceled dialog")
        return # User canceled

    # Build CSV
    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = ['Date/Time,' + ','.join(headers)] # Header with Timestamp

    if debug: 
        print("[DEBUG] exportTableToCSV: Built headers: {}".format(csvLines[0]))

    # Add timestamps as first column
    timestamps = [table.verticalHeaderItem(r).text() if table.verticalHeaderItem(r) else '' for r in range(table.rowCount())]

    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(timestamps[r] + ',' + ','.join(rowData))

    # Write
    try:
        with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\n'.join(csvLines))
        if debug: 
            print("[DEBUG] exportTableToCSV: Successfully wrote CSV to {}".format(filePath))
    except Exception as e:
        if debug: 
            print("[DEBUG] exportTableToCSV: Failed to write CSV: {}".format(e))
        return

    # Save last path to full settings (dir only, preserve others)
    exportDir = os.path.normpath(os.path.dirname(filePath))

    if debug: 
        print("[DEBUG] exportTableToCSV: Updating lastExportPath to {}".format(exportDir))

    settings['lastExportPath'] = exportDir

    if debug: 
        print("[DEBUG] exportTableToCSV: Full settings after update: {}".format(settings))

    configPath = getConfigPath()

    try:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2)
        if debug: print("[DEBUG] exportTableToCSV: Updated user.config with new lastExportPath-full file preserved")
    except Exception as e:
        if debug: print("[DEBUG] exportTableToCSV: Failed to update user.config: {}".format(e))

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
    queryDir = os.path.join(quickLookDir, "query")

    if not os.path.exists(quickLookDir):
        os.makedirs(quickLookDir)

        if debug: 
            print("[DEBUG] getQuickLookDir: Created quickLook directory: {}".format(quickLookDir))
    if not os.path.exists(queryDir):
        os.makedirs(queryDir)

        if debug: 
            print("[DEBUG] getQuickLookDir: Created query subfolder: {}".format(queryDir))

    # Migrate existing .txt files from quickLook root to query subfolder
    for file in os.listdir(quickLookDir):
        if file.endswith(".txt"):
            srcPath = os.path.join(quickLookDir, file)
            dstPath = os.path.join(queryDir, file)

            if os.path.isfile(srcPath) and not os.path.exists(dstPath):
                try:
                    os.rename(srcPath, dstPath)

                    if debug: 
                        print("[DEBUG] getQuickLookDir: Moved {} to {}".format(srcPath, dstPath))
                except Exception as e:
                    if debug: 
                        print("[ERROR] getQuickLookDir: Failed to move {} to {}: {}".format(srcPath, dstPath, e))
            elif os.path.exists(dstPath):
                if debug: 
                    print("[DEBUG] getQuickLookDir: Skipped moving {} as it already exists in {}".format(srcPath, queryDir))
    return queryDir

def reloadGlobals():
    settings = loadConfig() # Load JSON settings
    global debug, utcOffset, periodOffset, retroMode, qaqcEnabled, rawData # Update globals
    debug = settings['debugMode'] # Set debug
    utcOffset = settings['utcOffset'] # Set UTC
    periodOffset = settings['periodOffset'] # Set period
    retroMode = settings['retroMode'] # Set retro
    qaqcEnabled = settings['qaqc'] # Set QAQC
    rawData = settings['rawData'] # Set raw

    if debug: 
        print("[DEBUG] Globals reloaded from user.config")

def applyRetroFont(widget, pointSize=10):
    if retroMode:
        fontPath = resourcePath('ui/fonts/PressStart2P-Regular.ttf') # Load from path
        fontId = QFontDatabase.addApplicationFont(fontPath)

        if fontId != -1:
            fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
            retroFontObj = QFont(fontFamily, pointSize)
            retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing for crisp retro
            widget.setFont(retroFontObj)

            for child in widget.findChildren(QWidget):
                child.setFont(retroFontObj) # Recursive to all children

            if debug: 
                print("[DEBUG] Applied retro font to widget: {}".format(widget.objectName()))
        else:
            if debug: 
                print("[ERROR] Failed to load retro font from {}".format(fontPath))
    else:
        widget.setFont(QFont()) # System default font

        for child in widget.findChildren(QWidget):
            child.setFont(QFont()) # Recursive to all children
        if debug: 
            print("[DEBUG] Reverted widget {} to system font".format(widget.objectName()))

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
        if debug: 
            print("[DEBUG] Unknown radio button in setQueryDateRange")

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

        if debug: 
            print("[DEBUG] Found config.ini, converting to user.config")

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

            if debug: 
                print(f"[DEBUG] Converted utcOffset: {settings['utcOffset']}")
            settings['retroFont'] = config['Settings'].getboolean('retroFont', settings['retroFont']) # Preserve retro

            if debug: 
                print(f"[DEBUG] Converted retroFont: {settings['retroFont']}")
            settings['qaqc'] = config['Settings'].getboolean('qaqc', settings['qaqc']) # Preserve QAQC

            if debug: 
                print(f"[DEBUG] Converted qaqc: {settings['qaqc']}")
            settings['rawData'] = config['Settings'].getboolean('rawData', settings['rawData']) # Preserve raw

            if debug: 
                print(f"[DEBUG] Converted rawData: {settings['rawData']}")
            settings['debugMode'] = config['Settings'].getboolean('debugMode', settings['debugMode']) # Preserve debug

            if debug: 
                print(f"[DEBUG] Converted debugMode: {settings['debugMode']}")
            settings['tnsNamesLocation'] = config['Settings'].get('tnsNamesLocation', settings['tnsNamesLocation']) # Preserve TNS

            if debug: 
                print(f"[DEBUG] Converted tnsNamesLocation: {settings['tnsNamesLocation']}")
            settings['hourTimestampMethod'] = config['Settings'].get('hourTimestampMethod', settings['hourTimestampMethod']) # Preserve period

            if debug: 
                print(f"[DEBUG] Converted hourTimestampMethod: {settings['hourTimestampMethod']}")
            settings['lastQuickLook'] = config['Settings'].get('lastQuickLook', settings['lastQuickLook']) # Preserve quick look

            if debug: 
                print(f"[DEBUG] Converted lastQuickLook: {settings['lastQuickLook']}")
            settings['colorMode'] = config['Settings'].get('colorMode', settings['colorMode']) # Preserve color

            if debug: 
                print(f"[DEBUG] Converted colorMode: {settings['colorMode']}")
            settings['lastExportPath'] = config['Settings'].get('lastExportPath', settings['lastExportPath']) # Preserve export path

            if debug: 
                print(f"[DEBUG] Converted lastExportPath: {settings['lastExportPath']}")
        with open(newConfigPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2) # Write JSON
        if debug: 
            print("[DEBUG] Converted config.ini to user.config")
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

            if debug: 
                print(f"[DEBUG] Set cbQuickLook to index {index}: {lastQuickLook}")
        else:
            if debug: 
                print(f"[DEBUG] Last quick look '{lastQuickLook}' not found, setting to -1")
            cbQuickLook.setCurrentIndex(-1) # Fallback
    else:
        cbQuickLook.setCurrentIndex(-1) # No config, blank

def getUtcOffsetInt(utcOffsetStr):
    """Extract UTC offset as float from full string (e.g., 'UTC-09:30 | Marquesas Islands' -> -9.5)."""
    try:
        offsetPart = utcOffsetStr.split(' | ')[0].replace('UTC', '') # Get 'UTC-09:30'
        offsetParts = offsetPart.split(':') # Split on colon
        hours = int(offsetParts[0]) # Extract hours
        minutes = int(offsetParts[1]) if len(offsetParts) > 1 and offsetParts[1] else 0 # Extract minutes
        offset = hours + (minutes / 60.0) * (-1 if hours < 0 else 1) # Convert to float (e.g., -9:30 -> -9.5)

        if debug: 
            print("[DEBUG] getUtcOffsetInt: Parsed '{}' to {} hours".format(utcOffsetStr, offset))

        return offset
    except (ValueError, IndexError) as e:
        if debug: 
            print("[ERROR] getUtcOffsetInt: Failed to parse '{}': {}. Returning 0".format(utcOffsetStr, e))
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

                if debug: 
                    print("[DEBUG] Applied retro scroll bar styles to {}".format(widget.objectName()))
        app.setStyleSheet(app.styleSheet() + retroStyles)

        if debug: 
            print("[DEBUG] Applied retro scroll bar styles globally")
    else:
        # Reset to base stylesheet
        with open(resourcePath('ui/stylesheet.qss'), 'r') as f:
            app.setStyleSheet(f.read())
        for widget in [mainTable, webQueryList, internalQueryList]:
            if widget:
                widget.setStyleSheet("")

                if debug: 
                    print("[DEBUG] Cleared retro scroll bar styles from {}".format(widget.objectName()))
        if debug: 
            print("[DEBUG] Reverted to base stylesheet")