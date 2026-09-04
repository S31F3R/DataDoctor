# FormulaUi.py
# Excel-like formula editing on the Data Query table: click-to-ref, fill handle.

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QEvent, QObject, QPoint
from PyQt6.QtGui import (
    QColor, QCursor, QPainter, QPen, QMouseEvent, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QLineEdit, QRubberBand, QStyledItemDelegate, QTableWidgetItem, QWidget,
    QAbstractItemDelegate, QToolTip, QApplication, QTextEdit,
)

from core import Config, Logic, Upload
from core.Formula import (
    FORMULA_KEY, ERR_VALUE, FUNCTIONS, FUNCTION_HELP,
    adjustFormula, colToLetters, evaluateFormula, formatFormulaResult,
    looksLikeFormula, parseCellRef,
)

HANDLE_PX = 7

_REF_COLORS_DARK = (
    QColor("#00E5FF"), QColor("#FF80AB"), QColor("#FFD54F"), QColor("#69F0AE"),
)
_REF_COLORS_LIGHT = (
    QColor("#0066CC"), QColor("#C2185B"), QColor("#E65100"), QColor("#2E7D32"),
)


def _refColors():
    app = QApplication.instance()
    dark = True
    if app is not None:
        pal = app.palette()
        dark = pal.color(pal.ColorRole.Window).lightness() < 128
    if Config.retroMode:
        return (QColor("#00FF00"), QColor("#00FFFF"), QColor("#FF00FF"), QColor("#FFFF00"))
    return _REF_COLORS_DARK if dark else _REF_COLORS_LIGHT


