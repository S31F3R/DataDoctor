# py

import os
import sys
import json
import sqlite3
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from PyQt6.QtCore import QThreadPool, QDir
from PyQt6.QtWidgets import QTableWidgetItem, QFileDialog, QSplitter, QTreeView
from core import Config, Utils

# Flag to prevent multiple initializations (module-level for encapsulation)
_logging_initialized = False

def resourcePath(relativePath):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False): # Bundled mode
        basePath = sys._MEIPASS
    else: # Dev mode
        basePath = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Project root (parent of core/)
    Config.appRoot = basePath
    return os.path.normpath(os.path.join(basePath, relativePath))

def initLogging():
    global _logging_initialized

    if _logging_initialized:
        return # Already initialized
    
    logDir = Utils.getLogDir()
    os.makedirs(logDir, exist_ok=True)
    
    logger = logging.getLogger('Data Doctor')
    logger.setLevel(logging.DEBUG) # Capture all levels
    
    # Console handler: Print to terminal, format like current prints
    consoleHandler = logging.StreamHandler()
    consoleLevel = logging.DEBUG if Config.debug else logging.WARNING
    consoleHandler.setLevel(consoleLevel)
    consoleFormatter = logging.Formatter('[%(levelname)s] %(message)s')
    consoleHandler.setFormatter(consoleFormatter)
    logger.addHandler(consoleHandler)
    
    # File handler: Log to rotating file with timestamps
    filePath = Utils.getLogPath('app.log')
    fileHandler = RotatingFileHandler(filePath, maxBytes=1048576, backupCount=5, encoding='utf-8') # 1MB max, 5 backups
    fileHandler.setLevel(logging.DEBUG) # Log all
    fileFormatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    fileHandler.setFormatter(fileFormatter)
    logger.addHandler(fileHandler)
    
    _logging_initialized = True
    
    if Config.debug:
        logger.debug("initLogging: Logging initialized with console level {} and file at {}".format(logging.getLevelName(consoleLevel), filePath))

def logMessage(level, message):
    logger = logging.getLogger('Data Doctor')
    level = level.upper()

    if level == 'DEBUG':
        logger.debug(message)
    elif level == 'INFO':
        logger.info(message)
    elif level == 'WARN':
        logger.warning(message)
    elif level == 'ERROR':
        logger.error(message)
    elif level == 'CRITICAL':
        logger.critical(message)
    else:
        logger.warning(f"Unknown log level '{level}': {message}")

def buildDataDictionary(table):
    table.clear()
    dbPath = resourcePath('core/bunker.db')

    try:
        with sqlite3.connect(dbPath) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM dataDictionary")
            rows = cur.fetchall()

            if not rows:
                if Config.debug:
                    logMessage("DEBUG", "dataDictionary table empty")
                return
            headers = [desc[0] for desc in cur.description]
            table.setColumnCount(len(headers))

            for c, header in enumerate(headers):
                item = QTableWidgetItem(header.strip())
                table.setHorizontalHeaderItem(c, item)
            table.setRowCount(len(rows))

            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    valStr = str(value) if value is not None else ''
                    item = QTableWidgetItem(valStr)
                    table.setItem(r, c, item)
    except Exception as e:
        logMessage("ERROR", f"Failed to build DataDictionary from DB: {e}")
        return
    for c in range(table.columnCount()):
        table.resizeColumnToContents(c)
    if Config.debug:
        logMessage("DEBUG", f"Built DataDictionary with {table.rowCount()} rows, {table.columnCount()} columns")

