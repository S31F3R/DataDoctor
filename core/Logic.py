import os
import sys
import time
import json
import queue
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QTimer, QCoreApplication
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QSizePolicy, QProgressDialog
from collections import defaultdict
from core import USBR, USGS, Aquarius, Config, Utils

def resourcePath(relativePath):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False): # Bundled mode
        basePath = sys._MEIPASS
    else: # Dev mode
        basePath = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Project root (parent of core/)
    Config.appRoot = basePath
    return os.path.normpath(os.path.join(basePath, relativePath))

def buildDataDictionary(table):
    table.clear()

    with open(resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
        data = [line.strip().split(',') for line in f.readlines()]
    if not data:
        if Config.debug:
            print("[DEBUG] DataDictionary.csv empty")
        return
    table.setRowCount(len(data) - 1)
    table.setColumnCount(len(data[0]))

    for c, header in enumerate(data[0]):
        item = QTableWidgetItem(header.strip())
        table.setHorizontalHeaderItem(c, item)
    for r in range(1, len(data)):
        for c in range(len(data[r])):
            value = data[r][c].strip()
            item = QTableWidgetItem(value)
            table.setItem(r-1, c, item)
    for c in range(table.columnCount()):
        table.resizeColumnToContents(c)
    if Config.debug:
        print(f"[DEBUG] Built DataDictionary with {table.rowCount()} rows, {table.columnCount()} columns")

def loadAllQuickLooks(cbQuickLook):
    cbQuickLook.clear()
    quickLookPaths = []

    # User-specific Quick Looks from query subfolder
    userDir = Utils.getQuickLookDir()

    for file in os.listdir(userDir):
        if file.endswith(".txt"):
            quickLookPaths.append(os.path.join(userDir, file))

            if Config.debug:
                print("[DEBUG] loadAllQuickLooks: Found user Quick Look: {}".format(file))

    # Append example Quick Looks (no duplicates – check names)
    exampleDir = Utils.getExampleQuickLookDir()

    for file in os.listdir(exampleDir):
        if file.endswith(".txt"):
            examplePath = os.path.join(exampleDir, file)
            userPath = os.path.join(userDir, file)

            if not os.path.exists(userPath):
                quickLookPaths.append(examplePath)

                if Config.debug:
                    print("[DEBUG] loadAllQuickLooks: Added example Quick Look: {}".format(file))

    # Add to combo (use basename without .txt)
    for path in quickLookPaths:
        name = os.path.basename(path).replace('.txt', '')
        cbQuickLook.addItem(name)

        if Config.debug:
            print("[DEBUG] loadAllQuickLooks: Added {} to cbQuickLook".format(name))

def saveQuickLook(textQuickLookName, listQueryList):
    name = textQuickLookName.toPlainText().strip() if hasattr(textQuickLookName, 'toPlainText') else str(textQuickLookName).strip()

    if not name:
        print("[WARN] Empty quick look name—skipped.")
        return

    data = [listQueryList.item(x).text() for x in range(listQueryList.count())]
    quicklookPath = os.path.join(Utils.getQuickLookDir(), f'{name}.txt')
    os.makedirs(os.path.dirname(quicklookPath), exist_ok=True)

    try:
        with open(quicklookPath, 'w', encoding='utf-8-sig') as f:
            f.write(','.join(data))
        if Config.debug:
            print("[DEBUG] saveQuickLook: Saved Quick Look to {}".format(quicklookPath))
    except Exception as e:
        if Config.debug:
            print("[ERROR] saveQuickLook: Failed to save Quick Look to {}: {}".format(quicklookPath, e))

def loadQuickLook(cbQuickLook, listQueryList):
    quickLookName = cbQuickLook.currentText()

    if not quickLookName:
        if Config.debug:
            print("[DEBUG] loadQuickLook: No quick look selected")
        return

    listQueryList.clear()
    userQuickLookPath = os.path.join(Utils.getQuickLookDir(), '{}.txt'.format(quickLookName))
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
                        if database.startswith('USBR-'):
                            interval = 'INSTANT:60'
                        elif database == 'USGS-NWIS':
                            interval = 'INSTANT:15'
                        elif database == 'AQUARIUS':
                            interval = 'INSTANT:1'
                    listQueryList.addItem('{}|{}|{}'.format(dataID, interval, database))

                    if Config.debug:
                        print("[DEBUG] loadQuickLook: Added item {}".format('{}|{}|{}'.format(dataID, interval, database)))
    except FileNotFoundError:
        print("[WARN] Quick look '{}' not found.".format(quickLookName))
    if Config.debug:
        print("[DEBUG] loadQuickLook: Loaded '{}' with {} items".format(quickLookName, listQueryList.count()))

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        if Config.debug:
            print("[DEBUG] exportTableToCSV: Empty table-no export")
        return
    settings = Utils.loadConfig()

    if Config.debug:
        print("[DEBUG] exportTableToCSV: Loaded full settings: {}".format(settings))

    lastPath = settings.get('lastExportPath', os.path.expanduser("~/Documents"))
    lastPath = os.path.normpath(os.path.abspath(lastPath)) if lastPath else None

    if Config.debug:
        print("[DEBUG] exportTableToCSV: Normalized lastPath: {}".format(lastPath))
    if not lastPath or not os.path.exists(lastPath):
        lastPath = os.path.normpath(os.path.expanduser("~/Documents"))
    if Config.debug:
        print("[DEBUG] exportTableToCSV: Used fallback Documents path")

    defaultDir = lastPath
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    defaultName = f"{timestamp} Export.csv"
    suggestedPath = os.path.normpath(os.path.join(defaultDir, defaultName))
    
    if Config.debug:
        print("[DEBUG] exportTableToCSV: Suggested path: {}".format(suggestedPath))

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
        print("[DEBUG] exportTableToCSV: Adjusted splitter sizes")
    mainView = dlg.findChild(QTreeView, "fileview")

    if not mainView:
        mainView = dlg.findChild(QTreeView)
    if mainView:
        header = mainView.header()

        for i in range(header.count()):
            mainView.resizeColumnToContents(i)
    if Config.debug:
        print("[DEBUG] exportTableToCSV: Resized main view columns")
    if dlg.exec():
        filePath = dlg.selectedFiles()[0]
    else:
        if Config.debug:
            print("[DEBUG] exportTableToCSV: User canceled dialog")
        return

    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csvLines = ['Date/Time,' + ','.join(headers)]

    if Config.debug:
        print("[DEBUG] exportTableToCSV: Built headers: {}".format(csvLines[0]))
    timestamps = [table.verticalHeaderItem(r).text() if table.verticalHeaderItem(r) else '' for r in range(table.rowCount())]
    
    for r in range(table.rowCount()):
        rowData = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csvLines.append(timestamps[r] + ',' + ','.join(rowData))
    try:
        with open(filePath, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\n'.join(csvLines))
        if Config.debug:
            print("[DEBUG] exportTableToCSV: Successfully wrote CSV to {}".format(filePath))
    except Exception as e:
        if Config.debug:
            print("[DEBUG] exportTableToCSV: Failed to write CSV: {}".format(e))
        return
    exportDir = os.path.normpath(os.path.dirname(filePath))

    if Config.debug:
        print("[DEBUG] exportTableToCSV: Updating lastExportPath to {}".format(exportDir))
    settings['lastExportPath'] = exportDir

    if Config.debug:
        print("[DEBUG] exportTableToCSV: Full settings after update: {}".format(settings))
    configPath = Utils.getConfigPath()

    try:
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2)
        if Config.debug:
            print("[DEBUG] exportTableToCSV: Updated user.config with new lastExportPath-full file preserved")
    except Exception as e:
        if Config.debug:
            print("[DEBUG] exportTableToCSV: Failed to update user.config: {}".format(e))

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
            print("[DEBUG] Unknown radio button in setQueryDateRange")

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
        print("[DEBUG] initializeQueryWindow: Setting initial state")

    rbCustomDateTime.setChecked(True)
    dteStartDate.setDateTime(datetime.now() - timedelta(hours=72))
    dteEndDate.setDateTime(datetime.now())

    if Config.debug:
        print("[DEBUG] initializeQueryWindow: Set default dates and radio button")

def loadLastQuickLook(cbQuickLook):
    configPath = Utils.getConfigPath()
    config = {}

    if os.path.exists(configPath):
        try:
            with open(configPath, 'r', encoding='utf-8') as configFile:
                config = json.load(configFile)
            if Config.debug:
                print(f"[DEBUG] Loaded config for quick look: {config.get('lastQuickLook', 'none')}")
        except Exception as e:
            if Config.debug:
                print(f"[DEBUG] Failed to load user.config for quick look: {e}")
    if 'lastQuickLook' in config:
        lastQuickLook = config['lastQuickLook']
        index = cbQuickLook.findText(lastQuickLook)

        if index != -1:
            cbQuickLook.setCurrentIndex(index)
            if Config.debug:
                print(f"[DEBUG] Set cbQuickLook to index {index}: {lastQuickLook}")
        else:
            if Config.debug:
                print(f"[DEBUG] Last quick look '{lastQuickLook}' not found, setting to -1")
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
            print("[DEBUG] getUtcOffsetInt: Parsed '{}' to {} hours".format(utcOffsetStr, offset))
        return offset
    except (ValueError, IndexError) as e:
        if Config.debug:
            print("[ERROR] getUtcOffsetInt: Failed to parse '{}': {}. Returning 0".format(utcOffsetStr, e))
        return 0.0