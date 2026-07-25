# Logic.py

import os
import sys
import re
import json
import sqlite3
import logging
import traceback
import threading
import faulthandler
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from PyQt6.QtCore import QThreadPool, QDir, QObject, pyqtSignal
from PyQt6.QtWidgets import QTableWidgetItem, QFileDialog, QSplitter, QTreeView
from core import Config, Utils

# Flag to prevent multiple initializations (module-level for encapsulation)
loggingInitialized = False
faultLogFile = None
exceptionHooksInstalled = False
qtMessageHandlerInstalled = False
qtMessageHandlerRef = None  # Must keep ref — PyQt GC's the handler otherwise
logNotifier = None  # LogNotifier for live log viewer (created in initLogging)


class LogNotifier(QObject):
    """Bridges Python logging to the Qt UI thread for live log viewing."""
    newLogEntry = pyqtSignal(str, str)  # level, formatted text


class qtLogHandler(logging.Handler):
    """
    Lightweight handler: format once and emit a signal.
    Receivers (log viewer) no-op when the Log tab is closed, so cost is negligible.
    emit() is safe from any thread; connect with QueuedConnection on the UI side.
    """
    def __init__(self, notifier):
        super().__init__()
        self.notifier = notifier
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.notifier.newLogEntry.emit(record.levelname, msg)
        except Exception:
            self.handleError(record)


def getLogNotifier():
    """Return the LogNotifier singleton, or None before initLogging."""
    return logNotifier

def resourcePath(relativePath):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False): # Bundled mode
        basePath = sys._MEIPASS
    else: # Dev mode
        basePath = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Project root (parent of core/)
    Config.appRoot = basePath
    return os.path.normpath(os.path.join(basePath, relativePath))

def initLogging():
    global loggingInitialized, logNotifier

    if loggingInitialized:
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

    # UI bridge for live log viewer (append-only when tab open; no-op otherwise)
    try:
        if logNotifier is None:
            logNotifier = LogNotifier()
        uiHandler = qtLogHandler(logNotifier)
        uiHandler.setLevel(logging.DEBUG)
        logger.addHandler(uiHandler)
    except Exception:
        # Live viewer is optional; never fail logging setup because of UI bridge
        pass
    
    loggingInitialized = True

    # Capture hard crashes (segfaults, etc.) into the same log when possible
    enableFaultHandler(filePath)

    # Python warnings → same file/console/UI handlers as app logs
    enableWarningCapture()

    # Qt category messages (filtered by QT_LOGGING_RULES) → app.log
    installQtMessageHandler()

    if Config.debug:
        rules = os.environ.get('QT_LOGGING_RULES', '')
        logger.debug(
            "initLogging: Logging initialized with console level {} and file at {} "
            "(QT_LOGGING_RULES={!r})".format(
                logging.getLevelName(consoleLevel), filePath, rules
            )
        )

def enableFaultHandler(filePath):
    """Dump fatal interpreter/native faults into app.log (best-effort)."""
    global faultLogFile
    try:
        if faultLogFile is not None:
            return
        faultLogFile = open(filePath, 'a', encoding='utf-8')
        faulthandler.enable(file=faultLogFile, all_threads=True)
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass


def enableWarningCapture():
    """Route Python warnings module output into the Data Doctor logger (with stack)."""
    try:
        logging.captureWarnings(True)
        wlog = logging.getLogger('py.warnings')
        wlog.setLevel(logging.DEBUG)
        wlog.propagate = False
        # Avoid stacking duplicate handlers on re-init edge cases
        if not any(isinstance(h, _WarningsBridgeHandler) for h in wlog.handlers):
            wlog.addHandler(_WarningsBridgeHandler())
    except Exception:
        pass


class _WarningsBridgeHandler(logging.Handler):
    """Forward py.warnings records into logMessage (WARN + message text)."""

    def emit(self, record):
        try:
            # warnings logger already includes file:line in the message when captureWarnings is on
            msg = self.format(record) if self.formatter else record.getMessage()
            logMessage('WARN', f"Python warning: {msg}")
        except Exception:
            pass