def loadAllQuickLooks(cbQuickLook):
    cbQuickLook.clear()
    quickLookNames = set() # Use set to avoid duplicates
    
    # User-specific Quick Looks from query subfolder (prefer .json, but include .txt for legacy)
    userDir = Utils.getQuickLookDir()
    for ext in ['.json', '.txt']: # Scan .json first
        for file in os.listdir(userDir):
            if file.endswith(ext):
                name = os.path.splitext(file)[0] # Get name without extension

                if name not in quickLookNames:
                    quickLookNames.add(name)

                    if Config.debug:
                        logMessage("DEBUG", f"loadAllQuickLooks: Found user Quick Look: {file}")
    
    # Append example Quick Looks (no duplicates – only if not in user)
    exampleDir = Utils.getExampleQuickLookDir()

    for ext in ['.json', '.txt']: # Scan .json first
        for file in os.listdir(exampleDir):
            if file.endswith(ext):
                name = os.path.splitext(file)[0] # Get name without extension

                if name not in quickLookNames:
                    quickLookNames.add(name)

                    if Config.debug:
                        logMessage("DEBUG", f"loadAllQuickLooks: Added example Quick Look: {file}")
    
    # Add sorted names to combo box for consistent order
    sortedNames = sorted(quickLookNames)

    for name in sortedNames:
        cbQuickLook.addItem(name)
        if Config.debug:
            logMessage("DEBUG", f"loadAllQuickLooks: Added {name} to cbQuickLook")

def convertLegacyQuickLooks():
    quickLookDir = Utils.getQuickLookDir()

    if not os.path.exists(quickLookDir):
        if Config.debug:
            logMessage("DEBUG", "convertLegacyQuickLooks: Quick Look directory does not exist—skipped.")
        return
    
    for fileName in os.listdir(quickLookDir):
        if fileName.endswith('.txt'):
            txtPath = os.path.join(quickLookDir, fileName)
            name = fileName[:-4] # Remove .txt extension
            jsonPath = os.path.join(quickLookDir, f'{name}.json')
            
            if os.path.exists(jsonPath):
                if Config.debug:
                    logMessage("DEBUG", f"convertLegacyQuickLooks: JSON already exists for {name}—skipping {txtPath}")
                continue
            
            try:
                with open(txtPath, 'r', encoding='utf-8-sig') as f:
                    content = f.read().strip()
                if content:
                    if ',' in content:
                        # Legacy comma-separated format
                        data = content.split(',')
                    else:
                        # New line-separated format
                        data = content.splitlines()
                    processedData = []
                    for itemText in data:
                        itemText = itemText.strip()
                        if not itemText:
                            continue
                        parts = itemText.split('|')
                        if len(parts) == 3:
                            dataID, interval, database = parts

                            # Convert historical INSTANT queries to new format
                            if interval == 'INSTANT':
                                if database.startswith('USBR-'):
                                    interval = 'INSTANT:60'
                                elif database == 'USGS-NWIS':
                                    interval = 'INSTANT:15'
                                elif database == 'AQUARIUS':
                                    interval = 'INSTANT:1'
                            processedData.append(f'{dataID}|{interval}|{database}')
                
                # Save as JSON
                with open(jsonPath, 'w', encoding='utf-8') as f:
                    json.dump(processedData, f, indent=4)
                
                # Delete the .txt file
                os.remove(txtPath)
                
                if Config.debug:
                    logMessage("DEBUG", f"convertLegacyQuickLooks: Converted and deleted {txtPath} to {jsonPath}")
            except Exception as e:                
                logMessage("ERROR", f"convertLegacyQuickLooks: Failed to convert {txtPath}: {e}")

