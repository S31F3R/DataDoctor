# DataDoctor.py

import sys
import os
import csv
import json
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QTabWidget, QWidget, QGridLayout, QTableWidgetItem,
                             QSizePolicy, QMessageBox, QFileDialog, QMenu, QComboBox, QPlainTextEdit, QListWidget, QInputDialog,
                             QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QAbstractItemView)
from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, QEvent, pyqtSignal, QTimer
from PyQt6.QtGui import QPalette, QIcon, QTextCharFormat, QTextBlockFormat, QColor, QTextCursor, QFont
from PyQt6 import uic
from core import Logic, Query, Utils, Config, Upload, Update
from ui.uiAbout import uiAbout
from ui.uiDataDictionary import uiDataDictionary
from ui.uiOptions import uiOptions, warmKeyringCache
from ui.uiQuery import uiQuery
from ui.uiDetails import uiDetails
from ui.uiGraph import GraphPanel
from ui.uiSql import SqlWorkbench
from core.Oracle import oracleConnection

class detachedTabWindow(QMainWindow):
    """
    Floating host for Graph or Log Viewer with the same tab chrome as the main window.
    Right-click the tab → Attach; closing the window also re-attaches.
    """

    def __init__(self, mainWindow, contentWidget, title, key):
        super().__init__(None)
        self.mainWindow = mainWindow
        self.contentWidget = contentWidget
        self.tabTitle = title
        self.key = key  # 'graph' | 'log' | 'sql'
        self._attaching = False

        self.setWindowTitle(f"Data Doctor — {title}")
        self.setWindowIcon(mainWindow.windowIcon() if mainWindow else QIcon())
        self.resize(1000, 700)
        self.setMinimumSize(400, 300)

        self.hostTabs = QTabWidget(self)
        self.hostTabs.setTabsClosable(False)
        self.hostTabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Reparent content into this window's tab strip (keeps tab look)
        self.hostTabs.addTab(contentWidget, title)
        self.setCentralWidget(self.hostTabs)

        tabBar = self.hostTabs.tabBar()
        tabBar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tabBar.customContextMenuRequested.connect(self.onTabBarContextMenu)

    def onTabBarContextMenu(self, pos):
        idx = self.hostTabs.tabBar().tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self)
        attachAct = menu.addAction("Attach")
        chosen = menu.exec(self.hostTabs.tabBar().mapToGlobal(pos))
        if chosen == attachAct:
            self.attachBack()

    def attachBack(self):
        if self._attaching:
            return
        self._attaching = True
        try:
            if self.mainWindow is not None:
                self.mainWindow.attachDetachedTab(self.key)
        finally:
            self._attaching = False

    def closeEvent(self, event):
        # Closing the floating window returns the tab to main (does not destroy content)
        if not self._attaching and self.mainWindow is not None:
            self._attaching = True
            try:
                self.mainWindow.attachDetachedTab(self.key)
            finally:
                self._attaching = False
        event.accept()

class mainTableKeyFilter(QObject):
    """
    Keyboard shortcuts on the main data table:
      Delete  — clear selected editable cells
      Ctrl+C  — copy selection (TSV)
      Ctrl+V  — paste into selection as edits (internal only)
    """

    def __init__(self, mainWindow):
        super().__init__(mainWindow)
        self.mainWindow = mainWindow

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier) or bool(
                mods & Qt.KeyboardModifier.MetaModifier
            )
            if key == Qt.Key.Key_Delete and not ctrl:
                if Upload.clearSelectedCells(self.mainWindow):
                    return True
            if ctrl and key == Qt.Key.Key_C:
                if Upload.copySelectionToClipboard(self.mainWindow):
                    return True
            if ctrl and key == Qt.Key.Key_V:
                if Upload.pasteClipboardToSelection(self.mainWindow):
                    return True
        return super().eventFilter(obj, event)

class sqlQuerySignals(QObject):
    finished = pyqtSignal(object)   # list of row dicts
    failed = pyqtSignal(str, bool)  # message, isAuthError

class sqlQueryWorker(QRunnable):
    """Run Oracle custom SQL off the UI thread so the main window stays responsive."""
    def __init__(self, dsn, sqlText, signals):
        super().__init__()
        self.dsn = dsn
        self.sqlText = sqlText
        self.signals = signals

    def run(self):
        conn = None
        try:
            from core.Oracle import OracleAuthError
            conn = oracleConnection(self.dsn)
            conn.connect()
            results = conn.executeCustomQuery(self.sqlText)
            self.signals.finished.emit(results if results is not None else [])
        except Exception as e:
            isAuth = False
            try:
                from core.Oracle import OracleAuthError, isAuthError
                isAuth = isinstance(e, OracleAuthError) or isAuthError(e)
            except Exception:
                pass
            Logic.logException("sqlQueryWorker: Failed to execute", e)
            self.signals.failed.emit(str(e), isAuth)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