def installQtMessageHandler():
    """
    Route Qt runtime messages into app.log / log viewer.

    QT_LOGGING_RULES (env var, set before process start) still filters which
    categories emit. Messages that pass the filter are written here instead of
    only appearing on stderr.

    Examples:
      QT_LOGGING_RULES="*.debug=true" python DataDoctor.py
      QT_LOGGING_RULES="qt.qpa.*=true;*.debug=false" ...
    """
    global qtMessageHandlerInstalled, qtMessageHandlerRef
    if qtMessageHandlerInstalled:
        return
    try:
        from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
    except Exception as e:
        try:
            logMessage('WARN', f"installQtMessageHandler: Qt API unavailable: {e}")
        except Exception:
            pass
        return

    levelMap = {
        QtMsgType.QtDebugMsg: 'DEBUG',
        QtMsgType.QtInfoMsg: 'INFO',
        QtMsgType.QtWarningMsg: 'WARN',
        QtMsgType.QtCriticalMsg: 'ERROR',
        QtMsgType.QtFatalMsg: 'CRITICAL',
    }

    def handler(mode, context, message):
        # Keep this path ultra-safe — never raise out of a Qt message handler
        try:
            level = levelMap.get(mode, 'WARN')
            text = message if isinstance(message, str) else str(message)

            category = ''
            fileName = ''
            line = 0
            function = ''
            try:
                if context is not None:
                    category = getattr(context, 'category', None) or ''
                    fileName = getattr(context, 'file', None) or ''
                    line = int(getattr(context, 'line', 0) or 0)
                    function = getattr(context, 'function', None) or ''
            except Exception:
                pass

            parts = ['Qt']
            if category:
                parts.append(f'[{category}]')
            head = ' '.join(parts)
            loc = ''
            if fileName:
                loc = f' @ {fileName}:{line}'
                if function:
                    loc += f' in {function}'
            logMessage(level, f'{head}: {text}{loc}')
        except Exception:
            pass

    # Critical: store reference so SIP does not garbage-collect the callback
    qtMessageHandlerRef = handler
    qInstallMessageHandler(handler)
    qtMessageHandlerInstalled = True
    if Config.debug:
        logMessage(
            'DEBUG',
            f"installQtMessageHandler: installed "
            f"(QT_LOGGING_RULES={os.environ.get('QT_LOGGING_RULES', '')!r})",
        )


def logMessage(level, message):
    """Log a message. Safe to call even if initLogging has not run yet."""
    try:
        if not loggingInitialized:
            # Best-effort early logging to stderr before handlers exist
            print(f"[{level.upper()}] {message}", file=sys.stderr)
            return
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
    except Exception:
        # Never let logging itself crash the app
        try:
            print(f"[{level}] {message}", file=sys.stderr)
        except Exception:
            pass

def logException(context, exc=None):
    """
    Always log an exception with full traceback at ERROR level.
    Use this for catch-and-recover paths so crashes are recorded even when debug is off.

    Multi-line traceback body is one log record (continuations stick together in the
    log viewer via loadAllAppLogEntries).
    """
    try:
        if exc is not None:
            tbText = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logMessage("ERROR", f"{context}: {exc}\n{tbText.rstrip()}")
        else:
            # Prefer active exception; format_exc() is empty outside an except block
            excInfo = sys.exc_info()
            if excInfo[0] is not None:
                tbText = ''.join(traceback.format_exception(*excInfo))
                logMessage("ERROR", f"{context}\n{tbText.rstrip()}")
            else:
                # No active exception — still record a stack of the call site
                stack = ''.join(traceback.format_stack()[:-1])
                logMessage("ERROR", f"{context}\n(no active exception; call stack:)\n{stack.rstrip()}")
    except Exception:
        try:
            print(f"ERROR: {context}: {exc}", file=sys.stderr)
        except Exception:
            pass

# File log line: "2026-07-24 12:34:56,789 [ERROR] message"
logLineRe = re.compile(
    r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+\[([A-Za-z]+)\]\s?(.*)$'
)