def saveQuickLook(textQuickLookName, listQueryList):
    name = textQuickLookName.toPlainText().strip() if hasattr(textQuickLookName, 'toPlainText') else str(textQuickLookName).strip()

    if not name:
        if Config.debug:
            logMessage("WARN", "Empty quick look name—skipped.")
        return
    data = [listQueryList.item(x).text() for x in range(listQueryList.count())]
    quicklookPath = os.path.join(Utils.getQuickLookDir(), f'{name}.json')
    os.makedirs(os.path.dirname(quicklookPath), exist_ok=True)

    try:
        with open(quicklookPath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        if Config.debug:
            logMessage("DEBUG", "saveQuickLook: Saved Quick Look to {}".format(quicklookPath))
    except Exception as e:        
        logMessage("ERROR", "saveQuickLook: Failed to save Quick Look to {}: {}".format(quicklookPath, e))

def loadQuickLook(cbQuickLook, listQueryList):
    quickLookName = cbQuickLook.currentText()

    if not quickLookName:
        if Config.debug:
            logMessage("DEBUG", "loadQuickLook: No quick look selected")
        return
    listQueryList.clear()
    userJsonPath = os.path.join(Utils.getQuickLookDir(), f'{quickLookName}.json')
    userTxtPath = os.path.join(Utils.getQuickLookDir(), f'{quickLookName}.txt') # Fallback for legacy
    exampleJsonPath = resourcePath(f'quickLook/{quickLookName}.json')
    exampleTxtPath = resourcePath(f'quickLook/{quickLookName}.txt') # Fallback for example legacy
    
    # Determine the path to load from, preferring JSON
    quickLookPath = None

    if os.path.exists(userJsonPath):
        quickLookPath = userJsonPath
    elif os.path.exists(userTxtPath):
        quickLookPath = userTxtPath
    elif os.path.exists(exampleJsonPath):
        quickLookPath = exampleJsonPath
    elif os.path.exists(exampleTxtPath):
        quickLookPath = exampleTxtPath
    
    if not quickLookPath:        
        logMessage("DEWARNBUG", "Quick look '{}' not found.".format(quickLookName))
        return
    
    try:
        if quickLookPath.endswith('.json'):
            with open(quickLookPath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else: # .txt
            with open(quickLookPath, 'r', encoding='utf-8-sig') as f:
                content = f.read().strip()
            if content:
                if ',' in content:
                    # Legacy comma-separated format
                    data = content.split(',')
                else:
                    # New line-separated format
                    data = content.splitlines()
            else:
                data = []
        
        for itemText in data:
            itemText = itemText.strip()
            if not itemText:
                continue
            parts = itemText.split('|')
            if len(parts) == 3:
                dataID, interval, database = parts

                # Convert historical INSTANT queries to new format
                if interval == 'INSTANT':
                    if database.startswith('USBR-'):
                        interval = 'INSTANT:60'
                    elif database == 'USGS-NWIS':
                        interval = 'INSTANT:15'
                    elif database == 'AQUARIUS':
                        interval = 'INSTANT:1'
                listQueryList.addItem(f'{dataID}|{interval}|{database}')

                if Config.debug:
                    logMessage("DEBUG", "loadQuickLook: Added item {}".format(f'{dataID}|{interval}|{database}'))
        
        if Config.debug:
            logMessage("DEBUG", "loadQuickLook: Loaded '{}' with {} items".format(quickLookName, listQueryList.count()))
        
        # If loaded from user .txt, convert to .json and delete .txt
        if quickLookPath == userTxtPath:
            saveQuickLook(quickLookName, listQueryList)
            os.remove(userTxtPath)
            if Config.debug:
                logMessage("DEBUG", f"loadQuickLook: Converted legacy {userTxtPath} to .json and deleted .txt")
    except Exception as e:        
        logMessage("ERROR", "loadQuickLook: Failed to load Quick Look from {}: {}".format(quickLookPath, e))

def deleteQuickLook(quickLookName):
    if not quickLookName:        
        logMessage("WARN", "Empty quick look name—cannot delete.")
        return False
    
    userQuickLookPath = os.path.join(Utils.getQuickLookDir(), f'{quickLookName}.json')
    
    if os.path.exists(userQuickLookPath):
        try:
            os.remove(userQuickLookPath)
            if Config.debug:
                logMessage("DEBUG", f"deleteQuickLook: Deleted Quick Look at {userQuickLookPath}")
            return True
        except Exception as e:
            if Config.debug:
                logMessage("DEBUG", f"deleteQuickLook: Failed to delete Quick Look at {userQuickLookPath}: {e}")
            return False
    else:
        logMessage("WARN", f"deleteQuickLook: Cannot delete example Quick Look '{quickLookName}'")
        return False

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        if Config.debug:
            logMessage("DEBUG", "exportTableToCSV: Empty table-no export")
        return
    settings = Utils.loadConfig()

    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Loaded full settings: {}".format(settings))

    lastPath = settings.get('lastExportPath', os.path.expanduser("~/Documents"))
    lastPath = os.path.normpath(os.path.abspath(lastPath)) if lastPath else None

    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Normalized lastPath: {}".format(lastPath))
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.normpath(os.path.expanduser("~/Documents"))
    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Used fallback Documents path")

    defaultDir = lastPath
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.normpath(os.path.join(defaultDir, defaultName))

    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Suggested path: {}".format(suggestedPath))

    dlg = QFileDialog(None)
    dlg.setWindowTitle("Save CSV As")
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setNameFilter("CSV files (*.csv)")
    dlg.selectFile(defaultName)
    dlg.setDirectory(QDir.fromNativeSeparators(defaultDir))
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)

    if Config.retroMode:
        Utils.applyRetroFont(dlg, 9)
        dlg.resize(1200, 600)
        dlg.setViewMode(QFileDialog.ViewMode.Detail)
    splitter = dlg.findChild(QSplitter)

    if splitter:
        splitter.setSizes([150, dlg.width() - 150])
    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Adjusted splitter sizes")
    mainView = dlg.findChild(QTreeView, "fileview")

    if not mainView:
        mainView = dlg.findChild(QTreeView)
    if mainView:
        header = mainView.header()

        for i in range(header.count()):
            mainView.resizeColumnToContents(i)
    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Resized main view columns")
    if dlg.exec():
        filePath = dlg.selectedFiles()[0]
    else:
        if Config.debug:
            logMessage("DEBUG", "exportTableToCSV: User canceled dialog")
        return

    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = ['Date/Time,' + ','.join(headers)]

    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Built headers: {}".format(csvLines[0]))
    timestamps = [table.verticalHeaderItem(r).text() if table.verticalHeaderItem(r) else '' for r in range(table.rowCount())]

    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(timestamps[r] + ',' + ','.join(rowData))
    try:
        with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\n'.join(csvLines))
        if Config.debug:
            logMessage("DEBUG", "exportTableToCSV: Successfully wrote CSV to {}".format(filePath))
    except Exception as e:
        if Config.debug:
            logMessage("DEBUG", "exportTableToCSV: Failed to write CSV: {}".format(e))
        return
    exportDir = os.path.normpath(os.path.dirname(filePath))

    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Updating lastExportPath to {}".format(exportDir))
    settings['lastExportPath'] = exportDir

    if Config.debug:
        logMessage("DEBUG", "exportTableToCSV: Full settings after update: {}".format(settings))
    configPath = Utils.getConfigPath()

    try:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2)
        if Config.debug:
            logMessage("DEBUG", "exportTableToCSV: Updated user.config with new lastExportPath-full file preserved")
    except Exception as e:
        if Config.debug:
            logMessage("DEBUG", "exportTableToCSV: Failed to update user.config: {}".format(e))

