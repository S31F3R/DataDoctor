# HeaderFilter.py
# Filter icon on Data Dictionary / Search headers (siteID, database).
# Click → combobox of values in the table. Right-click → clear that filter.

from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, QPoint, QEvent
from PyQt6.QtWidgets import QPushButton, QComboBox, QMenu

from core import Utils

ICON_PX = 16
ICON_MARGIN = 3


class HeaderFilterBar(QObject):
    """
    Overlay Filter/Filtered buttons on named header sections.
    `onChange` is called whenever a filter value changes (re-run table filter).
    """

    def __init__(self, table, columnNames, onChange=None, parent=None):
        super().__init__(parent if parent is not None else table)
        self.table = table
        self.columnNames = tuple(columnNames)
        self.onChange = onChange
        self.values = {n: None for n in self.columnNames}  # None = all
        self._buttons = {}
        self._combo = None
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
        vp = header.viewport()
        for name in self.columnNames:
            btn = QPushButton(vp)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Filter {name}")
            btn.setFixedSize(ICON_PX, ICON_PX)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.clicked.connect(lambda checked=False, n=name: self._openCombo(n))
            btn.customContextMenuRequested.connect(
                lambda pos, n=name: self._rightClick(n, pos)
            )
            self._buttons[name] = btn
            self._setIcon(name)
        self._padColumns()
        self.reposition()

    def _padColumns(self):
        header = self.table.horizontalHeader()
        need = ICON_PX + ICON_MARGIN * 2 + 48
        for name in self.columnNames:
            col = self._colIndex(name)
            if col < 0:
                continue
            if header.sectionSize(col) < need:
                header.resizeSection(col, need)

    def activeEquals(self) -> dict:
        """headerName → exact cell text for active filters."""
        return {n: v for n, v in self.values.items() if v}

    def rebuild(self):
        """After dictionary save: drop stale selections, refresh icons."""
        for name in self.columnNames:
            current = self.values.get(name)
            if not current:
                continue
            col = self._colIndex(name)
            if col < 0 or current not in self._uniqueValues(col):
                self.values[name] = None
                self._setIcon(name)
        self.reposition()
        self._fire()

    def eventFilter(self, obj, event):
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
        btn.setToolTip(
            f"Filter {name}: {self.values[name]}" if active else f"Filter {name}"
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

    def _openCombo(self, name):
        col = self._colIndex(name)
        if col < 0:
            return
        values = self._uniqueValues(col)
        combo = QComboBox(self.table.window())
        combo.setWindowFlags(Qt.WindowType.Popup)
        combo.setEditable(False)
        combo.setMaxVisibleItems(16)
        combo.addItem("(All)", "")
        current = self.values.get(name) or ""
        for v in values:
            combo.addItem(v, v)
        idx = combo.findData(current)
        combo.setCurrentIndex(max(0, idx))
        combo.activated.connect(lambda i, n=name, c=combo: self._picked(n, c, i))
        btn = self._buttons[name]
        gp = btn.mapToGlobal(QPoint(0, btn.height()))
        combo.setMinimumWidth(max(200, btn.width() + 120))
        combo.move(gp)
        combo.show()
        combo.showPopup()
        self._combo = combo

    def _picked(self, name, combo, index):
        data = combo.itemData(index)
        text = ("" if data is None else str(data)).strip()
        self.values[name] = text or None
        self._setIcon(name)
        combo.hide()
        combo.deleteLater()
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

    def _fire(self):
        if self.onChange is not None:
            self.onChange()