def listAppLogFiles():
    """
    Return rotated app log paths newest-first: app.log, app.log.1, ... app.log.N
    (RotatingFileHandler: app.log is current; higher numbers are older).
    """
    logDir = Utils.getLogDir()
    if not os.path.isdir(logDir):
        return []
    files = []
    # Current + numbered backups (backupCount=5 → .1 .. .5)
    for name in os.listdir(logDir):
        if name == 'app.log' or (name.startswith('app.log.') and name[8:].isdigit()):
            files.append(os.path.join(logDir, name))

    def sortKey(path):
        base = os.path.basename(path)
        if base == 'app.log':
            return 0
        try:
            return int(base.split('.')[-1])
        except ValueError:
            return 999

    files.sort(key=sortKey)
    return files


def loadAllAppLogEntries(newestFirst=True):
    """
    Load all rotated app.log* files, group multi-line records, return list of dicts:
      { 'timestamp': datetime|None, 'level': str, 'text': str (full record) }

    Timeline order: newestFirst=True puts the most recent log entry first.
    """
    entries = []
    for path in listAppLogFiles():
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            logMessage("WARN", f"loadAllAppLogEntries: could not read {path}: {e}")
            continue

        current = None
        for raw in lines:
            line = raw.rstrip('\n')
            m = logLineRe.match(line)
            if m:
                if current is not None:
                    entries.append(current)
                tsStr, level, rest = m.group(1), m.group(2).upper(), m.group(3)
                ts = None
                for fmt in ('%Y-%m-%d %H:%M:%S,%f', '%Y-%m-%d %H:%M:%S'):
                    try:
                        ts = datetime.strptime(tsStr, fmt)
                        break
                    except ValueError:
                        pass
                current = {
                    'timestamp': ts,
                    'level': level,
                    'text': line,
                    'source': os.path.basename(path),
                }
            else:
                # Continuation (traceback, etc.) — attach to previous record
                if current is not None:
                    current['text'] = current['text'] + '\n' + line
                elif line.strip():
                    entries.append({
                        'timestamp': None,
                        'level': 'INFO',
                        'text': line,
                        'source': os.path.basename(path),
                    })
        if current is not None:
            entries.append(current)

    def entryKey(e):
        ts = e.get('timestamp')
        # Untimed lines sort as oldest so they don't float to the top
        if ts is None:
            return datetime.min
        return ts

    entries.sort(key=entryKey, reverse=bool(newestFirst))
    return entries


def installExceptionHooks(showDialog=True):
    """
    Install global handlers so uncaught exceptions (and their full tracebacks)
    are written to app.log and do not tear down the process.

    Covers:
      • sys.excepthook          — main-thread uncaught
      • threading.excepthook    — non-Qt thread uncaught
      • sys.unraisablehook      — __del__ / destructor failures
    KeyboardInterrupt / SystemExit still propagate normally.
    """
    global exceptionHooksInstalled
    if exceptionHooksInstalled:
        return

    def exceptionHook(excType, excValue, excTb):
        if issubclass(excType, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(excType, excValue, excTb)
            return
        try:
            tbText = ''.join(traceback.format_exception(excType, excValue, excTb)).rstrip()
            logMessage("CRITICAL", f"Uncaught exception:\n{tbText}")
        except Exception:
            try:
                sys.__excepthook__(excType, excValue, excTb)
            except Exception:
                pass
            return

        if not showDialog:
            return
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is None:
                return
            # Avoid dialog storms if many exceptions fire
            if getattr(app, 'dataDoctorShowingErrorDialog', False):
                return
            app.dataDoctorShowingErrorDialog = True
            try:
                QMessageBox.critical(
                    None,
                    "Unexpected Error",
                    "An unexpected error occurred and was logged.\n\n"
                    f"{excType.__name__}: {excValue}\n\n"
                    "The application will continue if possible.\n"
                    "See app.log for details."
                )
            finally:
                app.dataDoctorShowingErrorDialog = False
        except Exception:
            pass

    sys.excepthook = exceptionHook

    if hasattr(threading, 'excepthook'):
        def threadExceptionHook(args):
            if issubclass(args.exc_type, (SystemExit, KeyboardInterrupt)):
                return
            try:
                tbText = ''.join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )).rstrip()
                threadName = getattr(args.thread, 'name', '?')
                logMessage(
                    "CRITICAL",
                    f"Uncaught thread exception in {threadName}:\n{tbText}",
                )
            except Exception:
                pass
        threading.excepthook = threadExceptionHook

    # Failures during __del__ / GC (would otherwise only hit stderr)
    if hasattr(sys, 'unraisablehook'):
        def unraisableHook(unraisable):
            try:
                tbText = ''.join(traceback.format_exception(
                    unraisable.exc_type,
                    unraisable.exc_value,
                    unraisable.exc_traceback,
                )).rstrip()
                obj = getattr(unraisable, 'object', None)
                errMsg = getattr(unraisable, 'err_msg', None) or 'Unraisable exception'
                logMessage(
                    "ERROR",
                    f"{errMsg} (object={obj!r}):\n{tbText}",
                )
            except Exception:
                pass
        sys.unraisablehook = unraisableHook

    exceptionHooksInstalled = True
    if Config.debug:
        logMessage("DEBUG", "installExceptionHooks: Global exception hooks installed")