def valuePrecision(value):
    """Format value to 2 decimals if <10, 1 if 10-99, 0 if >=100."""
    if Config.rawData:
        return str(value)
    try:
        v = float(value)
        if v < 1000:
            return '%.2f' % v
        elif 1000 <= v < 10000:
            return '%.1f' % v
        else:
            return '%.0f' % v
    except ValueError:
        return value

def cleanShutdown():
    pool = QThreadPool.globalInstance()
    pool.waitForDone(5000)

def setQueryDateRange(window, radioButton, dteStartDate, dteEndDate):
    now = datetime.now()

    if radioButton == window.rbCustomDateTime:
        dteStartDate.setEnabled(True)
        dteEndDate.setEnabled(True)

        if dteStartDate.dateTime() >= dteEndDate.dateTime():
            dteStartDate.setDateTime(now - timedelta(hours=72))
            dteEndDate.setDateTime(now)
    elif radioButton == window.rbPrevDayToCurrent:
        dteStartDate.setEnabled(False)
        dteEndDate.setEnabled(False)
        yesterday = now - timedelta(days=1)
        dteStartDate.setDateTime(yesterday.replace(hour=1, minute=0, second=0))
        dteEndDate.setDateTime(now)
    elif radioButton == window.rbPrevWeekToCurrent:
        dteStartDate.setEnabled(False)
        dteEndDate.setEnabled(False)
        weekAgo = now - timedelta(days=7)
        dteStartDate.setDateTime(weekAgo.replace(hour=1, minute=0, second=0))
        dteEndDate.setDateTime(now)
    else:
        if Config.debug:
            logMessage("DEBUG", "Unknown radio button in setQueryDateRange")