class uiMain(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(Logic.resourcePath('ui/winMain.ui'), self)             

        # Define controls
        self.btnPublicQuery = self.findChild(QPushButton, 'btnPublicQuery')
        self.mainTable = self.findChild(QTableWidget, 'mainTable')

        # Built-in header sort OFF: single-click highlights; double-click customSort
        if self.mainTable is not None: self.mainTable.setSortingEnabled(False)
        self.btnDataDictionary = self.findChild(QPushButton, 'btnDataDictionary')
        self.btnExportCSV = self.findChild(QPushButton, 'btnExportCSV')
        self.btnOptions = self.findChild(QPushButton, 'btnOptions')
        self.btnInfo = self.findChild(QPushButton, 'btnInfo')
        self.btnViewLog = self.findChild(QPushButton, 'btnViewLog')
        self.btnInternalQuery = self.findChild(QPushButton, 'btnInternalQuery')
        self.btnSQL = self.findChild(QPushButton, 'btnSQL')
        self.btnGraph = self.findChild(QPushButton, 'btnGraph')
        self.btnGoat = self.findChild(QPushButton, 'btnGoat')
        self.btnRefresh = self.findChild(QPushButton, 'btnRefresh')
        self.btnUndo = self.findChild(QPushButton, 'btnUndo')
        self.btnUpload = self.findChild(QPushButton, 'btnUpload')
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
        self.tabMain = self.findChild(QWidget, 'tabMain')
        self.tabSQL = self.findChild(QWidget, 'tabSQL')
        self.tabLog = self.findChild(QWidget, 'tabLog')
        self.tabGraph = None # created on first graph (GraphPanel)
        self.pteLog = self.findChild(QPlainTextEdit, 'pteLog')
        self.lastQueryType = None
        self.lastQueryItems = []
        self.lastStartDate = None
        self.lastEndDate = None
        self.columnMetadata = []
        self.seriesResponses = {} # Dict to store {seriesLabel: responseDict} post-query
        self.currentQueryType = "" # str: "AQUARIUS", etc., set post-query
        self.uploadBaselineReady = False
        self.uploadTrackingBlocked = False

        # Detached floating windows ({'graph'|'log'|'sql': detachedTabWindow})
        self.detachedWindows = {}
        self.sqlWorkbench = None
        self._appIcon = QIcon() # set from main after load (Windows re-apply)
        self._goatPlayer = None
        self._goatAudio = None
        self.btnRunQuery = self.findChild(QPushButton, 'btnRunQuery')
        self.btnSaveSnippet = self.findChild(QPushButton, 'btnSaveSnippet')
        self.cbDatabase = self.findChild(QComboBox, 'cbDatabase')
        self.pteSQL = self.findChild(QPlainTextEdit, 'pteSQL')
        self.listSnippets = self.findChild(QListWidget, 'listSnippets')
        self.sqlTable = self.findChild(QTableWidget, 'sqlTable')
        self.btnDeleteSnippet = self.findChild(QPushButton, 'btnDeleteSnippet')        

        # Map button style (iconName → ui/icons/{name}.png; hover/pressed fall back to normal)
        buttonIcons = [
                        (self.btnPublicQuery, "PublicQuery", 36),
                        (self.btnDataDictionary, "Book", 36),
                        (self.btnExportCSV, "ExportCSV", 36),
                        (self.btnOptions, "Options", 36),
                        (self.btnViewLog, "Notebook", 36),
                        (self.btnGoat, "Goat", 36),
                        (self.btnInfo, "Info", 36),
                        (self.btnInternalQuery, "InternalQuery", 36),
                        (self.btnSQL, "SQL", 36),
                        (self.btnGraph, "Graph", 36),
                        (self.btnUndo, "Reset", 36),
                        (self.btnRefresh, "Refresh", 36),
                        (self.btnUpload, "Upload", 36),
                        (self.btnRunQuery, "Play", 36),
                      ]

        # Set button style        
        for btn, iconName, iconSize in buttonIcons:
            if btn is not None: Utils.buttonStyle(btn, iconName, iconSize=iconSize)

        # Ensure every main toolbar / data-tab button has a tooltip
        # Keep labels short (no parenthetical lists on Public/Internal/Options)
        mainTooltips = {
            self.btnPublicQuery: "Public Queries",
            self.btnInternalQuery: "Internal Queries",
            self.btnSQL: "SQL Query Builder",
            self.btnGraph: "Graph data table",
            self.btnDataDictionary: "Data Dictionary",
            self.btnExportCSV: "Export current table to CSV",
            self.btnOptions: "Options",
            self.btnViewLog: "View application logs",
            self.btnGoat: "FOR EMERGENCIES ONLY!!!",
            self.btnInfo: "About Data Doctor",
            self.btnRefresh: "Refresh current query",
            self.btnUndo: "Reset column sort to timestamp order",
            self.btnUpload: "Upload edited cells to HDB (MODIFY / DELETE)",
            self.btnRunQuery: "Run SQL query",
        }

        for btn, tip in mainTooltips.items():
            if btn is not None:
                btn.setToolTip(tip)

        # Set up layout
        centralLayout = self.centralWidget().layout()

        if isinstance(centralLayout, QGridLayout):
            centralLayout.setContentsMargins(0, 0, 0, 0)
            centralLayout.setRowStretch(0, 0)
            centralLayout.setRowStretch(1, 1)
            centralLayout.setColumnStretch(0, 1)

        # Create events
        self.btnPublicQuery.clicked.connect(self.btnPublicQueryPressed)
        self.btnDataDictionary.clicked.connect(self.showDataDictionary)
        self.btnExportCSV.clicked.connect(self.btnExportCSVPressed)
        self.btnOptions.clicked.connect(self.btnOptionsPressed)
        self.btnInfo.clicked.connect(self.btnInfoPressed)

        if self.btnViewLog:self.btnViewLog.clicked.connect(self.btnViewLogPressed)
        self.btnInternalQuery.clicked.connect(self.btnInternalQueryPressed)

        if self.btnSQL is not None: self.btnSQL.clicked.connect(self.btnSQLPressed)
        if self.btnGraph is not None: self.btnGraph.clicked.connect(self.btnGraphPressed)
        if self.btnGoat is not None: self.btnGoat.clicked.connect(self.btnGoatPressed)
        self.btnRefresh.clicked.connect(self.btnRefreshPressed)
        self.btnUndo.clicked.connect(self.btnUndoPressed)
        if self.btnUpload:self.btnUpload.clicked.connect(self.btnUploadPressed)

        # Single-click header → highlight column; double-click → sort
        self.mainTable.horizontalHeader().sectionClicked.connect(self.onMainHeaderClicked)
        self.mainTable.horizontalHeader().sectionDoubleClicked.connect(self.onMainHeaderDoubleClicked)
        self.mainTable.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainTable.horizontalHeader().customContextMenuRequested.connect(self.showHeaderContextMenu)
        self.mainTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainTable.customContextMenuRequested.connect(self.showCellContextMenu)
        self.mainTable.itemChanged.connect(self.onMainTableItemChanged)

        # Multi-cell ranges for Excel-like copy/paste
        self.mainTable.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.mainTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)

        # Delete / Ctrl+C / Ctrl+V on the data table
        self.mainTableKeyFilter = mainTableKeyFilter(self)
        self.mainTable.installEventFilter(self.mainTableKeyFilter)
        self.mainTable.viewport().installEventFilter(self.mainTableKeyFilter)

        # Edit triggers / locks applied after each query via Upload.snapshotBaseline
        # Multi-column selection → highlight every selected column header
        Upload.ensureHeaderSelectionSync(self)
        self.tabWidget.tabCloseRequested.connect(self.onTabCloseRequested)

        # Graph + Log + SQL: right-click tab → Detach tab
        if self.tabWidget is not None:
            tabBar = self.tabWidget.tabBar()
            tabBar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tabBar.customContextMenuRequested.connect(self.onMainTabBarContextMenu)
        # SQL snippets: drag-reorder + context menu up/down; order in user.config
        # NOTE: empty QListWidget is falsy in PyQt6 (len==0) — always test is not None
        if self.listSnippets is not None:
            self.listSnippets.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.listSnippets.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.listSnippets.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.listSnippets.customContextMenuRequested.connect(self.showSnippetContextMenu)

            try:
                self.listSnippets.model().rowsMoved.connect(self.onSnippetsReordered)
            except Exception:
                pass
            self.listSnippets.setToolTip("Drag to reorder, or right-click Move Up/Down/Delete")

        # Ensure tab widget expands
        self.tabWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Set up Data Query tab
        self.tabMain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if self.sqlTable is not None:
            self.sqlTable.horizontalHeader().setStretchLastSection(False)

        if not self.tabMain.layout():
            layout = QGridLayout(self.tabMain)
            layout.addWidget(self.mainTable)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        self.mainTable.setGeometry(0, 0, 0, 0)
        self.mainTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Center window
        Utils.centerWindowToParent(self)

        # Initialize globals
        Utils.reloadGlobals()

        # Hide tabs on startup
        sqlTab = self.tabSQL
        sqlIndex = self.tabWidget.indexOf(sqlTab) if sqlTab else -1

        # Store titles after removal (in case .ui changes)
        self.dataQueryTitle = "Data Query"
        self.sqlTitle = "SQL Query Builder"
        self.graphTitle = "Graph"
        self.logTitle = "Log Viewer"

        # Log viewer tab: layout pteLog to fill, hide until opened via btnViewLog
        if self.tabLog:
            if not self.tabLog.layout():
                logLayout = QVBoxLayout(self.tabLog)
                logLayout.setContentsMargins(0, 0, 0, 0)
                if self.pteLog:
                    logLayout.addWidget(self.pteLog)
            if self.pteLog:
                self.pteLog.setReadOnly(True)
                self.pteLog.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                self.pteLog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.tabLog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Live log updates: append while Log tab is open (no-op when closed — no refresh button)
        notifier = Logic.getLogNotifier()
        if notifier is not None:
            notifier.newLogEntry.connect(
                self.appendLogEntry,
                Qt.ConnectionType.QueuedConnection,
            )

        # SQL Query Builder workbench (worksheets, pin, history, categories)
        if sqlTab:
            self.sqlWorkbench = SqlWorkbench(self)
            if Config.debug:
                Logic.logMessage("DEBUG", "Set up SQL Query Builder workbench")

        if sqlIndex != -1:
            self.tabWidget.removeTab(sqlIndex)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Removed tabSQL at index {sqlIndex} on startup")
        else:
            if Config.debug:
                Logic.logMessage("WARN", "tabSQL not found in tabWidget on startup")

        # Hide log tab on startup (open via btnViewLog)
        logIndex = self.tabWidget.indexOf(self.tabLog) if self.tabLog else -1

        if logIndex != -1:
            self.tabWidget.removeTab(logIndex)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Removed tabLog at index {logIndex} on startup")
        dataQueryIndex = self.tabWidget.indexOf(self.tabMain)

        if dataQueryIndex != -1:
            self.tabWidget.removeTab(dataQueryIndex)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Removed tabMain at index {dataQueryIndex} on startup")
        else:
            if Config.debug:
                Logic.logMessage("WARN", "tabMain not found in tabWidget on startup")

        # Add dummy items to controls. This fixes issues with Qt6 quirks
        self.cbDatabase.addItem("")    
        self.listSnippets.addItem("")        

        # SQL tab stays hidden on startup (open via btnSQL toggle, like Data Query)
        if Config.debug:
            Logic.logMessage("DEBUG", "uiMain initialized with header context menu, Config.rawData: {}".format(Config.rawData))

    def closeEvent(self, event):
        """Save splitter sizes, tear down children, and actually quit the process."""
        if getattr(self, "_quitting", False):
            event.accept()
            return
        self._quitting = True
        Logic.appIsQuitting = True
        self._removeHeaderSelectFilters()

        try:
            sqlTab = self.tabSQL or self.findChild(QWidget, 'tabSQL')

            if (
                sqlTab is not None
                and self.tabWidget is not None
                and self.tabWidget.indexOf(sqlTab) != -1
            ):
                sqlSplitter = self.findChild(QSplitter, 'sqlSplitter')
                mainSplitter = self.findChild(QSplitter, 'mainSplitter')
                if sqlSplitter is not None and mainSplitter is not None:
                    config = Utils.loadConfig()
                    config['sqlVerticalSizes'] = sqlSplitter.sizes()
                    config['sqlHorizontalSizes'] = mainSplitter.sizes()

                    try:
                        with open(Utils.getConfigPath(), 'w', encoding='utf-8') as configFile:
                            json.dump(config, configFile, indent=2)
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"Saved splitter sizes to config: vertical={config['sqlVerticalSizes']}, horizontal={config['sqlHorizontalSizes']}")
                    except Exception as e:
                        Logic.logException("Failed to save splitter sizes", e)
        except Exception as e:
            Logic.logException("closeEvent failed", e)
        about = getattr(self, "winAbout", None)

        if about is not None:
            try:
                about._closing = True
                about.stopMusic()
                about._resetToDefaultAbout()
                about.close()
            except Exception:
                pass
        try:
            import pygame
            if pygame.get_init():
                pygame.quit()
        except Exception:
            pass
        try:
            QThreadPool.globalInstance().waitForDone(400)
        except Exception:
            pass
        app = QApplication.instance()

        if app is not None:
            try:
                app.closeAllWindows()
            except Exception:
                pass
            QTimer.singleShot(0, app.quit)
        event.accept()
        super().closeEvent(event)

    def _removeHeaderSelectFilters(self):
        """Detach header click filters before Qt deletes the table on close."""
        table = getattr(self, "mainTable", None)
        if table is None:
            return
        filt = getattr(table, "_headerSelectFilter", None)
        if filt is None:
            return
        try:
            header = table.horizontalHeader()
        except RuntimeError:
            header = None
        for widget in (table, header, getattr(header, "viewport", lambda: None)()):
            if widget is None:
                continue
            try:
                widget.removeEventFilter(filt)
            except RuntimeError:
                pass
            except Exception:
                pass
        try:
            table._headerSelectFilter = None
        except Exception:
            pass

    def showEvent(self, event):
        """Re-apply app icon after the window is shown (Windows first-paint glitch)."""
        super().showEvent(event)
        icon = getattr(self, '_appIcon', None)

        if icon is not None and not icon.isNull():
            try:
                self.setWindowIcon(icon)
                app = QApplication.instance()
                if app is not None:
                    app.setWindowIcon(icon)
            except Exception:
                pass

    def loadSnippets(self):
        """Load SQL snippets (filtered by the workbench category combo)."""
        if self.sqlWorkbench is not None:
            self.sqlWorkbench.loadSnippets()
            return
        if self.listSnippets is None:
            return
        try:
            sqlDir = Utils.getSqlSnippetDir()
            namesOnDisk = []
            if os.path.isdir(sqlDir):
                for file in os.listdir(sqlDir):
                    if file.endswith(".sql"):
                        namesOnDisk.append(file[:-4])
            config = Utils.loadConfig()
            savedOrder = config.get('sqlSnippetOrder') or []
            ordered = []
            seen = set()
            for name in savedOrder:
                if name in namesOnDisk and name not in seen:
                    ordered.append(name)
                    seen.add(name)
            for name in sorted(namesOnDisk, key=lambda s: s.lower()):
                if name not in seen:
                    ordered.append(name)
            self.listSnippets.clear()
            for name in ordered:
                self.listSnippets.addItem(name)
        except Exception as e:
            Logic.logException("loadSnippets failed", e)

    def currentSnippetOrder(self):
        """Return snippet names in current list order."""
        if self.listSnippets is None:
            return []
        return [
            self.listSnippets.item(i).text()
            for i in range(self.listSnippets.count())
            if self.listSnippets.item(i)
        ]

    def saveSnippetOrder(self):
        """Persist listSnippets order to user.config for next open."""
        try:
            config = Utils.loadConfig()
            config['sqlSnippetOrder'] = self.currentSnippetOrder()

            with open(Utils.getConfigPath(), 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"saveSnippetOrder: {config['sqlSnippetOrder']}",
                )
        except Exception as e:
            Logic.logException("saveSnippetOrder failed", e)

    def onSnippetsReordered(self, *args):
        """Drag-drop finished — save order after Qt finishes the move."""
        # Defer so InternalMove has committed the new row order
        QTimer.singleShot(0, self.saveSnippetOrder)

    def showSnippetContextMenu(self, pos):
        """Right-click: Move Up / Move Down for SQL snippet order."""
        if self.listSnippets is None:
            return
        item = self.listSnippets.itemAt(pos)

        if item is None: return
        row = self.listSnippets.row(item)
        self.listSnippets.setCurrentItem(item)
        menu = QMenu(self)
        actUp = menu.addAction("Move Up")
        actDown = menu.addAction("Move Down")
        actDelete = menu.addAction("Delete")
        actUp.setEnabled(row > 0)
        actDown.setEnabled(row < self.listSnippets.count() - 1)
        chosen = menu.exec(self.listSnippets.mapToGlobal(pos))

        if chosen == actUp and row > 0:
            taken = self.listSnippets.takeItem(row)
            self.listSnippets.insertItem(row - 1, taken)
            self.listSnippets.setCurrentRow(row - 1)
            self.saveSnippetOrder()
        elif chosen == actDown and row < self.listSnippets.count() - 1:
            taken = self.listSnippets.takeItem(row)
            self.listSnippets.insertItem(row + 1, taken)
            self.listSnippets.setCurrentRow(row + 1)
            self.saveSnippetOrder()
        elif chosen == actDelete:
            if self.sqlWorkbench is not None:
                self.sqlWorkbench.deleteSnippet()
            else:
                self.deleteSnippet()

    def saveSnippet(self):
        """Save current pteSQL content as .sql snippet."""
        if self.pteSQL is None:
            if Config.debug:
                Logic.logMessage("WARN", "pteSQL not found, skipping saveSnippet")
            return
        sqlText = self.pteSQL.toPlainText().strip()

        if not sqlText:
            QMessageBox.warning(self, "Save Snippet", "No SQL query to save.")

            if Config.debug:
                Logic.logMessage("DEBUG", "saveSnippet: No SQL text to save")
            return
        name, ok = QInputDialog.getText(self, "Save Snippet", "Snippet name:")

        if ok and name:
            sqlDir = Utils.getSqlSnippetDir()
            filePath = os.path.join(sqlDir, f"{name}.sql")

            with open(filePath, 'w', encoding='utf-8') as f:
                f.write(sqlText)
            self.loadSnippets() # Reload list to show new snippet immediately
            self.saveSnippetOrder()
            if Config.debug: Logic.logMessage("DEBUG", f"saveSnippet: Saved snippet {name} to {filePath} and reloaded list")

    def loadSnippet(self, index):
        """Load selected snippet into pteSQL on double-click."""
        if self.listSnippets is None or self.pteSQL is None:
            if Config.debug: Logic.logMessage("WARN", "listSnippets or pteSQL not found, skipping loadSnippet")
            return
        item = self.listSnippets.itemFromIndex(index)

        if item:
            name = item.text()
            sqlDir = Utils.getSqlSnippetDir()
            filePath = os.path.join(sqlDir, f"{name}.sql")

            if os.path.exists(filePath):
                with open(filePath, 'r', encoding='utf-8') as f:
                    sqlText = f.read()
                self.pteSQL.setPlainText(sqlText)

                if Config.debug: Logic.logMessage("DEBUG", f"loadSnippet: Loaded {name} into pteSQL")
            else:
                if Config.debug: Logic.logMessage("WARN", f"loadSnippet: Snippet file not found: {filePath}")

    def deleteSnippet(self):
        """Delete selected snippet file and remove from listSnippets."""
        if self.listSnippets is None:
            if Config.debug: Logic.logMessage("WARN", "listSnippets not found, skipping deleteSnippet")
            return
        selected = self.listSnippets.currentItem()

        if not selected:
            QMessageBox.warning(self, "Delete Snippet", "No snippet selected.")
            if Config.debug: Logic.logMessage("DEBUG", "deleteSnippet: No item selected")
            return
        name = selected.text()
        reply = QMessageBox.question(self, "Delete Snippet", f"Delete '{name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            sqlDir = Utils.getSqlSnippetDir()
            filePath = os.path.join(sqlDir, f"{name}.sql")

            if os.path.exists(filePath):
                os.remove(filePath)
                self.listSnippets.takeItem(self.listSnippets.row(selected))
                self.saveSnippetOrder()

                if Config.debug: Logic.logMessage("DEBUG", f"deleteSnippet: Deleted {name} from {filePath} and removed from list")
            else:
                if Config.debug: Logic.logMessage("WARN", f"deleteSnippet: File not found: {filePath}")

    def runCustomQuery(self):
        """Run custom SQL from pteSQL on a background thread; fill sqlTable on completion."""
        if not self.pteSQL or not self.sqlTable:
            if Config.debug: Logic.logMessage("WARN", "pteSQL or sqlTable not found, skipping runCustomQuery")
            return
        if getattr(self, 'sqlQueryRunning', False):
            QMessageBox.information(self, "Run Query", "A SQL query is already running.")
            return
        sqlText = self.pteSQL.toPlainText().strip()

        if not sqlText:
            QMessageBox.warning(self, "Run Query", "No SQL query to run.")
            if Config.debug: Logic.logMessage("DEBUG", "runCustomQuery: No SQL text to run")
            return
        db = self.cbDatabase.currentText()
        dsn = db.split('-')[1].lower() if '-' in db else db.lower() # e.g., 'USBR-LCHDB' -> 'lchdb'
        if Config.debug: Logic.logMessage("DEBUG", f"runCustomQuery: Using DSN {dsn} for query (background)")
        self.sqlQueryRunning = True
        if self.btnRunQuery: self.btnRunQuery.setEnabled(False)
        signals = sqlQuerySignals()

        # Keep reference so signals aren't GC'd before emit
        self.sqlQuerySignals = signals
        signals.finished.connect(self.onSqlQueryFinished)
        signals.failed.connect(self.onSqlQueryFailed)
        worker = sqlQueryWorker(dsn, sqlText, signals)
        QThreadPool.globalInstance().start(worker)

    def onSqlQueryFinished(self, results):
        self.sqlQueryRunning = False
        if self.btnRunQuery: self.btnRunQuery.setEnabled(True)

        if not results:
            QMessageBox.information(self, "Query Result", "No results returned.")

            if Config.debug:
                Logic.logMessage("DEBUG", "runCustomQuery: No results from query")
            return
        try:
            columns = list(results[0].keys()) if results else []
            self.sqlTable.setColumnCount(len(columns))
            self.sqlTable.setHorizontalHeaderLabels(columns)
            self.sqlTable.setRowCount(len(results))
            self.sqlTable.horizontalHeader().setStretchLastSection(False)

            for row, res in enumerate(results):
                for col, key in enumerate(columns):
                    item = QTableWidgetItem(str(res.get(key, '')))
                    self.sqlTable.setItem(row, col, item)
            self.sqlTable.resizeColumnsToContents()

            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"runCustomQuery: Populated sqlTable with {len(results)} rows, {len(columns)} columns"
                )
        except Exception as e:
            Logic.logException("runCustomQuery: Failed to populate table", e)
            QMessageBox.warning(self, "Query Error", f"Failed to display results: {e}")

    def onSqlQueryFailed(self, message, isAuthError):
        self.sqlQueryRunning = False

        if self.btnRunQuery:
            self.btnRunQuery.setEnabled(True)
        if isAuthError:
            upper = (message or '').upper()
            title = (
                "Oracle Password Expired"
                if ('EXPIRED' in upper or 'ORA-28001' in upper)
                else "Oracle Login Failed"
            )
            QMessageBox.warning(self, title, message)
        else:
            QMessageBox.warning(self, "Query Error", f"Failed to execute query: {message}")

    def storeQueryData(self, responses, queryType):
        """Store API responses and query type after successful query."""
        try:
            def _normKey(k):
                # Same normalization as resolveSeriesResponse candidates
                key = str(k).replace('\n', ' ').replace('\u00a0', ' ').strip()
                return ' '.join(key.split())
            normalizedResponses = {}

            for k, v in responses.items():
                key = _normKey(k)
                if not key:
                    continue
                if isinstance(v, dict) and 'label' in v:
                    v['label'] = _normKey(v['label'])
                normalizedResponses[key] = v
            self.seriesResponses = normalizedResponses
            self.currentQueryType = queryType
            
            if Config.debug: Logic.logMessage("DEBUG", f"Stored query data: {len(normalizedResponses)} series, type {queryType}, keys={[repr(k) for k in normalizedResponses.keys()]}")
        except Exception as e:
            Logic.logException("storeQueryData failed", e)

    def btnPublicQueryPressed(self):
        if self.winQuery:
            self.winQuery.queryType = 'public'
            self.winQuery.show()

            if Config.debug: Logic.logMessage("DEBUG", "btnPublicQueryPressed: Opened uiQuery as public")                  

    def btnInternalQueryPressed(self):
        if self.winQuery:
            self.winQuery.queryType = 'internal'
            self.winQuery.show()

            if Config.debug: Logic.logMessage("DEBUG", "btnInternalQueryPressed: Opened uiQuery as internal")           

    def showDataDictionary(self):
        if self.winDataDictionary:
            self.winDataDictionary.show()
            if Config.debug: Logic.logMessage("DEBUG", "showDataDictionary: Opened data dictionary")        

    def btnExportCSVPressed(self):
        # Export the table on the active tab (Data Query vs SQL Query Builder)
        exportTable = self.mainTable
        useSqlFormat = False

        # QTabWidget is falsy when it has 0 tabs — always use `is not None`
        currentWidget = self.tabWidget.currentWidget() if self.tabWidget is not None else None
        sqlTab = self.tabSQL or self.findChild(QWidget, 'tabSQL')

        # Detect SQL tab by objectName / index — identity (is) is unreliable across findChild wrappers
        isSqlTab = False

        if currentWidget is not None and self.tabWidget is not None:
            sqlIndex = self.tabWidget.indexOf(sqlTab) if sqlTab is not None else -1
            isSqlTab = (
                currentWidget.objectName() == 'tabSQL'
                or (sqlIndex != -1 and self.tabWidget.currentIndex() == sqlIndex)
                or (sqlTab is not None and currentWidget == sqlTab)
            )
        if self.detachedWindows.get("sql") is not None:
            isSqlTab = True

        if isSqlTab:
            wb = getattr(self, "sqlWorkbench", None)
            if wb is not None:
                exportTable = wb.currentResultTable()
            elif self.sqlTable is not None:
                exportTable = self.sqlTable
            useSqlFormat = True

        if Config.debug:
            tabName = currentWidget.objectName() if currentWidget else None
            Logic.logMessage(
                "DEBUG",
                f"btnExportCSVPressed: activeTab={tabName}, isSqlTab={isSqlTab}, "
                f"rows={exportTable.rowCount() if exportTable else 0}"
            )

        if exportTable is None or exportTable.rowCount() == 0:
            QMessageBox.warning(self, "Export CSV", "No data to export.")
            if Config.debug: Logic.logMessage("DEBUG", "btnExportCSVPressed: No data to export")
            return
        config = Utils.loadConfig()
        lastExportPath = config.get('lastExportPath', os.path.expanduser("~/Documents"))
        lastExportPath = os.path.normpath(os.path.abspath(lastExportPath)) if lastExportPath else os.path.expanduser("~/Documents")
        timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
        defaultName = f"{timestamp} Export.csv"
        fileName, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV", os.path.join(lastExportPath, defaultName), "CSV Files (*.csv)"
        )

        if not fileName:
            if Config.debug: Logic.logMessage("DEBUG", "btnExportCSVPressed: Export canceled by user")
            return
        try:
            with open(fileName, 'w', newline='', encoding='utf-8-sig') as csvFile:
                writer = csv.writer(csvFile)
                headers = []

                for c in range(exportTable.columnCount()):
                    headerItem = exportTable.horizontalHeaderItem(c)
                    headers.append(headerItem.text() if headerItem else f"Column {c}")

                # Data Query uses vertical header timestamps; SQL results use table columns only
                if useSqlFormat or not exportTable.verticalHeaderItem(0):
                    writer.writerow(headers)

                    for row in range(exportTable.rowCount()):
                        rowData = []

                        for col in range(exportTable.columnCount()):
                            item = exportTable.item(row, col)
                            rowData.append(item.text() if item else '')
                        writer.writerow(rowData)
                else:
                    writer.writerow(['Timestamp'] + headers)

                    for row in range(exportTable.rowCount()):
                        tsItem = exportTable.verticalHeaderItem(row)
                        rowData = [tsItem.text() if tsItem else '']

                        for col in range(exportTable.columnCount()):
                            item = exportTable.item(row, col)
                            rowData.append(item.text() if item else '')
                        writer.writerow(rowData)
            config['lastExportPath'] = os.path.dirname(fileName)

            with open(Utils.getConfigPath(), 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)
            if Config.debug: Logic.logMessage("DEBUG", f"btnExportCSVPressed: Exported table to {fileName}")
            QMessageBox.information(self, "Export Complete", f"CSV exported successfully to:\n{fileName}")
        except Exception as e:
            Logic.logMessage("ERROR", f"btnExportCSVPressed: Failed to export CSV: {e}")                
            QMessageBox.warning(self, "Export Error", f"Failed to export CSV: {e}")

    def btnOptionsPressed(self):
        try:
            if self.winOptions:
                self.winOptions.exec()
                if Config.debug: Logic.logMessage("DEBUG", "btnOptionsPressed: Opened options dialog")
        finally:
            Utils.resetStyledButtonHover(self.btnOptions)

    def btnInfoPressed(self):
        try:
            if self.winAbout:
                about = self.winAbout
                if about.isVisible():
                    about.raise_()
                    about.activateWindow()
                else:
                    about.show()
                if Config.debug: Logic.logMessage("DEBUG", "btnInfoPressed: Opened about dialog")
        finally:
            Utils.resetStyledButtonHover(self.btnInfo)

    def _parseQueryDate(self, value):
        """Normalize lastStartDate / lastEndDate to datetime, or None."""
        if value is None: return None
        if isinstance(value, datetime): return value.replace(second=0, microsecond=0)
        s = str(value).strip()        
        if not s: return None

        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%m/%d/%y %H:%M:00', '%m/%d/%y %H:%M'):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace('T', ' ').split('.')[0])
        except Exception:
            return None

    def refreshEndDateForQuery(self, lastEndDate, now=None):
        """
        On Refresh: pull end time up to *now* so new data is included.

        Exception — historical / older ranges: if the stored end is more than
        2 hours before now, leave it alone (do not jump a past period to "now").
        """
        now = now or datetime.now().replace(second=0, microsecond=0)
        endDt = self._parseQueryDate(lastEndDate)
        if endDt is None: return now

        # Older range (end more than 2 hours ago) → keep original end
        if now - endDt > timedelta(hours=2): return endDt

        # Recent / live range → extend end to the moment Refresh was hit
        return now if endDt <= now else endDt

    def btnRefreshPressed(self):
        try:
            if self.lastQueryType and self.lastQueryItems:
                if not Upload.confirmDiscardPendingEdits(self, "refresh the query"):
                    if Config.debug: Logic.logMessage("DEBUG", "btnRefreshPressed: Canceled due to pending edits")
                    return
                # Retrieve last query-option states from globals, default to False if not set
                deltaChecked = getattr(Config, 'lastDeltaChecked', False)
                overlayChecked = getattr(Config, 'lastOverlayChecked', False)
                rawChecked = getattr(Config, 'lastRawDataChecked', False)
                qaqcChecked = getattr(Config, 'lastQaqcChecked', False)
                startDate = self.lastStartDate
                endDate = self.refreshEndDateForQuery(self.lastEndDate)

                # Remember bumped end so the next Refresh keeps extending live series
                self.lastEndDate = endDate

                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"btnRefreshPressed: Refreshing start={startDate}, end={endDate}, "
                        f"deltaChecked={deltaChecked}, overlayChecked={overlayChecked}, "
                        f"rawData={rawChecked}, qaqc={qaqcChecked}",
                    )
                Query.executeQuery(
                    self, self.lastQueryItems, startDate, endDate,
                    self.lastQueryType == 'internal', self.winDataDictionary.mainTable,
                    deltaChecked=deltaChecked, overlayChecked=overlayChecked,
                    rawDataChecked=rawChecked, qaqcChecked=qaqcChecked,
                )

                if Config.debug: Logic.logMessage("DEBUG", "btnRefreshPressed: Refreshed query with last parameters")
            else:
                if Config.debug: Logic.logMessage("DEBUG", "btnRefreshPressed: No previous query to refresh")
        except Exception as e:
            Logic.logException("btnRefreshPressed failed", e)
            QMessageBox.warning(self, "Refresh Error", f"Failed to refresh query:\n{e}")
        finally:
            Utils.resetStyledButtonHover(self.btnRefresh)

    def btnUndoPressed(self):
        try:
            if self.mainTable.rowCount() == 0:
                if Config.debug: Logic.logMessage("DEBUG", "btnUndoPressed: No data to sort")
                QMessageBox.information(self, "Undo", "No data to sort.")
                return
            Query.timestampSortTable(self.mainTable, self.winDataDictionary.mainTable)

            if Config.debug: Logic.logMessage("DEBUG", "btnUndoPressed: Called timestampSortTable")
        except Exception as e:
            Logic.logException("btnUndoPressed failed", e)
        finally:
            Utils.resetStyledButtonHover(self.btnUndo)

    def onMainTableItemChanged(self, item):
        """Flag user edits for upload (magenta); restore baseline when text matches original."""
        Upload.onItemChanged(self, item)

    def onMainHeaderClicked(self, col):
        """Single-click column header: highlight the whole column (no sort)."""
        Upload.selectEntireColumn(self, col)

    def onMainHeaderDoubleClicked(self, col):
        """Double-click column header: sort by that column."""
        Query.customSortTable(self.mainTable, col, self.winDataDictionary.mainTable)

    def btnUploadPressed(self):
        """Upload pending user edits: HDB via MODIFY_R_BASE; Aquarius stubbed for now."""
        try:
            Upload.runUpload(self)
        finally:
            Utils.resetStyledButtonHover(self.btnUpload)

    def showHeaderContextMenu(self, pos):
        """Show context menu for header right-click to display full query info using uiDetails."""
        try:
            header = self.mainTable.horizontalHeader()
            col = header.logicalIndexAt(pos)

            if col < 0:
                return
            # columnMetadata may be shorter than table (edge cases) — still allow Graph
            meta = self.columnMetadata[col] if col < len(self.columnMetadata) else None
            if meta is not None: meta['col'] = col  # Add col for stats computation
            menu = QMenu(self)

            if meta is not None:
                if meta.get('type') == 'normal':
                    action = menu.addAction("Show Query Info")
                    action.triggered.connect(lambda: self.showHeaderDetails("headerNormal", meta))
                elif meta.get('type') == 'delta':
                    action = menu.addAction("Show details")
                    action.triggered.connect(lambda: self.showHeaderDetails("headerDelta", meta))
                elif meta.get('type') == 'overlay':
                    action = menu.addAction("Show details")
                    action.triggered.connect(lambda: self.showHeaderDetails("headerOverlay", meta))
            graphAction = menu.addAction("Graph")

            # Multi-column selection: graph all selected columns (include the
            # right-clicked header). Old code passed only [c], so Graph on the
            # first/last selected header ignored the rest of the highlight.
            graphAction.triggered.connect(
                lambda checked=False, c=col: self.graphTableSelection(
                    columns=self._columnsForHeaderGraph(c)
                )
            )

            if menu.actions(): menu.exec(header.mapToGlobal(pos))
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    "showHeaderContextMenu: Displayed menu for column {}, type {}".format(
                        col, (meta or {}).get('type')
                    ),
                )
        except Exception as e:
            Logic.logException("showHeaderContextMenu failed", e)

    def _columnsForHeaderGraph(self, clickedCol):
        """
        Columns to graph from a header right-click Graph action.

        Uses the current table multi-selection and always includes the clicked
        header column. Empty selection → just the clicked column.
        """
        cols = set()
        table = self.mainTable

        if table is not None:
            try:
                for idx in table.selectedIndexes(): cols.add(idx.column())
                for r in table.selectedRanges():
                    for c in range(r.leftColumn(), r.rightColumn() + 1):
                        cols.add(c)
            except Exception as e:
                if Config.debug: Logic.logMessage("DEBUG", f"_columnsForHeaderGraph selection: {e}")
        if clickedCol is not None and clickedCol >= 0: cols.add(clickedCol)
        return sorted(cols)

    def showHeaderDetails(self, queryType, meta):
        """Open uiDetails for header metadata."""
        try:
            seriesLabel = self.mainTable.horizontalHeaderItem(meta['col']).text() if self.mainTable.horizontalHeaderItem(meta['col']) else ""
            detailsWin = uiDetails(parent=self)
            detailsWin.populateDetails(queryType, seriesLabel, "", meta)
            detailsWin.show()
            
            if Config.debug: Logic.logMessage("DEBUG", f"showHeaderDetails: Opened details for {seriesLabel}")
        except Exception as e:
            Logic.logException("showHeaderDetails failed", e)
            QMessageBox.warning(self, "Details Error", f"Failed to show details:\n{e}")

    def showCellContextMenu(self, pos):
        """Show context menu for cell right-click: Metadata details (internal only, non-overlay) + overlay if applicable."""
        try:
            index = self.mainTable.indexAt(pos)
            if not index.isValid(): return        
            row = index.row()
            col = index.column()
            
            # Get timestamp and series (from headers)
            timestampStr = self.mainTable.verticalHeaderItem(row).text() if self.mainTable.verticalHeaderItem(row) else ""
            seriesLabel = self.mainTable.horizontalHeaderItem(col).text() if self.mainTable.horizontalHeaderItem(col) else ""
            
            if not timestampStr or not seriesLabel:
                Logic.logMessage("WARN", "Invalid cell: No timestamp or series label")
                return
            
            # Get lookupId and db from columnMetadata
            lookupId = self.columnMetadata[col].get('lookupId') if col < len(self.columnMetadata) else None
            db = self.columnMetadata[col].get('dbs') if col < len(self.columnMetadata) else None
            
            # Normalize db to string if it's a list (for single-db normal columns)
            if isinstance(db, list) and len(db) > 0: db = db[0]            
            if Config.debug: Logic.logMessage("DEBUG", f"showCellContextMenu: columnMetadata={repr(self.columnMetadata)}, col={col}, lookupId={lookupId!r}, db={db!r}")
            
            # Resolve seriesResponses with multiple candidate keys (header label != storage key for USGS).
            response, normalizedLabel = self.resolveSeriesResponse(col, seriesLabel, db, lookupId)
            if Config.debug: Logic.logMessage("DEBUG", f"showCellContextMenu: seriesLabel={seriesLabel!r}, normalizedLabel={normalizedLabel!r}, response type={type(response).__name__ if response else 'None'}, response={repr(response) if response else 'None'}, currentQueryType={self.currentQueryType}, seriesResponses keys={[repr(k) for k in self.seriesResponses.keys()]}")              
            menu = QMenu(self)
            
            # Add metadata details:
            #   - Internal: Aquarius / USBR / USGS (normal columns)
            #   - Public: USGS only (public OGC metadata is already pulled with the query)
            colType = self.columnMetadata[col].get('type') if col < len(self.columnMetadata) else None
            isInternal = self.currentQueryType == 'internal'
            isPublic = self.currentQueryType == 'public'
            allowUsgsPublic = isPublic and db == 'USGS-NWIS'

            if colType == 'normal' and (isInternal or allowUsgsPublic):
                # Extract interval from queryInfos (e.g., '20179|HOUR|USBR-LCHDB' -> 'HOUR')
                queryInfo = self.columnMetadata[col].get('queryInfos', ['|'])[0]
                interval = queryInfo.split('|')[1] if '|' in queryInfo else 'HOUR' # Default to HOUR if missing
                
                if isInternal and db == 'AQUARIUS':
                    # Always offer details for Aquarius (even if response lookup missed);
                    # populateAquarius handles empty dict gracefully.
                    aqResponse = response if isinstance(response, dict) else {}
                    detailsAction = menu.addAction("Show details")
                    detailsAction.triggered.connect(
                        lambda r=row, c=col, ts=timestampStr, sl=seriesLabel, resp=aqResponse, iv=interval:
                        self.showMetadataDetails(r, c, ts, sl, resp, 'AQUARIUS', iv)
                    )

                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            f"showCellContextMenu: Added 'Show details' for AQUARIUS "
                            f"(response keys={list(aqResponse.keys())[:8] if aqResponse else []})",
                        )
                elif isInternal and db and str(db).startswith('USBR'):
                    # List = full R_* meta; dict kind=mrid = values-only (no meta), like USGS legacy
                    usbrResponse = response
                    if isinstance(response, dict) and (response.get('kind') or '').lower() == 'mrid': usbrResponse = response
                    elif not isinstance(response, list): usbrResponse = []
                    detailsAction = menu.addAction("Show details")
                    detailsAction.triggered.connect(
                        lambda r=row, c=col, ts=timestampStr, sl=seriesLabel, resp=usbrResponse, iv=interval:
                        self.showMetadataDetails(r, c, ts, sl, resp, 'USBR', iv)
                    )

                    if Config.debug:
                        kind = (
                            response.get('kind')
                            if isinstance(response, dict)
                            else f'list[{len(response)}]' if isinstance(response, list) else type(response).__name__
                        )
                        Logic.logMessage(
                            "DEBUG",
                            f"showCellContextMenu: Added 'Show details' for USBR ({kind})",
                        )
                elif db == 'USGS-NWIS':
                    # Internal or public USGS — OGC full meta when available; legacy blanks.
                    # Do NOT invent kind=legacy when lookup misses (that lied after tsid-only dict keys).
                    if isinstance(response, dict):
                        usgsResponse = response
                    else:
                        usgsResponse = {"kind": "missing", "seriesMeta": {}, "points": []}
                    detailsAction = menu.addAction("Show details")
                    detailsAction.triggered.connect(lambda r=row, c=col, ts=timestampStr, sl=seriesLabel, resp=usgsResponse, iv=interval: self.showMetadataDetails(r, c, ts, sl, resp, 'USGS', iv))
                    
                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            f"showCellContextMenu: Added 'Show details' for USGS "
                            f"(queryType={self.currentQueryType}, kind={usgsResponse.get('kind')})",
                        )            
            # Add single action for overlay columns
            isOverlay = colType == 'overlay'
            
            if isOverlay:
                # Get types from columnMetadata (e.g., ['overlay', 'USBR', 'AQUARIUS'])
                meta = self.columnMetadata[col]
                types = ['overlay'] + meta.get('dbs', []) # Overlay first, then DBs in order                
                if Config.debug: Logic.logMessage("DEBUG", f"showCellContextMenu: Overlay types for col {col}: {types}")
                
                # Add single action
                detailsAction = menu.addAction("Show details")
                detailsAction.triggered.connect(lambda: self.showMetadataDetails(row, col, timestampStr, seriesLabel, response, 'overlay', multiTypes=types))

            # Graph selection (highlighted rows/cols); always available when table has data
            if menu.actions(): menu.addSeparator()
            graphAction = menu.addAction("Graph")
            graphAction.triggered.connect(lambda: self.graphTableSelection())

            # Clipboard: always Copy; Paste only on internal (public is read-only)
            menu.addSeparator()
            copyAction = menu.addAction("Copy")
            copyAction.setShortcut("Ctrl+C")
            copyAction.triggered.connect(lambda: Upload.copySelectionToClipboard(self))

            if isInternal:
                pasteAction = menu.addAction("Paste")
                pasteAction.setShortcut("Ctrl+V")
                pasteAction.triggered.connect(lambda: Upload.pasteClipboardToSelection(self))
            if menu.actions():
                # If the right-clicked cell is outside the current multi-selection,
                # select only that cell so Copy/Paste/Graph target the intended range.
                sel = self.mainTable.selectionModel()

                if sel is not None and not sel.isSelected(index):
                    self.mainTable.clearSelection()
                    self.mainTable.setCurrentIndex(index)
                    sel.select(index, sel.SelectionFlag.ClearAndSelect)
                menu.exec(self.mainTable.viewport().mapToGlobal(pos))                
                if Config.debug: Logic.logMessage("DEBUG", f"showCellContextMenu: Displayed menu for cell ({row}, {col}) with {len(menu.actions())} actions")
            else:
                if Config.debug: Logic.logMessage("DEBUG", f"showCellContextMenu: No actions for cell ({row}, {col})")
        except Exception as e:
            Logic.logException("showCellContextMenu failed", e)

    def resolveSeriesResponse(self, col, seriesLabel, db, lookupId):
        """
        Find the stored series response for a column.

        seriesResponses is keyed by query DataID (and Aquarius label variants).
        Header text alone is not reliable for USGS (headers are site-param + interval).
        """
        candidates = []

        def addCandidate(val):
            if val is None: return
            if isinstance(val, (list, tuple)):
                for v in val: addCandidate(v)
                return
            key = str(val).replace('\n', ' ').replace('\u00a0', ' ').strip()
            key = ' '.join(key.split())
            if key and key not in candidates: candidates.append(key)
        addCandidate(lookupId)
        meta = self.columnMetadata[col] if col < len(self.columnMetadata) else {}
        addCandidate(meta.get('dataIds'))

        for qi in (meta.get('queryInfos') or []):
            if isinstance(qi, list): qi = qi[0] if qi else ''
            qiStr = str(qi) if qi is not None else ''
            if '|' in qiStr: addCandidate(qiStr.split('|')[0])
            else: addCandidate(qiStr)
        if db == 'AQUARIUS':
            addCandidate(seriesLabel.replace('\n', ' ').strip() if seriesLabel else None)
        elif db == 'USGS-NWIS':
            # Prefer DataID candidates already added; header last line is often just interval
            if seriesLabel:
                parts = [p.strip() for p in seriesLabel.split('\n') if p.strip()]

                for p in parts:
                    addCandidate(p)

            # Also try bare time_series_id (dictionary / lookupId may be tsid only)
            for key in list(candidates):
                try:
                    tsid = Query.dictionaryLookupKey(key, 'USGS-NWIS')
                    addCandidate(tsid)
                except Exception:
                    pass
        else:
            # USBR: second header line is usually SDID or SDID-MRID
            if seriesLabel and '\n' in seriesLabel: addCandidate(seriesLabel.split('\n')[-1].strip())
            elif seriesLabel: addCandidate(seriesLabel.strip())
        for key in candidates:
            if key in self.seriesResponses: return self.seriesResponses[key], key

        # Case-insensitive fallback (hex time_series_id case mismatches)
        lowerMap = {str(k).lower(): (k, v) for k, v in self.seriesResponses.items()}
        for key in candidates:
            hit = lowerMap.get(key.lower())
            if hit: return hit[1], hit[0]

        # USGS: match any stored key whose 2nd segment (or whole key) is this tsid
        if db == 'USGS-NWIS' and self.seriesResponses:
            for key in candidates:
                kl = key.lower()

                for sk, sv in self.seriesResponses.items():
                    sks = str(sk)
                    if sks.lower() == kl: return sv, sk

                    # Site-tsid[-param] contains this tsid as 2nd segment
                    parts = [p for p in sks.split('-') if p]
                    if len(parts) >= 2 and parts[1].lower() == kl: return sv, sk
                    if len(parts) == 1 and parts[0].lower() == kl: return sv, sk
        return None, (candidates[0] if candidates else None)

    def showMetadataDetails(self, row, col, timestampStr, seriesLabel, response, dbType, interval=None, multiTypes=None):
        """Open uiDetails for metadata (Aquarius or USBR)."""
        try:
            # For multiTypes, gather responses and intervals for each type
            responsesList = None
            intervalsList = None

            if multiTypes:
                meta = self.columnMetadata[col]
                lookupIds = meta.get('lookupId', [])
                if not isinstance(lookupIds, list): lookupIds = [lookupIds] if lookupIds is not None else []
                dataIds = meta.get('dataIds', [])
                if not isinstance(dataIds, list): dataIds = [dataIds] if dataIds is not None else []
                dbs = meta.get('dbs', [])
                if not isinstance(dbs, list): dbs = [dbs] if dbs is not None else []
                queryInfos = meta.get('queryInfos', [])
                if not isinstance(queryInfos, list): queryInfos = [queryInfos] if queryInfos is not None else []
                responsesList = []
                intervalsList = []
                
                for i, t in enumerate(multiTypes):
                    if t == 'overlay':
                        # Use cell data for overlay tab
                        item = self.mainTable.item(row, col)
                        cellData = item.data(Qt.ItemDataRole.UserRole) if item else {}
                        responsesList.append(cellData)
                        intervalsList.append(None) # No interval for overlay
                    else:
                        # DB tab index in parallel lists (overlay is multiTypes[0])
                        dbIdx = i - 1
                        lid = lookupIds[dbIdx] if dbIdx < len(lookupIds) else None
                        dataId = dataIds[dbIdx] if dbIdx < len(dataIds) else None
                        dbName = dbs[dbIdx] if dbIdx < len(dbs) else t
                        if isinstance(dbName, list): dbName = dbName[0] if dbName else t

                        # Prefer this tab's own DataID/lookupId so primary/secondary don't swap
                        dbResponse = None
                        matchedKey = None

                        for prefer in (lid, dataId):
                            if prefer is None: continue
                            preferKey = str(prefer).replace('\n', ' ').strip()

                            if preferKey in self.seriesResponses:
                                dbResponse = self.seriesResponses[preferKey]
                                matchedKey = preferKey
                                break
                        if dbResponse is None:
                            dbResponse, matchedKey = self.resolveSeriesResponse(
                                col, seriesLabel, dbName, lid if lid is not None else dataId
                            )
                        if dbResponse is None: dbResponse = {}

                        # USGS-NWIS: ensure details never receive a non-dict (overlay crash guard)
                        if isinstance(t, str) and t.upper().startswith('USGS') and not isinstance(dbResponse, dict):
                            dbResponse = {"kind": "missing", "seriesMeta": {}, "points": []}
                        responsesList.append(dbResponse)

                        # Extract interval from queryInfos
                        qInfo = queryInfos[dbIdx] if dbIdx < len(queryInfos) else '|'
                        if isinstance(qInfo, list): qInfo = qInfo[0] if qInfo else '|'
                        dbInterval = str(qInfo).split('|')[1] if '|' in str(qInfo) else 'HOUR'
                        intervalsList.append(dbInterval)

                        if Config.debug and not dbResponse:
                            Logic.logMessage(
                                "DEBUG",
                                f"showMetadataDetails: No seriesResponse for type {t} idx={dbIdx} "
                                f"lid={lid!r} dataId={dataId!r} matchedKey={matchedKey!r}"
                            )                
                if Config.debug: Logic.logMessage("DEBUG", f"showMetadataDetails: Gathered {len(responsesList)} responses and intervals for multiTypes {multiTypes}")            
            detailsWin = uiDetails(parent=self)
            detailsWin.populateDetails(dbType, seriesLabel, timestampStr, response, interval, multiTypes=multiTypes, responsesList=responsesList, intervalsList=intervalsList)
            detailsWin.show()            
            if Config.debug: Logic.logMessage("DEBUG", f"showMetadataDetails: Opened details for {timestampStr} - {seriesLabel} ({dbType}), multiTypes={multiTypes}")
        except Exception as e:
            Logic.logException("showMetadataDetails failed", e)
            QMessageBox.warning(self, "Details Error", f"Failed to show details:\n{e}")

    def onTabCloseRequested(self, index):
        # removeTab hides the page but keeps the widget so we can re-add log/SQL/query/graph tabs
        if self.tabWidget is None: return
        widget = self.tabWidget.widget(index)
        self.tabWidget.removeTab(index)

        if Config.debug:
            name = widget.objectName() if widget is not None else '?'
            Logic.logMessage("DEBUG", f"onTabCloseRequested: Closed tab at index {index} ({name})")

    def tabKeyForWidget(self, widget):
        """Return 'graph' / 'log' / 'sql' for detachable tabs, else None."""
        if widget is None: return None
        if self.tabGraph is not None and widget is self.tabGraph: return 'graph'
        if self.tabLog is not None and widget is self.tabLog: return 'log'
        if self.tabSQL is not None and widget is self.tabSQL: return 'sql'

        # objectName fallback (reparent edge cases)
        name = widget.objectName() if hasattr(widget, 'objectName') else ''
        if name == 'tabGraph': return 'graph'
        if name == 'tabLog': return 'log'
        if name == 'tabSQL': return 'sql'
        return None

    def graphInsertIndex(self):
        """Graph sits immediately to the right of Data Query when present."""
        if self.tabWidget is None: return 0
        dataIdx = self.tabWidget.indexOf(self.tabMain) if self.tabMain is not None else -1
        return dataIdx + 1 if dataIdx != -1 else 0

    def sqlInsertIndex(self):
        """
        SQL after Data Query and Graph (normal order:
        Data Query | Graph | SQL | Log).
        """
        if self.tabWidget is None: return 0
        idx = self.graphInsertIndex()

        # If Graph is already in the main tab bar, place SQL after it
        if self.tabGraph is not None:
            gIdx = self.tabWidget.indexOf(self.tabGraph)
            if gIdx != -1: idx = gIdx + 1
        return idx

    def ensureGraphPanel(self):
        """Create GraphPanel once; reuse across show/hide/detach."""
        if self.tabGraph is None:
            self.tabGraph = GraphPanel(None)
            self.tabGraph.setObjectName('tabGraph')
        return self.tabGraph

    def showGraphInMainTabs(self, select=True):
        """Insert Graph tab at normal position if it is not detached and not already open."""
        if self.tabWidget is None: return -1
        panel = self.ensureGraphPanel()

        if self.detachedWindows.get('graph') is not None:
            # Content lives in floating window — bring that forward instead
            win = self.detachedWindows['graph']
            win.show()
            win.raise_()
            win.activateWindow()
            return -1
        idx = self.tabWidget.indexOf(panel)        
        if idx == -1: idx = self.tabWidget.insertTab(self.graphInsertIndex(), panel, self.graphTitle)
        if select and idx >= 0: self.tabWidget.setCurrentIndex(idx)
        return idx

    def btnGraphPressed(self):
        """Graph toolbar button — plots current table selection (or full table)."""
        self.graphTableSelection()

    def graphTableSelection(self, columns=None, rows=None):
        """
        Graph from the Data Query table.

        - columns / rows: optional explicit subsets (header Graph passes a column).
        - Otherwise uses the highlighted selection; empty selection → full table.
        - Partial row selection graphs only that timeseries window.
        """
        if self.mainTable is None:
            QMessageBox.warning(self, "Graph", "Data table is not available.")
            return
        if self.mainTable.rowCount() <= 0 or self.mainTable.columnCount() <= 0:
            QMessageBox.information(
                self, "Graph",
                "No data to graph.\n\nRun a Data Query first, then press Graph.",
            )
            return

        # Need Data Query tab present so user can see context (create if missing)
        if (
            self.tabWidget is not None
            and self.tabMain is not None
            and self.tabWidget.indexOf(self.tabMain) == -1
        ):
            self.tabWidget.insertTab(0, self.tabMain, self.dataQueryTitle)
        panel = self.ensureGraphPanel()
        ok, message = panel.plotFromTable(
            self.mainTable,
            columns=columns,
            rows=rows,
            columnMetadata=getattr(self, 'columnMetadata', None),
        )

        if not ok:
            QMessageBox.warning(self, "Graph", message or "Could not build graph.")
            return

        if self.detachedWindows.get('graph') is not None:
            win = self.detachedWindows['graph']
            win.show()
            win.raise_()
            win.activateWindow()
            if message and Config.debug: Logic.logMessage("DEBUG", f"graphTableSelection (detached): {message}")
            return
        self.showGraphInMainTabs(select=True)
        if message and Config.debug: Logic.logMessage("DEBUG", f"graphTableSelection: {message}")

    def onMainTabBarContextMenu(self, pos):
        """Right-click Graph or Log tab → Detach tab."""
        if self.tabWidget is None: return
        tabBar = self.tabWidget.tabBar()
        idx = tabBar.tabAt(pos)
        if idx < 0: return
        widget = self.tabWidget.widget(idx)
        key = self.tabKeyForWidget(widget)
        if key is None: return
        menu = QMenu(self)
        detachAct = menu.addAction("Detach tab")
        chosen = menu.exec(tabBar.mapToGlobal(pos))
        if chosen == detachAct: self.detachTab(key)

    def detachTab(self, key):
        """
        Pop Graph, Log, or SQL into its own maximizable window (one window per tab).
        """
        if key not in ('graph', 'log', 'sql'): return
        if self.detachedWindows.get(key) is not None:
            win = self.detachedWindows[key]
            win.show()
            win.raise_()
            win.activateWindow()
            return
        if key == 'graph':
            content = self.ensureGraphPanel()
            title = self.graphTitle
        elif key == 'sql':
            content = self.tabSQL
            title = self.sqlTitle
            if content is None:
                QMessageBox.warning(self, "Detach", "SQL tab is not available.")
                return
        else:
            content = self.tabLog
            title = self.logTitle

            if content is None:
                QMessageBox.warning(self, "Detach", "Log tab is not available.")
                return

        # Remove from main tab bar if present (widget is kept alive)
        if self.tabWidget is not None:
            idx = self.tabWidget.indexOf(content)
            if idx != -1: self.tabWidget.removeTab(idx)
        win = detachedTabWindow(self, content, title, key)
        self.detachedWindows[key] = win
        win.show()
        if Config.debug: Logic.logMessage("DEBUG", f"detachTab: detached {key!r}")

    def attachDetachedTab(self, key):
        """
        Return a detached Graph/Log tab to the main window at normal tab order.
        """
        win = self.detachedWindows.pop(key, None)
        if win is None: return

        # Block floating window closeEvent from re-entering attach
        win._attaching = True

        if key == 'graph':
            content = self.tabGraph or win.contentWidget
            title = self.graphTitle
        elif key == 'sql':
            content = self.tabSQL or win.contentWidget
            title = self.sqlTitle
        else:
            content = self.tabLog or win.contentWidget
            title = self.logTitle

        # Pull content out of the floating host without destroying it
        if win.hostTabs is not None and content is not None:
            wIdx = win.hostTabs.indexOf(content)
            if wIdx != -1: win.hostTabs.removeTab(wIdx)

        # Tear down floating shell (avoid recursive closeEvent)
        win.hide()
        win.deleteLater()
        if content is None or self.tabWidget is None: return

        if key == 'graph':
            self.tabGraph = content
            insertAt = self.graphInsertIndex()
            idx = self.tabWidget.insertTab(insertAt, content, title)
        elif key == 'sql':
            self.tabSQL = content
            idx = self.tabWidget.insertTab(self.sqlInsertIndex(), content, title)
        else:
            # Log always last
            idx = self.tabWidget.addTab(content, title)
        self.tabWidget.setCurrentIndex(idx)
        if key == 'log': self.populateLogViewer()
        if key == 'sql': self.refreshSqlTab()
        if Config.debug: Logic.logMessage("DEBUG", f"attachDetachedTab: attached {key!r} at index {idx}")

    def btnSQLPressed(self):
        """Toggle SQL Query Builder tab: show if hidden, hide if already open."""
        # Empty QTabWidget is falsy in PyQt6 — never use bare `if self.tabWidget`
        if self.tabSQL is None or self.tabWidget is None:
            QMessageBox.warning(self, "SQL Query Builder", "SQL tab is not available.")
            return
        if self.detachedWindows.get('sql') is not None:
            win = self.detachedWindows['sql']
            win.show()
            win.raise_()
            win.activateWindow()
            self.refreshSqlTab()
            return
        idx = self.tabWidget.indexOf(self.tabSQL)

        if idx == -1:
            insertIndex = self.sqlInsertIndex()
            self.tabWidget.insertTab(insertIndex, self.tabSQL, self.sqlTitle)
            self.refreshSqlTab()
            idx = self.tabWidget.indexOf(self.tabSQL)
            self.tabWidget.setCurrentIndex(idx)
            if Config.debug: Logic.logMessage("DEBUG", f"btnSQLPressed: added tabSQL at index {idx}")
        else:
            self.tabWidget.removeTab(idx)
            if Config.debug: Logic.logMessage("DEBUG", f"btnSQLPressed: removed tabSQL from index {idx}")

    def btnGoatPressed(self):
        """Play the emergency stress-relief sound."""
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtCore import QUrl
        except Exception as e:
            Logic.logMessage("WARN", f"Goat audio backend unavailable: {e}")
            return
        wavPath = Logic.resourcePath('ui/sounds/Goat.wav')

        if not os.path.isfile(wavPath):
            Logic.logMessage("WARN", f"Goat sound missing: {wavPath}")
            return
        try:
            if self._goatPlayer is None:
                self._goatAudio = QAudioOutput(self)
                self._goatAudio.setVolume(0.95)
                self._goatPlayer = QMediaPlayer(self)
                self._goatPlayer.setAudioOutput(self._goatAudio)
            self._goatPlayer.setSource(QUrl.fromLocalFile(wavPath))
            self._goatPlayer.setPosition(0)
            self._goatPlayer.play()
        except Exception as e:
            Logic.logException("btnGoatPressed failed", e)

    def btnViewLogPressed(self):
        """Toggle Log Viewer tab: show if hidden, hide if already open (like SQL)."""
        if self.tabLog is None or self.tabWidget is None:
            QMessageBox.warning(self, "Log Viewer", "Log tab is not available.")
            return

        # If Log is detached, focus that window and refresh contents (do not close)
        if self.detachedWindows.get('log') is not None:
            self.populateLogViewer()
            win = self.detachedWindows['log']
            win.show()
            win.raise_()
            win.activateWindow()
            return
        idx = self.tabWidget.indexOf(self.tabLog)

        if idx == -1:
            # Always open Log Viewer as the last tab (not next to the active tab)
            self.tabWidget.addTab(self.tabLog, self.logTitle)
            idx = self.tabWidget.indexOf(self.tabLog)
            self.tabWidget.setCurrentIndex(idx)
            self.populateLogViewer()
            if Config.debug: Logic.logMessage("DEBUG", f"btnViewLogPressed: added tabLog at end index {idx}")
        else:
            # Already open → close (toggle off), same as btnSQL
            self.tabWidget.removeTab(idx)
            if Config.debug: Logic.logMessage("DEBUG", f"btnViewLogPressed: removed tabLog from index {idx}")

    def logViewerLineHeight(self):
        """
        Block line height % — Press Start has near-zero internal leading so lines
        blur together; open that up. System font still gets a little air.
        """
        return 155.0 if Config.retroMode else 125.0

    def logViewerFormat(self, level):
        """QTextCharFormat for a log level (shared by full load and live append)."""
        level = (level or 'INFO').upper()
        levelColors = {
            'CRITICAL': QColor(220, 50, 47),
            'ERROR': QColor(220, 50, 47),
            'WARN': QColor(203, 120, 50),
            'WARNING': QColor(203, 120, 50),
            'INFO': QColor(38, 139, 210),
            'DEBUG': QColor(108, 113, 120),
        }

        if Config.retroMode:
            defaultColor = QColor(200, 200, 200)
        elif isinstance(Config.systemTextColor, QColor) and Config.systemTextColor.isValid():
            defaultColor = QColor(Config.systemTextColor)
        else:
            defaultColor = QColor(40, 40, 40)

        # Role 'log' is intentionally larger than UI (especially in retro)
        mono = Utils.makeFontForRole('log')
        fmt = QTextCharFormat()
        fmt.setForeground(levelColors.get(level, defaultColor))
        fmt.setFont(mono)

        if level in ('ERROR', 'CRITICAL'): fmt.setFontWeight(QFont.Weight.Bold)
        return fmt

    def insertLogLine(self, cursor, text, level):
        """Insert one log record with role font + extra line spacing."""
        blockFmt = QTextBlockFormat()

        # PyQt6 expects heightType as int, not the LineHeightTypes enum object
        blockFmt.setLineHeight(
            self.logViewerLineHeight(),
            int(QTextBlockFormat.LineHeightTypes.ProportionalHeight.value),
        )

        cursor.setBlockFormat(blockFmt)
        line = text if text.endswith('\n') else text + '\n'
        cursor.insertText(line, self.logViewerFormat(level))

    def appendLogEntry(self, level, text):
        """
        Live-append one formatted log line at the top of pteLog.
        No-op unless the Log tab is open in main or detached — avoids UI work when closed.
        """
        if self.pteLog is None or self.tabLog is None or self.tabWidget is None: return
        logOpenInMain = self.tabWidget.indexOf(self.tabLog) != -1
        logDetached = self.detachedWindows.get('log') is not None

        # Tab closed (removeTab) and not floating: skip. Open or detached: still update.
        if not logOpenInMain and not logDetached: return
        if not text: return

        # Stay put if user scrolled away from newest; otherwise pin to top
        scrollBar = self.pteLog.verticalScrollBar()
        wasAtTop = scrollBar is None or scrollBar.value() == 0

        # Drop placeholder when first real entry arrives (check first block only — cheap)
        doc = self.pteLog.document()
        if doc.blockCount() <= 2:
            first = doc.firstBlock().text()
            if first.startswith("(No log entries found"): self.pteLog.clear()
        cursor = self.pteLog.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.insertLogLine(cursor, text, level)

        if wasAtTop:
            self.pteLog.moveCursor(QTextCursor.MoveOperation.Start)
            self.pteLog.ensureCursorVisible()

    def populateLogViewer(self):
        """Load app.log + rotations into pteLog with level-based colors, newest on top."""
        if not self.pteLog: return
        entries = Logic.loadAllAppLogEntries(newestFirst=True)
        self.pteLog.clear()
        self.pteLog.setUndoRedoEnabled(False)

        # Role font on the widget itself (default char format for any plain inserts)
        logFont = Utils.makeFontForRole('log')
        self.pteLog.setFont(logFont)
        self.pteLog.document().setDefaultFont(logFont)
        cursor = self.pteLog.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        if not entries:
            self.insertLogLine(
                cursor,
                f"(No log entries found in {Utils.getLogDir()})",
                'INFO',
            )

            self.pteLog.setTextCursor(cursor)
            if Config.debug: Logic.logMessage("DEBUG", "populateLogViewer: no entries")
            return

        for entry in entries:
            level = (entry.get('level') or 'INFO').upper()
            text = entry.get('text') or ''
            self.insertLogLine(cursor, text, level)

        # Keep view at top (newest)
        self.pteLog.moveCursor(QTextCursor.MoveOperation.Start)
        self.pteLog.ensureCursorVisible()

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"populateLogViewer: loaded {len(entries)} entries from {Utils.getLogDir()}",
            )

    def showOverlayCellDetails(self, row, col):
        """Display details for overlay cell using uiDetails window."""
        item = self.mainTable.item(row, col)        
        if not item: return        
        data = item.data(Qt.ItemDataRole.UserRole)        
        if not data: return
        
        # Get timestamp and series for title
        timestampStr = self.mainTable.verticalHeaderItem(row).text() if self.mainTable.verticalHeaderItem(row) else ""
        seriesLabel = self.mainTable.horizontalHeaderItem(col).text() if self.mainTable.horizontalHeaderItem(col) else ""
        
        # Open uiDetails with overlay mode
        detailsWin = uiDetails(parent=self)
        detailsWin.populateDetails('overlay', seriesLabel, timestampStr, data)
        detailsWin.show()        
        if Config.debug: Logic.logMessage("DEBUG", f"showOverlayCellDetails: Opened details for cell ({row}, {col})")

    def refreshSqlTab(self):
        if self.sqlWorkbench is not None:
            self.sqlWorkbench.refresh()
            return
        config = Utils.loadConfig()
        sqlSplitter = self.findChild(QSplitter, 'sqlSplitter')
        mainSplitter = self.findChild(QSplitter, 'mainSplitter')
        if sqlSplitter and 'sqlHorizontalSizes' in config:
            pass
        if sqlSplitter and 'sqlVerticalSizes' in config:
            sqlSplitter.setSizes(config['sqlVerticalSizes'])
        if mainSplitter and 'sqlHorizontalSizes' in config:
            mainSplitter.setSizes(config['sqlHorizontalSizes'])
        if self.cbDatabase:
            Utils.loadDatabase(self.cbDatabase, 'sql')
            self.cbDatabase.setMinimumWidth(200)
            self.cbDatabase.adjustSize()
        if self.listSnippets is not None:
            self.loadSnippets()

