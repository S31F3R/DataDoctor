# Undo.py
# Ctrl+Z / Ctrl+Y stack for the Data Query table (cell edits + column ops).
# SQL editors keep QPlainTextEdit's built-in undo.

from __future__ import annotations

from core import Config, Logic


class _Macro:
    def __init__(self, commands):
        self.commands = list(commands)

    def undo(self, mainWindow):
        for cmd in reversed(self.commands):
            cmd.undo(mainWindow)

    def redo(self, mainWindow):
        for cmd in self.commands:
            cmd.redo(mainWindow)


class CellEditCmd:
    def __init__(self, row, col, oldText, oldFormula, newText, newFormula):
        self.row = row
        self.col = col
        self.oldText = oldText
        self.oldFormula = oldFormula
        self.newText = newText
        self.newFormula = newFormula

    def _apply(self, mainWindow, text, formula):
        from core import FormulaUi
        FormulaUi.applyCellInput(mainWindow, self.row, self.col, formula or text, asFill=True)
        FormulaUi.recalculateAll(mainWindow)

    def undo(self, mainWindow):
        self._apply(mainWindow, self.oldText, self.oldFormula)

    def redo(self, mainWindow):
        self._apply(mainWindow, self.newText, self.newFormula)


class TableUndoStack:
    def __init__(self, maxLen=80):
        self.undoList = []
        self.redoList = []
        self.maxLen = maxLen
        self.blocked = False
        self._macro = None

    def beginMacro(self):
        if self.blocked:
            return
        self._macro = []

    def endMacro(self):
        if self._macro:
            self._push(_Macro(self._macro))
        self._macro = None

    def _push(self, cmd):
        if self.blocked or cmd is None:
            return
        if self._macro is not None:
            self._macro.append(cmd)
            return
        self.undoList.append(cmd)
        if len(self.undoList) > self.maxLen:
            self.undoList.pop(0)
        self.redoList.clear()

    def pushCellEdit(self, row, col, oldText, oldFormula, newText, newFormula):
        if oldText == newText and (oldFormula or "") == (newFormula or ""):
            return
        self._push(CellEditCmd(row, col, oldText, oldFormula, newText, newFormula))

    def push(self, cmd):
        self._push(cmd)

    def undo(self, mainWindow) -> bool:
        if not self.undoList:
            return False
        cmd = self.undoList.pop()
        self.blocked = True
        try:
            cmd.undo(mainWindow)
        except Exception as e:
            Logic.logException("TableUndoStack.undo failed", e)
        finally:
            self.blocked = False
        self.redoList.append(cmd)
        if Config.debug:
            Logic.logMessage("DEBUG", f"TableUndoStack: undo {type(cmd).__name__}")
        return True

    def redo(self, mainWindow) -> bool:
        if not self.redoList:
            return False
        cmd = self.redoList.pop()
        self.blocked = True
        try:
            cmd.redo(mainWindow)
        except Exception as e:
            Logic.logException("TableUndoStack.redo failed", e)
        finally:
            self.blocked = False
        self.undoList.append(cmd)
        if Config.debug:
            Logic.logMessage("DEBUG", f"TableUndoStack: redo {type(cmd).__name__}")
        return True

    def clear(self):
        self.undoList.clear()
        self.redoList.clear()
        self._macro = None


def stackFor(mainWindow) -> TableUndoStack:
    stack = getattr(mainWindow, "tableUndo", None)
    if stack is None:
        stack = TableUndoStack()
        if mainWindow is not None:
            mainWindow.tableUndo = stack
    return stack


def pushCellEdit(mainWindow, row, col, oldText, oldFormula, newText, newFormula):
    stackFor(mainWindow).pushCellEdit(row, col, oldText, oldFormula, newText, newFormula)
