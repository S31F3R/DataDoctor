# HeaderFilter.py
# Filter icon on Data Dictionary / Search headers (siteID, database) and
# SQL Query Builder result columns (dynamic: combo if ≤10 uniques, else text).
# Click → filter popup. Right-click → clear that filter.

from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, QPoint, QEvent
from PyQt6.QtWidgets import QPushButton, QMenu, QLineEdit, QListWidget, QListWidgetItem
from PyQt6.QtGui import QFontMetrics

from core import Utils

INPUT_COLUMNS = frozenset({"siteid"})
COMBO_MAX_UNIQUES = 10

ICON_PX = 16
ICON_MARGIN = 3


class HeaderFilterBar(QObject):
    """
    Overlay Filter/Filtered buttons on named header sections.
    `onChange` is called whenever a filter value changes (re-run table filter).

    dynamic=True (SQL results): a button on every column. Combobox when that
    column has ≤10 unique values, otherwise a text box. Reset per extract.
    """

    def __init__(self, table, columnNames=None, onChange=None, parent=None, dynamic=False):
        super().__init__(parent if parent is not None else table)
        self.table = table
        self.onChange = onChange
        self.dynamic = bool(dynamic)
        self.columnNames = tuple(columnNames or ())
        self.values = {}
        self._buttons = {}
        self._combo = None
        self._editName = None
        self._keys = []
        self._inputKeys = set()
        header = table.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionResized.connect(self.reposition)
        header.sectionMoved.connect(lambda *_: self.reposition())
        header.geometriesChanged.connect(self.reposition)
        hbar = table.horizontalScrollBar()
        if hbar is not None:
            hbar.valueChanged.connect(lambda *_: self.reposition())
        header.viewport().installEventFilter(self)
        header.installEventFilter(self)
        self._rebuildButtons()

    def _keysForTable(self):
        if self.dynamic:
            n = self.table.columnCount() if self.table is not None else 0
            return list(range(n))
        return list(self.columnNames)

    def _labelFor(self, key) -> str:
        if isinstance(key, int):
            if self.table is None or key < 0 or key >= self.table.columnCount():
                return str(key)
            h = self.table.horizontalHeaderItem(key)
            return h.text().strip() if h is not None and h.text() else f"col{key}"
        return str(key)

    def _rebuildButtons(self):
        for btn in self._buttons.values():
            try:
                btn.hide()
                btn.deleteLater()
            except RuntimeError:
                pass
        self._buttons = {}
        self._keys = self._keysForTable()
        old = self.values
        self.values = {k: old.get(k) if not self.dynamic else None for k in self._keys}
        self._inputKeys = set()
        if self.dynamic:
            for key in self._keys:
                col = self._colIndex(key)
                if len(self._uniqueValues(col)) > COMBO_MAX_UNIQUES:
                    self._inputKeys.add(key)
        if self.table is None:
            return
        vp = self.table.horizontalHeader().viewport()
        for key in self._keys:
            label = self._labelFor(key)
            btn = QPushButton(vp)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Filter {label}")
            btn.setFixedSize(ICON_PX, ICON_PX)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.clicked.connect(lambda checked=False, k=key: self._openFilter(k))
            btn.customContextMenuRequested.connect(
                lambda pos, k=key: self._rightClick(k, pos)
            )
            self._buttons[key] = btn
            self._setIcon(key)
        self._padColumns()
        self.reposition()

    def reset(self):
        """SQL extract: drop filters and rebuild buttons for the current headers."""
        self._combo = None
        self._editName = None
        self._rebuildButtons()
        self._fire()

    def _padColumns(self):
        if self.table is None:
            return
        header = self.table.horizontalHeader()
        need = ICON_PX + ICON_MARGIN * 2 + 48
        for key in self._keys:
            col = self._colIndex(key)
            if col < 0:
                continue
            if header.sectionSize(col) < need:
                header.resizeSection(col, need)

    def _isInput(self, key) -> bool:
        if self.dynamic:
            return key in self._inputKeys
        name = key if isinstance(key, str) else self._labelFor(key)
        return (name or "").lower() in INPUT_COLUMNS

    def activeEquals(self) -> dict:
        """Exact matches (database combobox)."""
        out = {}
        for n, v in self.values.items():
            if not v or self._isInput(n):
                continue
            if isinstance(n, str):
                out[n] = v
        return out

    def activeContains(self) -> dict:
        """Substring matches (typed siteID)."""
        out = {}
        for n, v in self.values.items():
            if not v or not self._isInput(n):
                continue
            if isinstance(n, str):
                out[n] = v
        return out

    def rebuild(self):
        """After dictionary save: drop stale combo selections, keep typed text."""
        for name in list(self._keys):
            current = self.values.get(name)
            if not current or self._isInput(name):
                continue
            col = self._colIndex(name)
            if col < 0 or current not in self._uniqueValues(col):
                self.values[name] = None
                self._setIcon(name)
        self.reposition()
        self._fire()

    def eventFilter(self, obj, event):
        if obj is self._combo and isinstance(obj, QLineEdit):
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                obj.setProperty("ddSkipApply", True)
                self._combo = None
                obj.hide()
                obj.deleteLater()
                return True
            if event.type() == QEvent.Type.Hide and self._combo is obj:
                name = self._editName
                if name is None:
                    name = "siteID"
                self._applyInput(name, obj)
        if event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        ):
            self.reposition()
        return super().eventFilter(obj, event)

    def _colIndex(self, name) -> int:
        table = self.table
        if table is None:
            return -1
        if isinstance(name, int):
            return name if 0 <= name < table.columnCount() else -1
        target = (name or "").strip().lower()
        for c in range(table.columnCount()):
            h = table.horizontalHeaderItem(c)
            if h is not None and h.text().strip().lower() == target:
                return c
        return -1

    def _uniqueValues(self, col) -> list:
        table = self.table
        seen = []
        found = set()
        if table is None or col < 0:
            return seen
        for r in range(table.rowCount()):
            item = table.item(r, col)
            text = item.text().strip() if item is not None and item.text() else ""
            if not text or text in found:
                continue
            found.add(text)
            seen.append(text)
        seen.sort(key=lambda s: s.lower())
        return seen

    def _setIcon(self, name):
        btn = self._buttons.get(name)
        if btn is None:
            return
        active = bool(self.values.get(name))
        Utils.buttonStyle(btn, "Filtered" if active else "Filter", ICON_PX)
        label = self._labelFor(name)
        btn.setToolTip(
            f"Filter {label}: {self.values[name]}" if active else f"Filter {label}"
        )

    def reposition(self):
        table = self.table
        if table is None:
            return
        header = table.horizontalHeader()
        vp = header.viewport()
        h = header.height()
        for name, btn in self._buttons.items():
            col = self._colIndex(name)
            if col < 0:
                btn.hide()
                continue
            x = header.sectionViewportPosition(col)
            w = header.sectionSize(col)
            btn.setParent(vp)
            bx = x + max(0, w - ICON_PX - ICON_MARGIN)
            by = max(0, (h - ICON_PX) // 2)
            btn.setGeometry(bx, by, ICON_PX, ICON_PX)
            btn.show()
            btn.raise_()

    def _openFilter(self, name):
        if self._isInput(name):
            self._openInput(name)
        else:
            self._openList(name)

    def _popupPos(self, name):
        btn = self._buttons[name]
        return btn.mapToGlobal(QPoint(0, btn.height()))

    def _openInput(self, name):
        edit = QLineEdit(self.table.window())
        edit.setWindowFlags(Qt.WindowType.Popup)
        edit.setPlaceholderText(f"Filter {self._labelFor(name)}…")
        edit.setText(self.values.get(name) or "")
        edit.setClearButtonEnabled(True)
        edit.setMinimumWidth(180)
        edit.move(self._popupPos(name))
        edit.returnPressed.connect(lambda n=name, e=edit: self._applyInput(n, e))
        edit.installEventFilter(self)
        self._editName = name
        self._combo = edit
        edit.show()
        edit.setFocus(Qt.FocusReason.PopupFocusReason)
        edit.selectAll()

    def _applyInput(self, name, edit):
        if edit.property("ddApplied"):
            return
        if edit.property("ddSkipApply"):
            return
        edit.setProperty("ddApplied", True)
        text = (edit.text() or "").strip()
        self.values[name] = text or None
        self._setIcon(name)
        self._combo = None
        self._editName = None
        edit.hide()
        edit.deleteLater()
        self._fire()

    def _openList(self, name):
        col = self._colIndex(name)
        if col < 0:
            return
        values = self._uniqueValues(col)
        lst = QListWidget(self.table.window())
        lst.setWindowFlags(Qt.WindowType.Popup)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        current = self.values.get(name) or ""
        allItem = QListWidgetItem("(All)")
        allItem.setData(Qt.ItemDataRole.UserRole, "")
        lst.addItem(allItem)
        pick = allItem
        for v in values:
            it = QListWidgetItem(v)
            it.setData(Qt.ItemDataRole.UserRole, v)
            lst.addItem(it)
            if v == current:
                pick = it
        lst.setCurrentItem(pick)
        fm = QFontMetrics(lst.font())
        w = max(200, fm.horizontalAdvance("(All)") + 24)
        for v in values[:80]:
            w = max(w, fm.horizontalAdvance(v) + 24)
        rows = min(lst.count(), 12)
        lst.resize(w, max(lst.sizeHintForRow(0) * rows + 4, 80))
        lst.move(self._popupPos(name))
        lst.itemClicked.connect(lambda item, n=name, wdg=lst: self._pickedList(n, wdg, item))
        lst.show()
        lst.setFocus(Qt.FocusReason.PopupFocusReason)
        self._combo = lst

    def _pickedList(self, name, lst, item):
        text = ""
        if item is not None:
            data = item.data(Qt.ItemDataRole.UserRole)
            text = ("" if data is None else str(data)).strip()
        self.values[name] = text or None
        self._setIcon(name)
        lst.hide()
        lst.deleteLater()
        self._combo = None
        self._fire()

    def _rightClick(self, name, pos):
        if not self.values.get(name):
            return
        menu = QMenu(self._buttons[name])
        act = menu.addAction("Clear filter")
        chosen = menu.exec(self._buttons[name].mapToGlobal(pos))
        if chosen is act:
            self.values[name] = None
            self._setIcon(name)
            self._fire()

    def _applyRowFilter(self):
        table = self.table
        if table is None or not self.dynamic:
            return
        for r in range(table.rowCount()):
            hide = False
            for key, val in self.values.items():
                if not val:
                    continue
                col = self._colIndex(key)
                if col < 0:
                    continue
                item = table.item(r, col)
                text = item.text().strip() if item is not None and item.text() else ""
                if self._isInput(key):
                    if val.lower() not in text.lower():
                        hide = True
                        break
                elif text != val:
                    hide = True
                    break
            table.setRowHidden(r, hide)

    def _fire(self):
        if self.dynamic:
            self._applyRowFilter()
        if self.onChange is not None:
            self.onChange()
