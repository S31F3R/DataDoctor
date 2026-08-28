# uiSql.py
# SQL Query Builder workbench: worksheets, pinned results, snippets/categories,
# history, stop, hide snippets. Session-only worksheets (not persisted).

from __future__ import annotations

import os
import json
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal, QPointF, QRect, QEvent
from PyQt6.QtGui import QPainter, QColor, QPixmap, QPalette, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QSplitterHandle, QTabWidget,
    QTabBar, QPlainTextEdit, QTableWidget, QTableWidgetItem, QListWidget,
    QComboBox, QPushButton, QLabel, QMenu, QMessageBox, QInputDialog, QDialog,
    QDialogButtonBox, QSizePolicy, QAbstractItemView, QToolTip,
)

from core import Logic, Utils, Config
from core.Oracle import oracleConnection

UNCATEGORIZED = "Uncategorized"
HISTORY_MAX = 50
SNIPPET_HANDLE_PX = 6
PIN_ICON_PX = 16
PIN_SLOT_PX = 22


def _pinPixmap(iconName, kind, iconSize=PIN_ICON_PX):
    if kind == "hover":
        path = Logic.resourcePath(f"ui/icons/hoover/{iconName}.png")
    elif kind == "pressed":
        path = Logic.resourcePath(f"ui/icons/pressed/{iconName}.png")
    else:
        path = Logic.resourcePath(f"ui/icons/{iconName}.png")
    pix = QPixmap(path)
    if pix.isNull() and kind != "normal":
        pix = QPixmap(Logic.resourcePath(f"ui/icons/{iconName}.png"))
    if not pix.isNull() and iconSize:
        pix = pix.scaled(
            iconSize, iconSize,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pix


class ResultTabBar(QTabBar):
    """
    Result tabs paint Pin/Pinned in the close-X slot.

    QTabBar.setTabButton widgets do not get hover or reliable clicks — Qt
    handles that slot itself (same reason worksheet close-X uses QSS
    QTabBar::close-button:hover, not a child QPushButton).
    """

    pinClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hoverIndex = -1
        self._pressedIndex = -1
        self._pix = {}
        for name in ("Pin", "Pinned"):
            self._pix[name] = {
                "normal": _pinPixmap(name, "normal"),
                "hover": _pinPixmap(name, "hover"),
                "pressed": _pinPixmap(name, "pressed"),
            }

    def tabInserted(self, index):
        super().tabInserted(index)
        # Empty right-side widget so Qt reserves the close-X slot for text
        # layout. Mouse-transparent: hover/click stay on this bar.
        slot = QWidget(self)
        slot.setFixedSize(PIN_ICON_PX + 4, PIN_ICON_PX + 4)
        slot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        slot.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTabButton(index, QTabBar.ButtonPosition.RightSide, slot)

    def _isPinned(self, index):
        data = self.tabData(index) or {}
        if isinstance(data, dict):
            return bool(data.get("pinned"))
        return False

    def _pinRect(self, index):
        slot = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if slot is not None:
            g = slot.geometry()
            if g.width() > 0 and g.height() > 0:
                x = g.x() + (g.width() - PIN_ICON_PX) // 2
                y = g.y() + (g.height() - PIN_ICON_PX) // 2
                return QRect(x, y, PIN_ICON_PX, PIN_ICON_PX)
        r = self.tabRect(index)
        x = r.right() - PIN_SLOT_PX + (PIN_SLOT_PX - PIN_ICON_PX) // 2
        y = r.y() + (r.height() - PIN_ICON_PX) // 2
        return QRect(x, y, PIN_ICON_PX, PIN_ICON_PX)

    def _pinHitRect(self, index):
        slot = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if slot is not None:
            g = slot.geometry()
            if g.width() > 0 and g.height() > 0:
                return g
        return self._pinRect(index).adjusted(-3, -3, 3, 3)

    def _indexAtPin(self, pos):
        i = self.tabAt(pos)
        if i < 0:
            return -1
        if self._pinHitRect(i).contains(pos):
            return i
        return -1

    def _pinTip(self, index):
        if self._isPinned(index):
            return "Unpin result"
        return "Pin result (next run opens a new tab)"

    def _cursorPinIndex(self):
        return self._indexAtPin(self.mapFromGlobal(QCursor.pos()))

    def _syncHover(self, pos):
        idx = self._indexAtPin(pos)
        if idx == self._hoverIndex:
            return
        self._hoverIndex = idx
        if idx >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        self.update()

    def _clearHover(self):
        # Tooltip popup steals hover; if the cursor is still on the pin, keep it.
        if self._pressedIndex >= 0 or self._cursorPinIndex() >= 0:
            return
        if self._hoverIndex < 0:
            return
        self._hoverIndex = -1
        self.unsetCursor()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for i in range(self.count()):
            name = "Pinned" if self._isPinned(i) else "Pin"
            if self._pressedIndex == i:
                kind = "pressed"
            elif self._hoverIndex == i:
                kind = "hover"
            else:
                kind = "normal"
            pix = self._pix[name][kind]
            if pix is None or pix.isNull():
                continue
            painter.drawPixmap(self._pinRect(i), pix)

    def event(self, event):
        et = event.type()
        if et == QEvent.Type.ToolTip:
            idx = self._indexAtPin(event.pos())
            if idx >= 0:
                QToolTip.showText(
                    event.globalPos(), self._pinTip(idx), self, self._pinHitRect(idx)
                )
                return True
            return super().event(event)
        if et in (QEvent.Type.HoverMove, QEvent.Type.HoverEnter):
            self._syncHover(event.position().toPoint())
        elif et == QEvent.Type.HoverLeave:
            self._clearHover()
        return super().event(event)

    def mouseMoveEvent(self, event):
        self._syncHover(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._clearHover()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._indexAtPin(event.position().toPoint())
            if idx >= 0:
                self._pressedIndex = idx
                self.setCurrentIndex(idx)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressedIndex >= 0:
            idx = self._pressedIndex
            self._pressedIndex = -1
            if self._indexAtPin(event.position().toPoint()) == idx:
                self.pinClicked.emit(idx)
            self._hoverIndex = self._indexAtPin(event.position().toPoint())
            if self._hoverIndex >= 0:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                if QToolTip.isVisible():
                    QToolTip.showText(
                        QCursor.pos(),
                        self._pinTip(self._hoverIndex),
                        self,
                        self._pinHitRect(self._hoverIndex),
                    )
            else:
                self.unsetCursor()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._indexAtPin(event.position().toPoint()) >= 0:
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class ResultTabWidget(QTabWidget):
    """Result tabs use ResultTabBar so Pin/Pinned hover, press, and toggle work."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(ResultTabBar(self))
        self.setTabsClosable(False)
        self.setMovable(False)
        self.setDocumentMode(False)


class SnippetPaneHandle(QSplitterHandle):
    """
    Thin splitter grip matching the query/result handle: window/tab color
    with a short dotted grabber in the middle. Double-click collapses.
    """

    def mouseDoubleClickEvent(self, event):
        sp = self.splitter()
        wb = getattr(sp, "_sqlWorkbench", None) if sp is not None else None
        if wb is not None:
            wb.toggleSnippets()
        event.accept()

    def _chromePalette(self):
        """Tab-strip / button-face palette (lighter than the pane in dark mode)."""
        from PyQt6.QtWidgets import QApplication
        sp = self.splitter()
        wb = getattr(sp, "_sqlWorkbench", None) if sp is not None else None
        ref = None
        if wb is not None:
            wt = getattr(wb, "worksheetTabs", None)
            if wt is not None:
                ref = wt.tabBar()
            if ref is None:
                ref = getattr(wb, "btnRun", None)
        if ref is not None:
            return ref.palette()
        app = QApplication.instance()
        return app.palette() if app is not None else self.palette()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self._chromePalette()
        # Button = control chrome behind tabs and toolbar buttons
        bg = pal.color(QPalette.ColorRole.Button)
        window = pal.color(QPalette.ColorRole.Window)
        if bg.lightness() <= window.lightness():
            midlight = pal.color(QPalette.ColorRole.Midlight)
            if midlight.lightness() > bg.lightness():
                bg = midlight
        painter.fillRect(self.rect(), bg)
        if Config.retroMode:
            dot = QColor("#00FF00")
        else:
            dot = pal.color(QPalette.ColorRole.Mid)
            if abs(dot.lightness() - bg.lightness()) < 35:
                dot = pal.color(QPalette.ColorRole.WindowText)
                dot.setAlpha(150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = 1.25
        gap = 5.0
        for i in range(-2, 3):
            painter.drawEllipse(QPointF(cx, cy + i * gap), radius, radius)
        painter.end()


class SnippetPaneSplitter(QSplitter):
    def createHandle(self):
        return SnippetPaneHandle(self.orientation(), self)


class _CategoryDropList(QListWidget):
    """Left pane: drop a snippet name here to recategorize it."""

    def __init__(self, onDrop, parent=None):
        super().__init__(parent)
        self._onDrop = onDrop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        src = event.source()
        if isinstance(src, QListWidget) and src is not self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.itemAt(event.position().toPoint()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        dest = self.itemAt(event.position().toPoint())
        src = event.source()
        if dest is None or not isinstance(src, QListWidget):
            event.ignore()
            return
        snippet = src.currentItem()
        if snippet is None:
            event.ignore()
            return
        self._onDrop(snippet.text(), dest.text())
        event.acceptProposedAction()


class SnippetCategoryDialog(QDialog):
    """Add/remove categories; click a category to see its snippets; drag a snippet onto a category to move it."""

    def __init__(self, workbench):
        super().__init__(workbench.win)
        self.wb = workbench
        self.setWindowTitle("Snippet Categories")
        self.resize(560, 380)
        config = Utils.loadConfig()
        self.mapping = dict(config.get("sqlSnippetCategory") or {})
        cats = list(config.get("sqlCategories") or [])
        if UNCATEGORIZED not in cats:
            cats = [UNCATEGORIZED] + [c for c in cats if c != UNCATEGORIZED]
        self.cats = cats

        root = QVBoxLayout(self)
        panes = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Categories"))
        self.catList = _CategoryDropList(self._moveSnippet, self)
        for c in self.cats:
            self.catList.addItem(c)
        self.catList.setCurrentRow(0)
        left.addWidget(self.catList, 1)
        btnRow = QHBoxLayout()
        self.btnAdd = QPushButton("Add")
        self.btnRemove = QPushButton("Remove")
        btnRow.addWidget(self.btnAdd)
        btnRow.addWidget(self.btnRemove)
        left.addLayout(btnRow)

        right = QVBoxLayout()
        self.snipLabel = QLabel("Snippets")
        right.addWidget(self.snipLabel)
        self.snipList = QListWidget(self)
        self.snipList.setDragEnabled(True)
        self.snipList.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.snipList.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.snipList.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.snipList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.snipList.customContextMenuRequested.connect(self._snippetMenu)
        right.addWidget(self.snipList, 1)
        hint = QLabel("Drag a snippet onto a category to move it.")
        hint.setWordWrap(True)
        right.addWidget(hint)

        panes.addLayout(left, 1)
        panes.addLayout(right, 2)
        root.addLayout(panes, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.catList.currentItemChanged.connect(lambda *_args: self._fillSnippets())
        self.catList.currentItemChanged.connect(lambda *_args: self._syncRemoveEnabled())
        self.btnAdd.clicked.connect(self._addCat)
        self.btnRemove.clicked.connect(self._removeCat)
        self._fillSnippets()
        self._syncRemoveEnabled()

    def _syncRemoveEnabled(self):
        it = self.catList.currentItem()
        self.btnRemove.setEnabled(it is not None and it.text() != UNCATEGORIZED)

    def _snippetNames(self):
        sqlDir = Utils.getSqlSnippetDir()
        names = []
        if os.path.isdir(sqlDir):
            for file in os.listdir(sqlDir):
                if file.endswith(".sql"):
                    names.append(file[:-4])
        return sorted(names, key=lambda s: s.lower())

    def _catOf(self, name):
        return self.mapping.get(name) or UNCATEGORIZED

    def _fillSnippets(self):
        it = self.catList.currentItem()
        cat = it.text() if it is not None else UNCATEGORIZED
        self.snipLabel.setText(f"Snippets in {cat}")
        self.snipList.clear()
        for name in self._snippetNames():
            if self._catOf(name) == cat:
                self.snipList.addItem(name)

    def _snippetMenu(self, pos):
        item = self.snipList.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        moveMenu = menu.addMenu("Move to")
        current = self._catOf(item.text())
        for i in range(self.catList.count()):
            cat = self.catList.item(i).text()
            act = moveMenu.addAction(cat)
            act.setEnabled(cat != current)
            act.triggered.connect(
                lambda _c=False, n=item.text(), k=cat: self._moveSnippet(n, k)
            )
        actDelete = menu.addAction("Delete")
        chosen = menu.exec(self.snipList.mapToGlobal(pos))
        if chosen == actDelete:
            self._deleteSnippet(item.text())

    def _deleteSnippet(self, name):
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Snippet", f"Delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.wb.deleteSnippetByName(name, confirm=False):
            self._fillSnippets()

    def _moveSnippet(self, snippetName, category):
        if not snippetName or not category:
            return
        self.mapping[snippetName] = category
        self._save()
        self._fillSnippets()
        if Config.debug:
            Logic.logMessage("DEBUG", f"Snippet {snippetName!r} → {category}")

    def _addCat(self):
        name, ok = QInputDialog.getText(self, "Add category", "Name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        existing = [self.catList.item(i).text() for i in range(self.catList.count())]
        if name in existing:
            QMessageBox.information(self, "Categories", "That category already exists.")
            return
        self.catList.addItem(name)
        self.cats.append(name)
        self._save()
        self.catList.setCurrentRow(self.catList.count() - 1)

    def _removeCat(self):
        it = self.catList.currentItem()
        if it is None or it.text() == UNCATEGORIZED:
            return
        cat = it.text()
        for name, mapped in list(self.mapping.items()):
            if mapped == cat:
                self.mapping[name] = UNCATEGORIZED
        self.catList.takeItem(self.catList.row(it))
        self.cats = [self.catList.item(i).text() for i in range(self.catList.count())]
        self._save()
        self.catList.setCurrentRow(0)
        self._fillSnippets()

    def _save(self):
        cats = [self.catList.item(i).text() for i in range(self.catList.count())]
        if UNCATEGORIZED not in cats:
            cats = [UNCATEGORIZED] + cats
        config = Utils.loadConfig()
        config["sqlCategories"] = cats
        config["sqlSnippetCategory"] = dict(self.mapping)
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            Logic.logException("SnippetCategoryDialog: save failed", e)

    def accept(self):
        self._save()
        super().accept()

    def reject(self):
        self._save()
        super().reject()


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
        # No solid-bar stylesheet — handle paints tab/window color + center dots.
        mainSplitter.setChildrenCollapsible(True)
        snippetPanel.setMinimumWidth(0)
        mainSplitter.addWidget(leftWidget)
        mainSplitter.addWidget(snippetPanel)
        # setCollapsible indexes are valid only after widgets are added
        if mainSplitter.count() > 0:
            mainSplitter.setCollapsible(0, False)
        if mainSplitter.count() > 1:
            mainSplitter.setCollapsible(1, True)
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
        handle = mainSplitter.handle(1)
        if handle is not None:
            handle.setToolTip("Double-click to collapse or expand SQL quick looks")
        self._applySnippetHidden(bool(Utils.loadConfig().get("sqlSnippetsHidden", False)))
        self._stylePanes()

    def _stylePanes(self, *widgets):
        targets = widgets or (
            getattr(self, "pteSQL", None),
            getattr(self, "sqlTable", None),
            getattr(self, "listSnippets", None),
            getattr(self, "snippetPanel", None),
        )
        for w in targets:
            Utils.applyBasePaneBackground(w)

    def _newResultTabs(self, parent):
        tabs = ResultTabWidget(parent)
        bar = tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(
            lambda pos, t=tabs: self._resultTabMenu(t, pos)
        )
        bar.pinClicked.connect(lambda i, t=tabs: self._togglePinAt(t, i))
        tabs.currentChanged.connect(lambda _i, t=tabs: self._onResultTabChanged(t))
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
        """Table on the focused result tab of the active worksheet (CSV export)."""
        tabs = self.currentResultTabs()
        if tabs is None:
            return self.win.sqlTable
        w = tabs.currentWidget()
        if isinstance(w, QTableWidget):
            return w
        return self.win.sqlTable

    def _onResultTabChanged(self, tabs):
        if tabs is not self.currentResultTabs():
            return
        w = tabs.currentWidget()
        if isinstance(w, QTableWidget):
            self.win.sqlTable = w

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
        self._stylePanes(editor)
        self._setWorksheetDatabase(editor, self.currentDatabase())
        name = f"Query {self._wsSeq}"
        idx = self.worksheetTabs.addTab(editor, name)
        resultTabs = self._newResultTabs(self.win.tabSQL)
        table = QTableWidget(self.win.tabSQL)
        table.setSortingEnabled(True)
        table.horizontalHeader().setStretchLastSection(False)
        self._stylePanes(table)
        resultTabs.addTab(self._wrapResult(table, pinned=False), "Result")
        resultTabs.tabBar().setTabData(0, {"pinned": False})
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
                tabs.tabBar().update()
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
        tabs.tabBar().update()

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
        self._stylePanes(table)
        idx = tabs.addTab(self._wrapResult(table, pinned=False), "Result")
        tabs.tabBar().setTabData(idx, {"pinned": False})
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
            tabs.tabBar().update()
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
        try:
            dlg.exec()
        finally:
            Utils.resetStyledButtonHover(self.btnHistory)

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
        try:
            SnippetCategoryDialog(self).exec()
        finally:
            Utils.resetStyledButtonHover(self.btnCatagory)
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
            assigned = False
            for name in namesOnDisk:
                if not mapping.get(name):
                    mapping[name] = UNCATEGORIZED
                    assigned = True
            if assigned:
                config["sqlSnippetCategory"] = mapping
                cats = list(config.get("sqlCategories") or [])
                if UNCATEGORIZED not in cats:
                    config["sqlCategories"] = [UNCATEGORIZED] + [
                        c for c in cats if c != UNCATEGORIZED
                    ]
                try:
                    with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=2)
                except Exception:
                    pass
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
        try:
            name = Utils.sqlSnippetStem(name)
            filePath = Utils.sqlSnippetPath(name)
        except ValueError:
            QMessageBox.warning(self.win, "Save Snippet", "Snippet name cannot contain path characters.")
            return
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
        try:
            name = Utils.sqlSnippetStem(item.text())
            filePath = Utils.sqlSnippetPath(name)
        except ValueError:
            return
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
        self.deleteSnippetByName(selected.text(), confirm=True)

    def deleteSnippetByName(self, name, confirm=True):
        name = (name or "").strip()
        if not name:
            return False
        if confirm:
            reply = QMessageBox.question(
                self.win, "Delete Snippet", f"Delete '{name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        try:
            name = Utils.sqlSnippetStem(name)
            filePath = Utils.sqlSnippetPath(name)
        except ValueError:
            return False
        if os.path.exists(filePath):
            os.remove(filePath)
        config = Utils.loadConfig()
        mapping = dict(config.get("sqlSnippetCategory") or {})
        mapping.pop(name, None)
        config["sqlSnippetCategory"] = mapping
        order = list(config.get("sqlSnippetOrder") or [])
        if name in order:
            order = [n for n in order if n != name]
            config["sqlSnippetOrder"] = order
        try:
            with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception:
            pass
        if self.listSnippets is not None:
            for i in range(self.listSnippets.count()):
                item = self.listSnippets.item(i)
                if item is not None and item.text() == name:
                    self.listSnippets.takeItem(i)
                    break
        self.win.saveSnippetOrder()
        return True

    def refresh(self):
        """Called when the SQL tab is shown."""
        config = Utils.loadConfig()
        if self.sqlSplitter is not None and "sqlVerticalSizes" in config:
            self.sqlSplitter.setSizes(config["sqlVerticalSizes"])
        if self.mainSplitter is not None and "sqlHorizontalSizes" in config:
            self._snippetSizes = config["sqlHorizontalSizes"]
            if not bool(config.get("sqlSnippetsHidden", False)):
                self.mainSplitter.setSizes(config["sqlHorizontalSizes"])
        if self.cbDatabase is not None:
            Utils.loadDatabase(self.cbDatabase, "sql")
            self.cbDatabase.setMinimumWidth(200)
            self.cbDatabase.adjustSize()
            editor = self.currentEditor()
            if editor is not None and not self._worksheetDatabase(editor):
                self._setWorksheetDatabase(editor, self.currentDatabase())
        self._loadCategories()