if __name__ == '__main__':
    app = None

    try:
        # Windows taskbar: python.exe / pythonw.exe group under the Python
        # AppUserModelID, so the shell shows the Python icon even when
        # setWindowIcon is correct. Give this process its own ID *before*
        # QApplication so the taskbar uses DataDoctor's window icon instead.
        # Same path for .py, .pyw, and the VB launcher → python child.
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    'USBR.DataDoctor.1'
                )
            except Exception: pass
        app = QApplication(sys.argv)

        # Application name only — do NOT set OrganizationName. QStandardPaths
        # AppConfigLocation becomes ~/.config/<App> (or %LocalAppData%\<App>).
        # Adding an org (e.g. "USBR") would redirect to .../USBR/Data Doctor and
        # hide existing user.config + quickLooks (regression from taskbar work).
        app.setApplicationName("Data Doctor")

        # Color theme before any widgets (and before systemTextColor): Light/Dark
        # must look like the OS is in that mode, not a half-applied hint.
        try:
            Utils.applyColorTheme(Utils.loadConfig().get('colorTheme', 'system'))
        except Exception:
            pass

        # Taskbar / window icon (Windows + Linux desktop shells that honor it)
        appIcon = QIcon()

        # Windows: .ico next to app (and under ui/icons). Linux: DataDoctor.png.
        # About splash art (ui/DataDoctor.png large) is NOT used as the app icon.
        icoPath = Logic.resourcePath('ui/icons/DataDoctor.ico')
        iconCandidates = (
            icoPath,

            # Same folder as DataDoctor.pyw when packaged on Windows
            Logic.resourcePath('DataDoctor.ico'),
            Logic.resourcePath('ui/icons/DataDoctor.png'),
        )

        for iconPath in iconCandidates:
            if os.path.isfile(iconPath):
                appIcon = QIcon(iconPath)
                if not appIcon.isNull(): break
        if not appIcon.isNull(): app.setWindowIcon(appIcon)

        # Init logging early, then install hooks so uncaught errors are logged and non-fatal
        Logic.initLogging()
        Logic.installExceptionHooks(showDialog=True)

        if Config.debug:   
            Logic.logMessage("DEBUG", "Applied global app stylesheet with default button effects and tab close styles")

            try:
                sizes = [(s.width(), s.height()) for s in appIcon.availableSizes()] if not appIcon.isNull() else []
                Logic.logMessage(
                    "DEBUG",
                    f"App icon loaded null={appIcon.isNull()} sizes={sizes} ico={icoPath}",
                )
            except Exception:
                pass

        # Text color the rest of the app uses (tables, deltas). Must be after
        # applyColorTheme so Light/Dark is what we see, not the real OS scheme.
        Config.systemTextColor = app.palette().color(QPalette.ColorRole.Text)

        # Create instances
        winMain = uiMain()
        if not appIcon.isNull(): winMain.setWindowIcon(appIcon)
        winQuery = uiQuery(winMain)
        winDataDictionary = uiDataDictionary(winMain)
        winOptions = uiOptions(winMain)
        winAbout = uiAbout(winMain)  
        winMain.winQuery = winQuery
        winMain.winDataDictionary = winDataDictionary  
        winMain.winOptions = winOptions
        winMain.winAbout = winAbout

        # Apply styles and fonts
        Utils.applyStylesAndFonts(app, winMain.mainTable, winQuery.listQueryList)
        # Stylesheet can leave widgets on the old palette — re-assert theme.
        Utils.applyColorTheme()

        # Load data dictionary and quick looks (best-effort; do not block startup)
        # ensureDataDictionarySchema runs inside load/build (valuePrecision + precisionOverride)
        try:
            Logic.ensureDataDictionarySchema()
            Logic.loadAquariusRoundingSpecs()
            Utils.loadDataDictionary(winDataDictionary.mainTable)
        except Exception as e:
            Logic.logException("Startup: loadDataDictionary failed", e)
        try:
            Utils.loadQuickLooks(winQuery.cbQuickLook)
        except Exception as e:
            Logic.logException("Startup: loadQuickLooks failed", e)

        # Keep icon on the main window for showEvent re-apply (Windows cold start)
        if not appIcon.isNull(): winMain._appIcon = appIcon

        # Show main window
        winMain.show()

        # Re-apply window icon after first show (Windows sometimes paints the
        # default icon on the very first frame before the process icon sticks).
        if not appIcon.isNull():
            def _reapplyIcon(icon=appIcon, window=winMain, application=app):
                try:
                    application.setWindowIcon(icon)
                    window.setWindowIcon(icon)
                except Exception:
                    pass
            QTimer.singleShot(0, _reapplyIcon)
            QTimer.singleShot(100, _reapplyIcon)
            QTimer.singleShot(500, _reapplyIcon)
            QTimer.singleShot(1500, _reapplyIcon)
        try:
            Logic.logMessage("INFO", f"Config directory: {Utils.getConfigDir()}")
        except Exception:
            pass

        # Warm keyring off the critical path so first Options open is not cold
        QTimer.singleShot(0, warmKeyringCache)

        # GitHub release check (silent if no releases / offline / already current)
        Update.scheduleStartupUpdateCheck(winMain, delayMs=3000)

        # Convert legacy quickLooks
        try:
            Logic.convertLegacyQuickLooks()
        except Exception as e:
            Logic.logException("Startup: convertLegacyQuickLooks failed", e)
        
        # Start application
        sys.exit(app.exec())
    except Exception as e:
        try:
            Logic.logException("Fatal startup error", e)
        except Exception:
            print(f"Fatal startup error: {e}", file=sys.stderr)
        try:
            if app is not None: QMessageBox.critical(None, "Startup Error", f"Data Doctor failed to start:\n{e}")
        except Exception:
            pass
        sys.exit(1)