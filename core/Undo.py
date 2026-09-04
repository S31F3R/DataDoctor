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
    def __init__(
        self, row, col, oldText, oldFormula, newText, newFormula,
        oldBg=None, oldFg=None, newBg=None, newFg=None,
        oldEdit=None, newEdit=None,
        oldUser=None, newUser=None,
    ):
        self.row = row
        self.col = col
        self.oldText = oldText
        self.oldFormula = oldFormula
        self.newText = newText
        self.newFormula = newFormula
        self.oldBg = oldBg
        self.oldFg = oldFg
        self.newBg = newBg
        self.newFg = newFg
        self.oldEdit = dict(oldEdit) if isinstance(oldEdit, dict) else None
        self.newEdit = dict(newEdit) if isinstance(newEdit, dict) else None
        self.oldUser = dict(oldUser) if isinstance(oldUser, dict) else None
        self.newUser = dict(newUser) if isinstance(newUser, dict) else None

    def _apply(self, mainWindow, text, formula, bg, fg, editState, userSnap):
        from core import FormulaUi, Upload
        prev = getattr(mainWindow, "uploadTrackingBlocked", False)
        mainWindow.uploadTrackingBlocked = True
        try:
            FormulaUi.applyCellInput(
                mainWindow, self.row, self.col, formula or text,
                asFill=True, skipUndo=True,
            )
            table = getattr(mainWindow, "mainTable", None)
            item = table.item(self.row, self.col) if table is not None else None
            if item is not None:
                if userSnap is not None:
                    Upload.setUserDict(item, dict(userSnap))
                Upload.applyColors(item, bg, fg)
                if editState is not None:
                    user = Upload.getUserDict(item)
                    user[Upload.editKey] = dict(editState)
                    Upload.setUserDict(item, user)
            FormulaUi.recalculateAll(mainWindow)
        finally:
            mainWindow.uploadTrackingBlocked = prev

    def undo(self, mainWindow):
        self._apply(
            mainWindow, self.oldText, self.oldFormula,
            self.oldBg, self.oldFg, self.oldEdit, self.oldUser,
        )

    def redo(self, mainWindow):
        self._apply(
            mainWindow, self.newText, self.newFormula,
            self.newBg, self.newFg, self.newEdit, self.newUser,
        )


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

    def pushCellEdit(
        self, row, col, oldText, oldFormula, newText, newFormula,
        oldBg=None, oldFg=None, newBg=None, newFg=None,
        oldEdit=None, newEdit=None,
        oldUser=None, newUser=None,
    ):
        sameText = oldText == newText and (oldFormula or "") == (newFormula or "")
        sameFmt = oldBg == newBg and oldFg == newFg
        sameUser = oldUser == newUser
        if sameText and sameFmt and sameUser:
            return
        self._push(CellEditCmd(
            row, col, oldText, oldFormula, newText, newFormula,
            oldBg, oldFg, newBg, newFg, oldEdit, newEdit,
            oldUser, newUser,
        ))

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


def pushCellEdit(mainWindow, row, col, oldText, oldFormula, newText, newFormula, **kwargs):
    stackFor(mainWindow).pushCellEdit(
        row, col, oldText, oldFormula, newText, newFormula, **kwargs
    )
