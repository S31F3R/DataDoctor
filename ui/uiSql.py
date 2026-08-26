# uiSql.py
# SQL Query Builder workbench: worksheets, pinned results, snippets/categories,
# history, stop, hide snippets. Session-only worksheets (not persisted).

from __future__ import annotations

import os
import json
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QSplitterHandle, QTabWidget,
    QTabBar, QPlainTextEdit, QTableWidget, QTableWidgetItem, QListWidget,
    QComboBox, QPushButton, QLabel, QMenu, QMessageBox, QInputDialog, QDialog,
    QDialogButtonBox, QSizePolicy,
)

from core import Logic, Utils, Config
from core.Oracle import oracleConnection

UNCATEGORIZED = "Uncategorized"
HISTORY_MAX = 50
SNIPPET_HANDLE_PX = 10


class SnippetPaneHandle(QSplitterHandle):
    """Vertical split grip: double-click collapses the snippet pane; grip stays visible."""

    def mouseDoubleClickEvent(self, event):
        sp = self.splitter()
        wb = getattr(sp, "_sqlWorkbench", None) if sp is not None else None
        if wb is not None:
            wb.toggleSnippets()
        event.accept()


class SnippetPaneSplitter(QSplitter):
    def createHandle(self):
        return SnippetPaneHandle(self.orientation(), self)


class sqlQuerySignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str, bool)
    cancelled = pyqtSignal()


class sqlQueryWorker(QRunnable):
    """Run Oracle SQL off the UI thread. Close the session to abort."""

    def __init__(self, dsn, sqlText, signals, cancelEvent):
        super().__init__()
        self.dsn = dsn
        self.sqlText = sqlText
        self.signals = signals
        self.cancelEvent = cancelEvent
        self.conn = None

    def run(self):
        try:
            from core.Oracle import OracleAuthError, isAuthError
            if self.cancelEvent.is_set():
                self.signals.cancelled.emit()
                return
            self.conn = oracleConnection(self.dsn)
            self.conn.connect()
            if self.cancelEvent.is_set():
                self.signals.cancelled.emit()
                return
            results = self.conn.executeCustomQuery(self.sqlText)
            if self.cancelEvent.is_set():
                self.signals.cancelled.emit()
                return
            self.signals.finished.emit(results if results is not None else [])
        except Exception as e:
            if self.cancelEvent.is_set():
                self.signals.cancelled.emit()
                return
            isAuth = False
            try:
                from core.Oracle import OracleAuthError, isAuthError
                isAuth = isinstance(e, OracleAuthError) or isAuthError(e)
            except Exception:
                pass
            Logic.logException("sqlQueryWorker: Failed to execute", e)
            self.signals.failed.emit(str(e), isAuth)
        finally:
            conn = self.conn
            self.conn = None
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