def buildDataDictionary(table, columns=None, whereClause=None):
    table.clear()
    dbPath = resourcePath('core/bunker.db')

    try:
        with sqlite3.connect(dbPath) as conn:
            cur = conn.cursor()
            selectCols = '*' if columns is None else ','.join(columns)
            query = f"SELECT {selectCols} FROM dataDictionary"

            if whereClause:
                query += f" WHERE {whereClause}"
            cur.execute(query)
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
        logException("Failed to build DataDictionary from DB", e)
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

def formatRawNumber(value):
    """
    Format a float for raw-data display without scientific notation.
    Tiny differences (e.g. 1e-12) show as 0.000000000001, not 1e-12.
    """
    try:
        v = float(value)
    except (ValueError, TypeError):
        return str(value) if value is not None else ''
    if v != v:  # NaN
        return ''
    if v == float('inf') or v == float('-inf'):
        return str(v)
    # Shortest round-trip first (avoids 123.450000000000003 noise)
    s = format(v, '.15g')
    if 'e' in s.lower():
        # Force fixed-point for tiny/huge magnitudes Python would show as 1e-12
        s = format(v, '.15f')
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
    if s in ('', '-0'):
        s = '0'
    return s

def valuePrecision(value):
    """Format value to 2 decimals if |v|<1000, 1 if 1000-9999, 0 if >=10000.

    Raw mode: full precision in fixed-point (never scientific notation).
    """
    try:
        v = float(value)
    except (ValueError, TypeError):
        return value

    if Config.rawData:
        return formatRawNumber(v)
    if abs(v) < 1000:
        return '%.2f' % v
    elif abs(v) < 10000:
        return '%.1f' % v
    else:
        return '%.0f' % v

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
    
def filterTable(table, searchText, searchableColumns):
    """Modular function to filter QTableWidget rows based on search text in specified columns."""
    if Config.debug:
        logMessage("DEBUG", f"filterTable: Processing table with {table.rowCount()} rows, search '{searchText}', columns {searchableColumns}")

    # Map column names to indices (case-sensitive match to headers)
    columnMap = {table.horizontalHeaderItem(c).text().strip(): c for c in range(table.columnCount())}
    searchableIndices = [columnMap[col] for col in searchableColumns if col in columnMap]

    if not searchableIndices:
        if Config.debug:
            logMessage("WARN", "filterTable: No matching searchable columns found—showing all rows")
        for r in range(table.rowCount()):
            table.setRowHidden(r, False)
        return

    if not searchText.strip():
        # Empty search: Show all rows
        for r in range(table.rowCount()):
            table.setRowHidden(r, False)
        if Config.debug:
            logMessage("DEBUG", "filterTable: Empty search—showing all rows")
        return

    # Split search into keywords (space-separated, AND logic)
    keywords = [kw.lower() for kw in searchText.strip().split() if kw]
    visibleCount = 0

    for r in range(table.rowCount()):
        matches = True

        for kw in keywords:
            kwMatched = False

            for c in searchableIndices:
                item = table.item(r, c)
                cellText = item.text().strip().lower() if item else ''

                if kw in cellText:
                    kwMatched = True
                    break
            if not kwMatched:
                matches = False
                break
        table.setRowHidden(r, not matches)

        if matches:
            visibleCount += 1

    if Config.debug:
        logMessage("DEBUG", f"filterTable: Filtered to {visibleCount} visible rows out of {table.rowCount()}")