def setDefaultButton(window, widget, btnAddQuery, btnQuery):
    if widget == window.qleDataID:
        btnAddQuery.setDefault(True)
        btnQuery.setDefault(False)
    else:
        btnAddQuery.setDefault(False)
        btnQuery.setDefault(True)

def initializeQueryWindow(ui, rbCustomDateTime, dteStartDate, dteEndDate):
    """Initialize query window controls"""
    if Config.debug:
        logMessage("DEBUG", "initializeQueryWindow: Setting initial state")

    rbCustomDateTime.setChecked(True)
    dteStartDate.setDateTime(datetime.now() - timedelta(hours=72))
    dteEndDate.setDateTime(datetime.now())

    if Config.debug:
        logMessage("DEBUG", "initializeQueryWindow: Set default dates and radio button")

def loadLastQuickLook(cbQuickLook):
    configPath = Utils.getConfigPath()
    config = {}

    if os.path.exists(configPath):
        try:
            with open(configPath, 'r', encoding='utf-8') as configFile:
                config = json.load(configFile)
            if Config.debug:
                logMessage("DEBUG", f"Loaded config for quick look: {config.get('lastQuickLook', 'none')}")
        except Exception as e:
            if Config.debug:
                logMessage("DEBUG", f"Failed to load user.config for quick look: {e}")
    if 'lastQuickLook' in config:
        lastQuickLook = config['lastQuickLook']
        index = cbQuickLook.findText(lastQuickLook)

        if index != -1:
            cbQuickLook.setCurrentIndex(index)

            if Config.debug:
                logMessage("DEBUG", f"Set cbQuickLook to index {index}: {lastQuickLook}")
        else:
            if Config.debug:
                logMessage("DEBUG", f"Last quick look '{lastQuickLook}' not found, setting to -1")
            cbQuickLook.setCurrentIndex(-1)
    else:
        cbQuickLook.setCurrentIndex(-1)

def getUtcOffsetInt(utcOffsetStr):
    """Extract UTC offset as float from full string (e.g., 'UTC-09:30 | Marquesas Islands' -> -9.5)."""
    try:
        offsetPart = utcOffsetStr.split(' | ')[0].replace('UTC', '')
        offsetParts = offsetPart.split(':')
        hours = int(offsetParts[0])
        minutes = int(offsetParts[1]) if len(offsetParts) > 1 and offsetParts[1] else 0
        offset = hours + (minutes / 60.0) * (-1 if hours < 0 else 1)
        
        if Config.debug:
            logMessage("DEBUG", "getUtcOffsetInt: Parsed '{}' to {} hours".format(utcOffsetStr, offset))
        return offset
    except (ValueError, IndexError) as e:
        if Config.debug:
            logMessage("ERROR", "getUtcOffsetInt: Failed to parse '{}': {}. Returning 0".format(utcOffsetStr, e))
        return 0.0