class SqlWorkbench:
    """Owns the SQL Query Builder tab contents (wired from uiMain)."""

    def __init__(self, mainWindow):
        self.win = mainWindow
        self.cancelEvent = threading.Event()
        self.worker = None
        self.running = False
        self._wsSeq = 1
        self._syncingDb = False
        self._snippetSizes = [1281, 256]
        self.setupUi()

    def setupUi(self):
        win = self.win
        sqlTab = win.tabSQL
        if sqlTab is None:
            return

        self.btnRun = win.btnRunQuery
        self.btnSaveSnippet = win.btnSaveSnippet
        self.btnDeleteSnippet = win.btnDeleteSnippet
        self.cbDatabase = win.cbDatabase
        self.lblDatabase = win.findChild(QLabel, "lblDatabase")
        self.listSnippets = win.listSnippets
        self.pteSQL = win.pteSQL
        self.sqlTable = win.sqlTable

        self.btnStop = QPushButton(sqlTab)
        self.btnStop.setObjectName("btnStopQuery")
        self.btnStop.setToolTip("Stop SQL query")
        self.btnHistory = QPushButton(sqlTab)
        self.btnHistory.setObjectName("btnSqlHistory")
        self.btnHistory.setToolTip("SQL history")
        self.btnCatagory = QPushButton(sqlTab)
        self.btnCatagory.setObjectName("btnSqlCatagory")
        self.btnCatagory.setToolTip("Add or remove snippet categories")
        self.btnNewWorksheet = QPushButton(sqlTab)
        self.btnNewWorksheet.setObjectName("btnNewSqlWorksheet")
        self.btnNewWorksheet.setToolTip("New query tab")

        self.cbCategory = QComboBox(sqlTab)
        self.cbCategory.setObjectName("cbSqlCategory")
        self.cbCategory.setMinimumWidth(140)

        for btn, icon, size in (
            (self.btnRun, "Play", 36),
            (self.btnStop, "Deny", 36),
            (self.btnHistory, "History", 36),
            (self.btnSaveSnippet, "StarPlus", 36),
            (self.btnDeleteSnippet, "StarMinus", 36),
            (self.btnCatagory, "Catagory", 36),
            (self.btnNewWorksheet, "Plus", 36),
        ):
            if btn is not None:
                Utils.buttonStyle(btn, icon, iconSize=size)

        self.btnStop.setEnabled(False)

        self.worksheetTabs = QTabWidget(sqlTab)
        self.worksheetTabs.setObjectName("sqlWorksheetTabs")
        self.worksheetTabs.setTabsClosable(True)
        self.worksheetTabs.setMovable(False)
        self.worksheetTabs.setDocumentMode(False)

        self.resultStack = QTabWidget(sqlTab)
        self.resultStack.setObjectName("sqlResultHost")
        self.resultStack.tabBar().hide()
        self.resultStack.setDocumentMode(True)

        # First worksheet reuses the .ui editor
        if self.pteSQL is None:
            self.pteSQL = QPlainTextEdit(sqlTab)
            self.pteSQL.setObjectName("pteSQL")
        editor = self.pteSQL
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.worksheetTabs.addTab(editor, "Query 1")

        resultTabs = self._newResultTabs(sqlTab)
        if self.sqlTable is None:
            self.sqlTable = QTableWidget(sqlTab)
            self.sqlTable.setObjectName("sqlTable")
        firstTable = self.sqlTable
        firstTable.setSortingEnabled(True)
        firstTable.horizontalHeader().setStretchLastSection(False)
        firstTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        resultTabs.addTab(self._wrapResult(firstTable, pinned=False), "Result")
        resultTabs.tabBar().setTabData(0, {"pinned": False})
        self._installPinButton(resultTabs, 0)
        self.resultStack.addTab(resultTabs, "ws")

        # Top bar: Run, Stop, New query tab, History, database
        topLayout = QHBoxLayout()
        topLayout.setSpacing(0)
        topLayout.setContentsMargins(4, 4, 4, 2)
        topLayout.addWidget(self.btnRun)
        topLayout.addSpacing(10)
        topLayout.addWidget(self.btnStop)
        topLayout.addSpacing(10)
        topLayout.addWidget(self.btnNewWorksheet)
        topLayout.addSpacing(10)
        topLayout.addWidget(self.btnHistory)
        topLayout.addSpacing(20)
        if self.lblDatabase is not None:
            topLayout.addWidget(self.lblDatabase)
        comboWrap = QWidget(sqlTab)
        comboLay = QVBoxLayout(comboWrap)
        comboLay.setContentsMargins(0, 4, 0, 0)
        comboLay.setSpacing(0)
        if self.cbDatabase is not None:
            comboLay.addWidget(self.cbDatabase)
        topLayout.addWidget(comboWrap)
        topLayout.addStretch()

        sqlSplitter = QSplitter(Qt.Orientation.Vertical, sqlTab)
        sqlSplitter.setObjectName("sqlSplitter")
        sqlSplitter.addWidget(self.worksheetTabs)
        sqlSplitter.addWidget(self.resultStack)
        sqlSplitter.setSizes([231, 291])

        leftWidget = QWidget(sqlTab)
        leftLay = QVBoxLayout(leftWidget)
        leftLay.setContentsMargins(0, 0, 0, 0)
        leftLay.setSpacing(0)
        leftLay.addLayout(topLayout)
        leftLay.addWidget(sqlSplitter, 1)

        # Snippet side panel
        snippetTop = QHBoxLayout()
        snippetTop.setContentsMargins(4, 4, 4, 2)
        snippetTop.setSpacing(8)
        snippetTop.addWidget(self.btnSaveSnippet)
        snippetTop.addWidget(self.btnDeleteSnippet)
        snippetTop.addWidget(self.btnCatagory)
        snippetTop.addStretch()

        snippetPanel = QWidget(sqlTab)
        snippetPanel.setObjectName("sqlSnippetPanel")
        snippetLay = QVBoxLayout(snippetPanel)
        snippetLay.setContentsMargins(0, 0, 0, 0)
        snippetLay.setSpacing(4)
        snippetLay.addLayout(snippetTop)
        snippetLay.addWidget(self.cbCategory)
        if self.listSnippets is not None:
            snippetLay.addWidget(self.listSnippets, 1)

        mainSplitter = SnippetPaneSplitter(Qt.Orientation.Horizontal, sqlTab)
        mainSplitter.setObjectName("mainSplitter")
        mainSplitter._sqlWorkbench = self
        mainSplitter.setHandleWidth(SNIPPET_HANDLE_PX)
        mainSplitter.setChildrenCollapsible(True)
        mainSplitter.setCollapsible(0, False)
        mainSplitter.setCollapsible(1, True)
        snippetPanel.setMinimumWidth(0)
        mainSplitter.addWidget(leftWidget)
        mainSplitter.addWidget(snippetPanel)
        mainSplitter.setSizes([1281, 256])
        self.snippetPanel = snippetPanel
        self.mainSplitter = mainSplitter
        self.sqlSplitter = sqlSplitter

        if sqlTab.layout():
            old = sqlTab.layout()
            while old.count():
                item = old.takeAt(0)
                # widgets are re-parented below; do not deleteLater
        mainLayout = QVBoxLayout(sqlTab)
        mainLayout.setContentsMargins(0, 0, 0, 0)
        mainLayout.addWidget(mainSplitter)

        self._wire()
        self._loadCategories()
        self._styleSnippetHandle()
        handle = mainSplitter.handle(1)
        if handle is not None:
            handle.setToolTip("Double-click to collapse or expand SQL quick looks")
        self._applySnippetHidden(bool(Utils.loadConfig().get("sqlSnippetsHidden", False)))

    def _newResultTabs(self, parent):
        tabs = QTabWidget(parent)
        # Pin sits where the close X would be; worksheets keep X.
        tabs.setTabsClosable(False)
        tabs.setMovable(False)
        bar = tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(
            lambda pos, t=tabs: self._resultTabMenu(t, pos)
        )
        return tabs

    def _wrapResult(self, table, pinned=False):
        table.setProperty("sqlPinned", bool(pinned))
        return table

    def _wire(self):
        self.btnRun.clicked.connect(self.runQuery)
        self.btnStop.clicked.connect(self.stopQuery)
        self.btnHistory.clicked.connect(self.showHistory)
        self.btnSaveSnippet.clicked.connect(self.saveSnippet)
        self.btnDeleteSnippet.clicked.connect(self.deleteSnippet)
        self.btnCatagory.clicked.connect(self.manageCategories)
        self.btnNewWorksheet.clicked.connect(self.addWorksheet)
        self.worksheetTabs.tabCloseRequested.connect(self.closeWorksheet)
        self.worksheetTabs.currentChanged.connect(self._onWorksheetChanged)
        bar = self.worksheetTabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._worksheetTabMenu)
        if self.cbDatabase is not None:
            self.cbDatabase.currentTextChanged.connect(self._onDatabaseChanged)
        if self.cbCategory is not None:
            self.cbCategory.currentTextChanged.connect(self._onCategoryChanged)
        if self.listSnippets is not None:
            self.listSnippets.doubleClicked.connect(self.loadSnippet)

    def currentEditor(self):
        w = self.worksheetTabs.currentWidget()
        return w if isinstance(w, QPlainTextEdit) else self.win.pteSQL

    def currentResultTabs(self):
        idx = self.worksheetTabs.currentIndex()
        if idx < 0 or idx >= self.resultStack.count():
            return None
        return self.resultStack.widget(idx)

    def currentResultTable(self):
        tabs = self.currentResultTabs()
        if tabs is None:
            return self.win.sqlTable
        w = tabs.currentWidget()
        if isinstance(w, QTableWidget):
            return w
        return self.win.sqlTable

    def currentDatabase(self):
        if self.cbDatabase is None:
            return ""
        return self.cbDatabase.currentText() or ""

    def _worksheetDatabase(self, editor):
        return editor.property("sqlDatabase") or ""

    def _setWorksheetDatabase(self, editor, db):
        if editor is not None:
            editor.setProperty("sqlDatabase", db or "")

    def _onDatabaseChanged(self, text):
        if self._syncingDb:
            return
        self._setWorksheetDatabase(self.currentEditor(), text)

    def _onWorksheetChanged(self, index):
        if index < 0:
            return
        self.resultStack.setCurrentIndex(index)
        editor = self.currentEditor()
        db = self._worksheetDatabase(editor)
        if self.cbDatabase is not None:
            self._syncingDb = True
            try:
                if db:
                    i = self.cbDatabase.findText(db)
                    if i >= 0:
                        self.cbDatabase.setCurrentIndex(i)
                # if no stored db, keep combo as-is and stamp it on this sheet
                else:
                    self._setWorksheetDatabase(editor, self.currentDatabase())
            finally:
                self._syncingDb = False
        self.win.pteSQL = editor
        self.win.sqlTable = self.currentResultTable()

    def addWorksheet(self):
        self._wsSeq += 1
        editor = QPlainTextEdit(self.win.tabSQL)
        editor.setObjectName(f"pteSQL_{self._wsSeq}")
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setWorksheetDatabase(editor, self.currentDatabase())
        name = f"Query {self._wsSeq}"
        idx = self.worksheetTabs.addTab(editor, name)
        resultTabs = self._newResultTabs(self.win.tabSQL)
        table = QTableWidget(self.win.tabSQL)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(False)
        resultTabs.addTab(self._wrapResult(table, pinned=False), "Result")
        resultTabs.tabBar().setTabData(0, {"pinned": False})
        self._installPinButton(resultTabs, 0)
        self.resultStack.addTab(resultTabs, "ws")
        self.worksheetTabs.setCurrentIndex(idx)
        if Config.debug:
            Logic.logMessage("DEBUG", f"SqlWorkbench: added worksheet {name}")

    def closeWorksheet(self, index):
        if self.worksheetTabs.count() <= 1:
            editor = self.worksheetTabs.widget(0)
            if isinstance(editor, QPlainTextEdit):
                editor.clear()
            tabs = self.resultStack.widget(0)
            if isinstance(tabs, QTabWidget):
                while tabs.count() > 1:
                    w = tabs.widget(tabs.count() - 1)
                    tabs.removeTab(tabs.count() - 1)
                    if w is not None:
                        w.deleteLater()
                table = tabs.widget(0)
                if isinstance(table, QTableWidget):
                    table.clear()
                    table.setRowCount(0)
                    table.setColumnCount(0)
                tabs.tabBar().setTabData(0, {"pinned": False})
                tabs.setTabText(0, "Result")
                self._installPinButton(tabs, 0)
            return
        w = self.worksheetTabs.widget(index)
        r = self.resultStack.widget(index)
        self.worksheetTabs.removeTab(index)
        self.resultStack.removeTab(index)
        if w is not None:
            w.deleteLater()
        if r is not None:
            r.deleteLater()

    def _worksheetTabMenu(self, pos):
        bar = self.worksheetTabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self.win)
        actRename = menu.addAction("Rename")
        actNew = menu.addAction("New query tab")
        chosen = menu.exec(bar.mapToGlobal(pos))
        if chosen == actRename:
            self._renameTab(self.worksheetTabs, idx)
        elif chosen == actNew:
            self.addWorksheet()

    def _resultTabMenu(self, tabs, pos):
        bar = tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0:
            return
        pinned = bool((bar.tabData(idx) or {}).get("pinned"))
        menu = QMenu(self.win)
        actRename = menu.addAction("Rename")
        actPin = menu.addAction("Unpin" if pinned else "Pin")
        actClose = menu.addAction("Close")
        chosen = menu.exec(bar.mapToGlobal(pos))
        if chosen == actRename:
            self._renameTab(tabs, idx)
        elif chosen == actPin:
            self._togglePinAt(tabs, idx)
        elif chosen == actClose:
            self._closeResultTab(tabs, idx)

    def _renameTab(self, tabs, index):
        current = tabs.tabText(index)
        name, ok = QInputDialog.getText(
            self.win, "Rename tab", "Name:", text=current
        )
        if ok and name.strip():
            tabs.setTabText(index, name.strip())

    def _isPinned(self, tabs, index):
        if tabs is None or index < 0:
            return False
        data = tabs.tabBar().tabData(index) or {}
        return bool(data.get("pinned"))

    def _setPinned(self, tabs, index, pinned):
        tabs.tabBar().setTabData(index, {"pinned": bool(pinned)})
        table = tabs.widget(index)
        if table is not None:
            table.setProperty("sqlPinned", bool(pinned))
        self._refreshPinButton(tabs, index)

    def _installPinButton(self, tabs, index):
        """Pin/Pinned control in the tab's close-button slot (result tabs only)."""
        btn = QPushButton(tabs)
        btn.setObjectName("btnResultPin")
        btn.setFlat(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        Utils.buttonStyle(btn, "Pin", iconSize=16)
        btn.setFixedSize(18, 18)
        btn.setToolTip("Pin result (next run opens a new tab)")
        btn.clicked.connect(lambda _checked=False, t=tabs, b=btn: self._togglePinFromButton(t, b))
        tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)
        self._refreshPinButton(tabs, index)

    def _togglePinFromButton(self, tabs, btn):
        bar = tabs.tabBar()
        for i in range(tabs.count()):
            if bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self._togglePinAt(tabs, i)
                return

    def _refreshPinButton(self, tabs, index):
        if tabs is None or index < 0 or index >= tabs.count():
            return
        btn = tabs.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        if btn is None:
            return
        pinned = self._isPinned(tabs, index)
        Utils.buttonStyle(btn, "Pinned" if pinned else "Pin", iconSize=16)
        btn.setToolTip(
            "Unpin result" if pinned else "Pin result (next run opens a new tab)"
        )

    def _togglePinAt(self, tabs, index):
        if tabs is None or index < 0 or index >= tabs.count():
            return
        self._setPinned(tabs, index, not self._isPinned(tabs, index))

    def togglePin(self):
        tabs = self.currentResultTabs()
        if tabs is None:
            return
        i = tabs.currentIndex()
        if i < 0:
            return
        self._togglePinAt(tabs, i)

    def _targetResultTab(self, tabs):
        """Reuse the current unpinned tab, else add a new result tab."""
        cur = tabs.currentIndex()
        if cur >= 0 and not self._isPinned(tabs, cur):
            return cur
        for i in range(tabs.count()):
            if not self._isPinned(tabs, i):
                tabs.setCurrentIndex(i)
                return i
        table = QTableWidget(self.win.tabSQL)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(False)
        idx = tabs.addTab(self._wrapResult(table, pinned=False), "Result")
        tabs.tabBar().setTabData(idx, {"pinned": False})
        self._installPinButton(tabs, idx)
        tabs.setCurrentIndex(idx)
        return idx

    def _closeResultTab(self, tabs, index):
        if tabs.count() <= 1:
            table = tabs.widget(0)
            if isinstance(table, QTableWidget):
                table.clear()
                table.setRowCount(0)
                table.setColumnCount(0)
            tabs.setTabText(0, "Result")
            tabs.tabBar().setTabData(0, {"pinned": False})
            self._installPinButton(tabs, 0)
            return
        w = tabs.widget(index)
        tabs.removeTab(index)
        if w is not None:
            w.deleteLater()

    def runQuery(self):
        if self.running:
            QMessageBox.information(self.win, "Run Query", "A SQL query is already running.")
            return
        editor = self.currentEditor()
        if editor is None:
            return
        sqlText = editor.toPlainText().strip()
        if not sqlText:
            QMessageBox.warning(self.win, "Run Query", "No SQL query to run.")
            return
        db = self.currentDatabase()
        dsn = db.split("-")[1].lower() if "-" in db else db.lower()
        self._setWorksheetDatabase(editor, db)
        self._rememberHistory(sqlText, db)
        self.cancelEvent = threading.Event()
        self.running = True
        self.btnRun.setEnabled(False)
        self.btnStop.setEnabled(True)
        signals = sqlQuerySignals()
        self.win.sqlQuerySignals = signals
        signals.finished.connect(self._onFinished)
        signals.failed.connect(self._onFailed)
        signals.cancelled.connect(self._onCancelled)
        self.worker = sqlQueryWorker(dsn, sqlText, signals, self.cancelEvent)
        QThreadPool.globalInstance().start(self.worker)
        if Config.debug:
            Logic.logMessage("DEBUG", f"SqlWorkbench.runQuery: dsn={dsn}")

    def stopQuery(self):
        if not self.running:
            return
        self.cancelEvent.set()
        worker = self.worker
        if worker is not None and worker.conn is not None:
            try:
                worker.conn.close()
            except Exception:
                pass
        if Config.debug:
            Logic.logMessage("DEBUG", "SqlWorkbench.stopQuery: cancel requested")

    def _onCancelled(self):
        self._clearRunning()
        if Config.debug:
            Logic.logMessage("DEBUG", "SqlWorkbench: query cancelled")

    def _clearRunning(self):
        self.running = False
        self.worker = None
        self.btnRun.setEnabled(True)
        self.btnStop.setEnabled(False)

    def _onFinished(self, results):
        self._clearRunning()
        tabs = self.currentResultTabs()
        if tabs is None:
            return
        idx = self._targetResultTab(tabs)
        table = tabs.widget(idx)
        if not isinstance(table, QTableWidget):
            return
        self.win.sqlTable = table
        if not results:
            table.clear()
            table.setRowCount(0)
            table.setColumnCount(0)
            QMessageBox.information(self.win, "Query Result", "No results returned.")
            return
        try:
            columns = list(results[0].keys())
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels(columns)
            table.setRowCount(len(results))
            table.horizontalHeader().setStretchLastSection(False)
            for row, res in enumerate(results):
                for col, key in enumerate(columns):
                    table.setItem(row, col, QTableWidgetItem(str(res.get(key, ""))))
            table.resizeColumnsToContents()
        except Exception as e:
            Logic.logException("SqlWorkbench: failed to populate result", e)
            QMessageBox.warning(self.win, "Query Error", f"Failed to display results: {e}")

    def _onFailed(self, message, isAuthError):
        self._clearRunning()
        if isAuthError:
            upper = (message or "").upper()
            title = (
                "Oracle Password Expired"
                if ("EXPIRED" in upper or "ORA-28001" in upper)
                else "Oracle Login Failed"
            )
            QMessageBox.warning(self.win, title, message)
        else:
            QMessageBox.warning(self.win, "Query Error", f"Failed to execute query: {message}")

    def _rememberHistory(self, sqlText, database):
        config = Utils.loadConfig()
        hist = list(config.get("sqlHistory") or [])
        entry = {
            "sql": sqlText,
            "database": database or "",
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        hist = [h for h in hist if not (
            (h.get("sql") or "") == sqlText and (h.get("database") or "") == (database or "")
        )]
        hist.insert(0, entry)
        config["sqlHistory"] = hist[:HISTORY_MAX]
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            Logic.logException("SqlWorkbench: save history failed", e)

    def showHistory(self):
        config = Utils.loadConfig()
        hist = list(config.get("sqlHistory") or [])
        dlg = QDialog(self.win)
        dlg.setWindowTitle("SQL History")
        dlg.resize(640, 420)
        lay = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        for item in hist:
            sql = (item.get("sql") or "").strip()
            first = sql.splitlines()[0] if sql else "(empty)"
            if len(first) > 80:
                first = first[:77] + "..."
            db = item.get("database") or ""
            ts = item.get("ts") or ""
            label = f"{ts}  {db}  {first}".strip()
            lst.addItem(label)
            lst.item(lst.count() - 1).setData(Qt.ItemDataRole.UserRole, item)
        lay.addWidget(lst)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        lay.addWidget(buttons)
        buttons.rejected.connect(dlg.reject)

        def loadCurrent():
            it = lst.currentItem()
            if it is None:
                return
            self._applyHistory(it.data(Qt.ItemDataRole.UserRole) or {})
            dlg.accept()

        buttons.accepted.connect(loadCurrent)
        lst.itemDoubleClicked.connect(lambda _i: loadCurrent())
        dlg.exec()

    def _applyHistory(self, entry):
        editor = self.currentEditor()
        if editor is None:
            return
        editor.setPlainText(entry.get("sql") or "")
        db = entry.get("database") or ""
        self._setWorksheetDatabase(editor, db)
        if db and self.cbDatabase is not None:
            i = self.cbDatabase.findText(db)
            if i >= 0:
                self._syncingDb = True
                try:
                    self.cbDatabase.setCurrentIndex(i)
                finally:
                    self._syncingDb = False

    def _snippetsCollapsed(self):
        sizes = self.mainSplitter.sizes() if self.mainSplitter is not None else []
        return len(sizes) >= 2 and sizes[1] <= SNIPPET_HANDLE_PX + 2

    def toggleSnippets(self):
        self._applySnippetHidden(not self._snippetsCollapsed())
        config = Utils.loadConfig()
        config["sqlSnippetsHidden"] = self._snippetsCollapsed()
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            Logic.logException("SqlWorkbench: save snippet collapse failed", e)

    def _styleSnippetHandle(self):
        if self.mainSplitter is None:
            return
        if Config.retroMode:
            bg, hover = "#00AA00", "#00FF00"
        else:
            bg, hover = "#8a8a8a", "#5a9fd4"
        self.mainSplitter.setHandleWidth(SNIPPET_HANDLE_PX)
        self.mainSplitter.setStyleSheet(
            f"QSplitter#mainSplitter::handle:horizontal {{"
            f"  width: {SNIPPET_HANDLE_PX}px;"
            f"  background: {bg};"
            f"  margin: 0px;"
            f"  border: none;"
            f"}}"
            f"QSplitter#mainSplitter::handle:horizontal:hover {{"
            f"  background: {hover};"
            f"}}"
        )

    def _applySnippetHidden(self, hidden):
        """Collapse snippet pane to the right; the split handle stays on the edge."""
        if self.mainSplitter is None:
            return
        sizes = self.mainSplitter.sizes()
        total = sum(sizes) if sizes else self.mainSplitter.width()
        if total <= 0:
            total = 1537
        if hidden:
            if len(sizes) >= 2 and sizes[1] > SNIPPET_HANDLE_PX + 8:
                self._snippetSizes = sizes
            self.mainSplitter.setSizes([max(total - SNIPPET_HANDLE_PX, 1), 0])
        else:
            restored = self._snippetSizes
            if not restored or restored[1] < 80:
                restored = [max(total - 256, 1), 256]
            self.mainSplitter.setSizes(restored)

    def _loadCategories(self):
        config = Utils.loadConfig()
        cats = list(config.get("sqlCategories") or [])
        if UNCATEGORIZED not in cats:
            cats = [UNCATEGORIZED] + [c for c in cats if c != UNCATEGORIZED]
        self.cbCategory.blockSignals(True)
        self.cbCategory.clear()
        self.cbCategory.addItems(cats)
        current = config.get("sqlCategoryCurrent") or UNCATEGORIZED
        i = self.cbCategory.findText(current)
        self.cbCategory.setCurrentIndex(i if i >= 0 else 0)
        self.cbCategory.blockSignals(False)
        self.loadSnippets()

    def _onCategoryChanged(self, _text):
        config = Utils.loadConfig()
        config["sqlCategoryCurrent"] = self.cbCategory.currentText()
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception:
            pass
        self.loadSnippets()

    def manageCategories(self):
        config = Utils.loadConfig()
        cats = [c for c in (config.get("sqlCategories") or []) if c != UNCATEGORIZED]
        dlg = QDialog(self.win)
        dlg.setWindowTitle("Snippet categories")
        dlg.resize(360, 320)
        lay = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        lst.addItems(cats)
        lay.addWidget(lst)
        row = QHBoxLayout()
        btnAdd = QPushButton("Add")
        btnRemove = QPushButton("Remove")
        row.addWidget(btnAdd)
        row.addWidget(btnRemove)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        buttons.clicked.connect(dlg.accept)
        lay.addWidget(buttons)

        def addCat():
            name, ok = QInputDialog.getText(dlg, "Add category", "Name:")
            name = (name or "").strip()
            if not ok or not name:
                return
            if name == UNCATEGORIZED or lst.findItems(name, Qt.MatchFlag.MatchExactly):
                QMessageBox.information(dlg, "Categories", "That category already exists.")
                return
            lst.addItem(name)

        def removeCat():
            it = lst.currentItem()
            if it is None:
                return
            lst.takeItem(lst.row(it))

        btnAdd.clicked.connect(addCat)
        btnRemove.clicked.connect(removeCat)
        dlg.exec()
        newCats = [lst.item(i).text() for i in range(lst.count())]
        mapping = dict(config.get("sqlSnippetCategory") or {})
        allowed = set(newCats)
        for name, cat in list(mapping.items()):
            if cat not in allowed:
                mapping[name] = UNCATEGORIZED
        config["sqlCategories"] = [UNCATEGORIZED] + newCats
        config["sqlSnippetCategory"] = mapping
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            Logic.logException("SqlWorkbench: save categories failed", e)
        self._loadCategories()

    def loadSnippets(self):
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
            savedOrder = config.get("sqlSnippetOrder") or []
            mapping = dict(config.get("sqlSnippetCategory") or {})
            currentCat = self.cbCategory.currentText() if self.cbCategory else UNCATEGORIZED
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
                cat = mapping.get(name) or UNCATEGORIZED
                if cat == currentCat:
                    self.listSnippets.addItem(name)
        except Exception as e:
            Logic.logException("loadSnippets failed", e)

    def saveSnippet(self):
        editor = self.currentEditor()
        if editor is None:
            return
        sqlText = editor.toPlainText().strip()
        if not sqlText:
            QMessageBox.warning(self.win, "Save Snippet", "No SQL query to save.")
            return
        name, ok = QInputDialog.getText(self.win, "Save Snippet", "Snippet name:")
        if not (ok and name.strip()):
            return
        name = name.strip()
        sqlDir = Utils.getSqlSnippetDir()
        filePath = os.path.join(sqlDir, f"{name}.sql")
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(sqlText)
        config = Utils.loadConfig()
        mapping = dict(config.get("sqlSnippetCategory") or {})
        mapping[name] = self.cbCategory.currentText() or UNCATEGORIZED
        config["sqlSnippetCategory"] = mapping
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            Logic.logException("saveSnippet category map failed", e)
        self.win.saveSnippetOrder()
        self.loadSnippets()

    def loadSnippet(self, index):
        if self.listSnippets is None:
            return
        item = self.listSnippets.itemFromIndex(index)
        if item is None:
            return
        name = item.text()
        filePath = os.path.join(Utils.getSqlSnippetDir(), f"{name}.sql")
        if not os.path.exists(filePath):
            return
        with open(filePath, "r", encoding="utf-8") as f:
            sqlText = f.read()
        editor = self.currentEditor()
        if editor is not None:
            editor.setPlainText(sqlText)

    def deleteSnippet(self):
        if self.listSnippets is None:
            return
        selected = self.listSnippets.currentItem()
        if selected is None:
            QMessageBox.warning(self.win, "Delete Snippet", "No snippet selected.")
            return
        name = selected.text()
        reply = QMessageBox.question(
            self.win, "Delete Snippet", f"Delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        filePath = os.path.join(Utils.getSqlSnippetDir(), f"{name}.sql")
        if os.path.exists(filePath):
            os.remove(filePath)
        config = Utils.loadConfig()
        mapping = dict(config.get("sqlSnippetCategory") or {})
        mapping.pop(name, None)
        config["sqlSnippetCategory"] = mapping
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception:
            pass
        self.listSnippets.takeItem(self.listSnippets.row(selected))
        self.win.saveSnippetOrder()

    def refresh(self):
        """Called when the SQL tab is shown."""
        config = Utils.loadConfig()
        if self.sqlSplitter is not None and "sqlVerticalSizes" in config:
            self.sqlSplitter.setSizes(config["sqlVerticalSizes"])
        if self.mainSplitter is not None and "sqlHorizontalSizes" in config:
            self._snippetSizes = config["sqlHorizontalSizes"]
            if not bool(config.get("sqlSnippetsHidden", False)):
                self.mainSplitter.setSizes(config["sqlHorizontalSizes"])
        self._styleSnippetHandle()
        if self.cbDatabase is not None:
            Utils.loadDatabase(self.cbDatabase, "sql")
            self.cbDatabase.setMinimumWidth(200)
            self.cbDatabase.adjustSize()
            editor = self.currentEditor()
            if editor is not None and not self._worksheetDatabase(editor):
                self._setWorksheetDatabase(editor, self.currentDatabase())
        self._loadCategories()