class FormulaEditor(QTextEdit):
    """Single-line editor that can color A1 tokens to match cell rings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(False)
        self.setAcceptRichText(False)
        self.document().setDocumentMargin(2)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText("" if text is None else str(text))

    def cursorPosition(self):
        return self.textCursor().position()

    def setCursorPosition(self, pos):
        cur = self.textCursor()
        n = max(0, min(int(pos), len(self.toPlainText())))
        cur.setPosition(n)
        self.setTextCursor(cur)

    def setAlignment(self, align):
        super().setAlignment(align)


class CellRefRing(QWidget):
    """Colored outline on a formula-pointed cell (Excel-style)."""

    def __init__(self, parent, color):
        super().__init__(parent)
        self.color = QColor(color)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(self.color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        painter.end()


def _itemFormula(item) -> str:
    user = Upload.getUserDict(item)
    f = user.get(FORMULA_KEY)
    return str(f).strip() if f else ""


def _setItemFormula(item, formula: str | None):
    user = Upload.getUserDict(item)
    if formula:
        user[FORMULA_KEY] = formula
    else:
        user.pop(FORMULA_KEY, None)
    Upload.setUserDict(item, user)


def _tableGetCell(table, col, row, origin, stack):
    if col < 0 or row < 0 or col >= table.columnCount() or row >= table.rowCount():
        raise ValueError("#REF!")
    item = table.item(row, col)
    if item is None:
        return ""
    formula = _itemFormula(item)
    if formula:
        key = (col, row)
        if key in stack:
            raise ValueError("#CYCLE!")
        stack.add(key)
        try:
            return evaluateFormula(
                formula,
                lambda c, r: _tableGetCell(table, c, r, origin, stack),
                col,
                row,
            )
        finally:
            stack.discard(key)
    return item.text() if item.text() is not None else ""


def evaluateOnTable(table, formula: str, col: int, row: int):
    stack = {(col, row)}
    return evaluateFormula(
        formula,
        lambda c, r: _tableGetCell(table, c, r, (col, row), stack),
        col,
        row,
    )


def applyCellInput(mainWindow, row: int, col: int, text: str, *, asFill=False, skipUndo=False):
    """
    Set a cell from typed/pasted/filled text. Formulas starting with '=' are
    stored and the display becomes the computed value (upload uses that).
    """
    table = mainWindow.mainTable if mainWindow is not None else None
    if table is None:
        return False
    if Upload.columnIsLocked(mainWindow, col):
        return False
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem("")
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, col, item)
    if not (item.flags() & Qt.ItemFlag.ItemIsEditable):
        return False
    raw = "" if text is None else str(text).strip()
    oldText = item.text() if item is not None else ""
    oldFormula = _itemFormula(item)
    oldBg, oldFg = Upload.captureItemColors(item)
    _, oldEdit = Upload.getEditState(item)
    if looksLikeFormula(raw):
        try:
            result = evaluateOnTable(table, raw, col, row)
            display = formatFormulaResult(result)
        except ValueError as e:
            display = str(e) or ERR_VALUE
        _setItemFormula(item, raw)
        if item.text() != display:
            item.setText(display)
        # Formula replaces queried QAQC/overlay paint; custom cols stay unflagged
        metas = getattr(mainWindow, "columnMetadata", None) or []
        meta = metas[col] if col < len(metas) else {}
        if (meta or {}).get("type") != "custom":
            Upload.applyColors(item, None, None)
        if not skipUndo:
            from core import Undo
            newBg, newFg = Upload.captureItemColors(item)
            _, newEdit = Upload.getEditState(item)
            Undo.pushCellEdit(
                mainWindow, row, col, oldText, oldFormula, item.text(), raw,
                oldBg=oldBg, oldFg=oldFg, newBg=newBg, newFg=newFg,
                oldEdit=oldEdit, newEdit=newEdit,
            )
        return True
    _setItemFormula(item, None)
    if item.text() != raw:
        item.setText(raw)
    if not skipUndo:
        from core import Undo
        newBg, newFg = Upload.captureItemColors(item)
        _, newEdit = Upload.getEditState(item)
        Undo.pushCellEdit(
            mainWindow, row, col, oldText, oldFormula, item.text(), None,
            oldBg=oldBg, oldFg=oldFg, newBg=newBg, newFg=newFg,
            oldEdit=oldEdit, newEdit=newEdit,
        )
    return True


def recalculateAll(mainWindow):
    """Re-run every stored formula so dependents update after an edit."""
    table = mainWindow.mainTable if mainWindow is not None else None
    if table is None:
        return
    table.blockSignals(True)
    changed = []
    try:
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                formula = _itemFormula(item)
                if not formula:
                    continue
                try:
                    display = formatFormulaResult(evaluateOnTable(table, formula, c, r))
                except ValueError as e:
                    display = str(e) or ERR_VALUE
                if item.text() != display:
                    item.setText(display)
                    changed.append(item)
    finally:
        table.blockSignals(False)
    for item in changed:
        Upload.onItemChanged(mainWindow, item)


def formulaMayEdit(mainWindow, col: int) -> bool:
    """Formulas on editable cells (custom columns even on public queries)."""
    if mainWindow is None:
        return False
    return not Upload.columnIsLocked(mainWindow, col)


class FormulaDelegate(QStyledItemDelegate):
    def __init__(self, mainWindow):
        super().__init__(mainWindow)
        self.mainWindow = mainWindow
        self._editor = None
        self._editIndex = None

    def createEditor(self, parent, option, index):
        editor = FormulaEditor(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            from PyQt6.QtWidgets import QFrame
            editor.setFrameShape(QFrame.Shape.NoFrame)
        except Exception:
            pass
        editor.installEventFilter(self)
        editor.textChanged.connect(self._onEditorTextChanged)
        try:
            h = option.rect.height() if option is not None else 24
            editor.setFixedHeight(max(h, 22))
        except Exception:
            pass
        self._editor = editor
        self._editIndex = index
        table = self.mainWindow.mainTable
        if table is not None:
            table._formulaPointing = True
        return editor

    def destroyEditor(self, editor, index):
        table = self.mainWindow.mainTable
        if table is not None:
            table._formulaPointing = False
        self._clearRefRings()
        QToolTip.hideText()
        self._editor = None
        self._editIndex = None
        super().destroyEditor(editor, index)
        # Qt copies the editor palette onto items with no explicit brush.
        # Re-apply baseline / edit / upload colors so a no-op double-click
        # does not leave a black cell.
        if table is not None and index is not None and index.isValid():
            try:
                Upload.reapplyItemStyle(
                    self.mainWindow, table.item(index.row(), index.column())
                )
            except Exception:
                pass

    def setEditorData(self, editor, index):
        table = self.mainWindow.mainTable
        item = table.item(index.row(), index.column()) if table is not None else None
        formula = _itemFormula(item)
        editor.setText(formula if formula else (item.text() if item is not None else ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        applyCellInput(self.mainWindow, index.row(), index.column(), editor.text())
        recalculateAll(self.mainWindow)

    def isPointing(self) -> bool:
        """True while the in-cell editor is a formula (`=…`)."""
        editor = self._editor
        if editor is None:
            return False
        return (editor.text() or "").strip().startswith("=")

    def eventFilter(self, obj, event):
        # Qt commits/closes the editor on FocusOut before the table sees the
        # click. Swallow that when the click is still on the grid so pointing
        # at another cell can insert A1 instead of selecting it.
        if obj is self._editor and event.type() == QEvent.Type.FocusOut:
            if self.isPointing() and self._clickIsOnTable():
                return True
        if obj is self._editor and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._clearRefRings()
                table = self.mainWindow.mainTable if self.mainWindow is not None else None
                if table is not None:
                    table.closeEditor(self._editor, QAbstractItemDelegate.EndEditHint.RevertModelCache)
                return True
            if key == Qt.Key.Key_Tab:
                if self._tabComplete(self._editor):
                    return True
        return super().eventFilter(obj, event)

    def _tabComplete(self, editor) -> bool:
        if editor is None:
            return False
        text = editor.text() or ""
        if not text.strip().startswith("="):
            return False
        pos = editor.cursorPosition()
        i = pos
        while i > 1 and text[i - 1].isalpha():
            i -= 1
        prefix = text[i:pos]
        if not prefix:
            return False
        names = [n for n in FUNCTIONS if n.startswith(prefix.upper())]
        if not names:
            return False
        names.sort()
        chosen = names[0]
        if len(names) > 1:
            common = prefix.upper()
            for chs in zip(*names):
                if len(set(chs)) == 1:
                    common += chs[0]
                else:
                    break
            if len(common) > len(prefix):
                chosen = common
            # unique name still gets "("
            if chosen not in FUNCTIONS:
                ins = chosen[len(prefix):]
                editor.setText(text[:pos] + ins + text[pos:])
                editor.setCursorPosition(pos + len(ins))
                self._hintFunction(editor)
                return True
        ins = chosen[len(prefix):] + ("(" if chosen in FUNCTIONS else "")
        editor.setText(text[:i] + chosen + ("(" if chosen in FUNCTIONS else "") + text[pos:])
        editor.setCursorPosition(i + len(chosen) + (1 if chosen in FUNCTIONS else 0))
        self._hintFunction(editor)
        return True

    def _onEditorTextChanged(self, _text=""):
        self._hintFunction(self._editor)
        self._syncRefRings()

    def _hintFunction(self, editor):
        if editor is None:
            return
        text = editor.text() or ""
        pos = editor.cursorPosition()
        chunk = text[:pos]
        m = re.search(r"([A-Za-z]+)\s*\([^)]*$", chunk)
        if not m:
            QToolTip.hideText()
            return
        name = m.group(1).upper()
        tip = None
        for sig, helpText in FUNCTION_HELP:
            if sig.upper().startswith(name + "(") or sig.upper().startswith(name + " "):
                tip = f"{sig}  —  {helpText}"
                break
            if sig.upper().startswith(name):
                tip = f"{sig}  —  {helpText}"
                break
        if not tip:
            QToolTip.hideText()
            return
        QToolTip.showText(
            editor.mapToGlobal(QPoint(8, editor.height() + 2)),
            tip,
            editor,
        )

    def _clearRefRings(self):
        table = self.mainWindow.mainTable if self.mainWindow is not None else None
        rings = getattr(table, "_formulaRefRings", None) if table is not None else None
        if rings:
            for w in rings:
                try:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
                except Exception:
                    pass
        if table is not None:
            table._formulaRefRings = []

    def _syncRefRings(self):
        table = self.mainWindow.mainTable if self.mainWindow is not None else None
        editor = self._editor
        self._clearRefRings()
        if table is None or editor is None or not self.isPointing():
            return
        vp = table.viewport()
        colors = _refColors()
        seen = {}
        idx = 0
        text = editor.text() or ""
        for m in re.finditer(r"\$?[A-Za-z]+\$?\d+", text):
            parsed = parseCellRef(m.group(0))
            if parsed is None:
                continue
            col, row, _ac, _ar = parsed
            key = (col, row)
            if key in seen:
                color = seen[key]
            else:
                color = colors[idx % len(colors)]
                seen[key] = color
                idx += 1
            if col < 0 or row < 0 or col >= table.columnCount() or row >= table.rowCount():
                continue
            rect = table.visualRect(table.model().index(row, col))
            if rect.isNull():
                continue
            ring = CellRefRing(vp, color)
            ring.setGeometry(rect)
            ring.show()
            ring.raise_()
            table._formulaRefRings.append(ring)
        # Color matching tokens in the editor (QLineEdit palette per-char is limited;
        # the cell rings carry the identity. Tint the whole editor when pointing.)
        if isinstance(editor, FormulaEditor):
            pal = editor.palette()
            baseFmt = QTextCharFormat()
            baseFmt.setForeground(pal.color(pal.ColorRole.Text))
            doc = editor.document()
            pos = editor.cursorPosition()
            editor.blockSignals(True)
            try:
                cur = QTextCursor(doc)
                cur.select(QTextCursor.SelectionType.Document)
                cur.setCharFormat(baseFmt)
                for m in re.finditer(r"\$?[A-Za-z]+\$?\d+", text):
                    parsed = parseCellRef(m.group(0))
                    if parsed is None:
                        continue
                    key = (parsed[0], parsed[1])
                    color = seen.get(key)
                    if color is None:
                        continue
                    fmt = QTextCharFormat()
                    fmt.setForeground(color)
                    cur.setPosition(m.start())
                    cur.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
                    cur.mergeCharFormat(fmt)
                editor.setCursorPosition(pos)
            finally:
                editor.blockSignals(False)

    def _clickIsOnTable(self) -> bool:
        table = self.mainWindow.mainTable if self.mainWindow is not None else None
        if table is None:
            return False
        vp = table.viewport()
        try:
            pos = vp.mapFromGlobal(QCursor.pos())
        except Exception:
            return False
        return vp.rect().contains(pos)

    def insertRef(self, col: int, row: int, asRange=False):
        editor = self._editor
        if editor is None:
            return False
        text = editor.text() or ""
        if not text.strip().startswith("="):
            return False
        ref = f"{colToLetters(col)}{row + 1}"
        cursor = editor.cursorPosition()
        prefix = text[:cursor]
        suffix = text[cursor:]
        if asRange and re.search(r"\$?[A-Za-z]+\$?\d+$", prefix):
            if not prefix.endswith(":"):
                ref = ":" + ref
        new = prefix + ref + suffix
        editor.setText(new)
        editor.setCursorPosition(len(prefix) + len(ref))
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._syncRefRings()
        return True


class FillHandle(QWidget):
    """Small square at the bottom-right of the selection (Excel fill handle)."""

    def __init__(self, owner, parent):
        super().__init__(parent)
        self._owner = owner
        self.setFixedSize(HANDLE_PX + 2, HANDLE_PX + 2)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("Drag to fill (Excel-style)")
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        if Config.retroMode:
            fill, edge = QColor("#00FF00"), QColor("#003300")
        else:
            fill, edge = QColor(0x1B, 0x5E, 0x20), QColor(255, 255, 255)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        painter.drawRect(1, 1, HANDLE_PX, HANDLE_PX)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner.startFillDrag()
            event.accept()
            return
        super().mousePressEvent(event)


class FormulaTableFilter(QObject):
    """
    Viewport: click-to-insert A1 while a formula editor is open.
    Fill-handle widget + rubber-band drag-copy with $ lock.
    """

    def __init__(self, mainWindow):
        super().__init__(mainWindow)
        self.mainWindow = mainWindow
        self._drag = None
        table = self._table()
        vp = table.viewport() if table is not None else None
        self._handle = FillHandle(self, vp) if vp is not None else None
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, vp) if vp is not None else None
        if table is not None:
            table.itemSelectionChanged.connect(self.repositionHandle)
            hbar = table.horizontalScrollBar()
            vbar = table.verticalScrollBar()
            if hbar is not None:
                hbar.valueChanged.connect(lambda _v: self.repositionHandle())
            if vbar is not None:
                vbar.valueChanged.connect(lambda _v: self.repositionHandle())

    def _table(self):
        return getattr(self.mainWindow, "mainTable", None)

    def _delegate(self) -> FormulaDelegate | None:
        table = self._table()
        if table is None:
            return None
        d = table.itemDelegate()
        return d if isinstance(d, FormulaDelegate) else None

    def repositionHandle(self):
        table = self._table()
        handle = self._handle
        if table is None or handle is None:
            return
        if self._drag is not None:
            handle.hide()
            return
        bounds = Upload._selectionBounds(table)
        if bounds is None:
            handle.hide()
            return
        _minR, maxR, _minC, maxC = bounds
        if not formulaMayEdit(self.mainWindow, maxC):
            handle.hide()
            return
        rect = table.visualRect(table.model().index(maxR, maxC))
        if rect.isNull() or not rect.isValid():
            handle.hide()
            return
        handle.move(rect.right() - HANDLE_PX // 2, rect.bottom() - HANDLE_PX // 2)
        handle.show()
        handle.raise_()

    def startFillDrag(self):
        table = self._table()
        bounds = Upload._selectionBounds(table) if table is not None else None
        if bounds is None:
            return
        self._drag = {
            "minR": bounds[0],
            "maxR": bounds[1],
            "minC": bounds[2],
            "maxC": bounds[3],
            "endR": bounds[1],
            "endC": bounds[3],
        }
        if self._handle is not None:
            self._handle.hide()
        self._updateBand()
        if table is not None:
            table.viewport().grabMouse()

    def _updateBand(self):
        table = self._table()
        if table is None or self._band is None or self._drag is None:
            return
        minR = min(self._drag["minR"], self._drag["endR"])
        maxR = max(self._drag["maxR"], self._drag["endR"])
        minC = min(self._drag["minC"], self._drag["endC"])
        maxC = max(self._drag["maxC"], self._drag["endC"])
        tl = table.visualRect(table.model().index(minR, minC))
        br = table.visualRect(table.model().index(maxR, maxC))
        self._band.setGeometry(tl.united(br))
        self._band.show()

    def eventFilter(self, obj, event):
        if getattr(Logic, "appIsQuitting", False):
            return False
        table = self._table()
        if table is None:
            return super().eventFilter(obj, event)
        et = event.type()
        try:
            viewport = table.viewport()
        except RuntimeError:
            return False

        if et == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                d = self._delegate()
                if d is not None and d.isPointing():
                    if obj is viewport:
                        pos = event.position().toPoint()
                    elif obj is table:
                        pos = viewport.mapFrom(table, event.position().toPoint())
                    else:
                        pos = viewport.mapFromGlobal(event.globalPosition().toPoint())
                    idx = table.indexAt(pos)
                    if (
                        idx.isValid()
                        and d._editIndex is not None
                        and (idx.row(), idx.column())
                        != (d._editIndex.row(), d._editIndex.column())
                    ):
                        asRange = bool(
                            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        )
                        if d.insertRef(idx.column(), idx.row(), asRange=asRange):
                            return True

        if self._drag is not None and et == QEvent.Type.MouseMove:
            pos = event.position().toPoint() if isinstance(event, QMouseEvent) else viewport.mapFromGlobal(QCursor.pos())
            if obj is not viewport:
                pos = viewport.mapFromGlobal(QCursor.pos())
            idx = table.indexAt(pos)
            if idx.isValid():
                self._drag["endR"] = idx.row()
                self._drag["endC"] = idx.column()
                self._updateBand()
            return True

        if self._drag is not None and et == QEvent.Type.MouseButtonRelease:
            table.viewport().releaseMouse()
            if self._band is not None:
                self._band.hide()
            self._applyFill()
            self._drag = None
            self.repositionHandle()
            return True

        return super().eventFilter(obj, event)

    def _applyFill(self):
        drag = self._drag
        table = self._table()
        if drag is None or table is None:
            return
        sMinR, sMaxR = drag["minR"], drag["maxR"]
        sMinC, sMaxC = drag["minC"], drag["maxC"]
        endR, endC = drag["endR"], drag["endC"]
        nRows = sMaxR - sMinR + 1
        nCols = sMaxC - sMinC + 1
        # Drag along the longer overflow axis (Excel: down or right from the handle)
        down = endR > sMaxR
        right = endC > sMaxC
        up = endR < sMinR
        left = endC < sMinC
        filled = 0
        from core import Undo
        Undo.stackFor(self.mainWindow).beginMacro()
        if down:
            destMax = endR
            for r in range(sMaxR + 1, destMax + 1):
                for c in range(sMinC, sMaxC + 1):
                    srcR = sMinR + ((r - sMinR) % nRows)
                    srcC = c
                    filled += int(self._copyCell(srcR, srcC, r, c))
        elif right:
            destMax = endC
            for c in range(sMaxC + 1, destMax + 1):
                for r in range(sMinR, sMaxR + 1):
                    srcC = sMinC + ((c - sMinC) % nCols)
                    srcR = r
                    filled += int(self._copyCell(srcR, srcC, r, c))
        elif up:
            destMin = endR
            for r in range(destMin, sMinR):
                for c in range(sMinC, sMaxC + 1):
                    srcR = sMinR + ((r - destMin) % nRows)
                    srcC = c
                    filled += int(self._copyCell(srcR, srcC, r, c))
        elif left:
            destMin = endC
            for c in range(destMin, sMinC):
                for r in range(sMinR, sMaxR + 1):
                    srcC = sMinC + ((c - destMin) % nCols)
                    srcR = r
                    filled += int(self._copyCell(srcR, srcC, r, c))
        from core import Undo
        Undo.stackFor(self.mainWindow).endMacro()
        if filled:
            recalculateAll(self.mainWindow)
        if Config.debug:
            Logic.logMessage("DEBUG", f"FormulaUi.fill: copied {filled} cell(s)")

    def _copyCell(self, srcR, srcC, dstR, dstC) -> bool:
        table = self._table()
        if not formulaMayEdit(self.mainWindow, dstC):
            return False
        src = table.item(srcR, srcC)
        formula = _itemFormula(src)
        if formula:
            text = adjustFormula(formula, dstC - srcC, dstR - srcR)
        else:
            text = src.text() if src is not None else ""
        return applyCellInput(self.mainWindow, dstR, dstC, text, asFill=True)


def installOnTable(mainWindow):
    """Attach formula delegate + fill-handle filter to the Data Query table."""
    table = getattr(mainWindow, "mainTable", None)
    if table is None:
        return
    delegate = FormulaDelegate(mainWindow)
    table.setItemDelegate(delegate)
    table._formulaPointing = False
    filt = FormulaTableFilter(mainWindow)
    table._formulaFilter = filt
    table.viewport().installEventFilter(filt)
    table.installEventFilter(filt)
    table.viewport().setMouseTracking(True)
    Upload.cellInputHook = applyCellInput
    Upload.recalcHook = recalculateAll
    filt.repositionHandle()
    if Config.debug:
        Logic.logMessage("DEBUG", "FormulaUi.installOnTable: formula delegate + fill handle")
