# uiDataDictionary.py

import sqlite3
from PyQt6.QtWidgets import (
    QMainWindow, QTableWidget, QPushButton, QLineEdit, QComboBox,
    QStyledItemDelegate, QMessageBox,
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6 import uic
from core import Logic, Utils, Config


class ValuePrecisionDelegate(QStyledItemDelegate):
    """
    Combobox editor for the valuePrecision column.
    Items are Aquarius parameter Identifiers (from valuePrecision.json).
    Blank row = no Identifier → formatting falls back to DEC(2).
    Uses a delegate (not setCellWidget) so 30k-row tables stay light.
    """

    def __init__(self, identifiers, parent=None):
        super().__init__(parent)
        # identifiers: list[str] of Aquarius Identifiers
        self.identifiers = list(identifiers) if identifiers else []

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.addItem('')  # blank → default DEC(2) at format time
        for ident in self.identifiers:
            _, byId = Logic.loadAquariusRoundingSpecs()
            spec = byId.get(ident)
            # Show rule next to name for operators; model stores Identifier only
            label = f'{ident}  [{spec}]' if spec else ident
            combo.addItem(label, ident)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        return combo

    def setEditorData(self, editor, index):
        current = (index.data(Qt.ItemDataRole.DisplayRole) or '').strip()
        # Prefer userData (Identifier); fall back to matching display text
        idx = editor.findData(current)
        if idx < 0:
            idx = editor.findText(current)
        if idx < 0 and current:
            # Match Identifier ignoring trailing "  [SPEC]"
            for i in range(editor.count()):
                data = editor.itemData(i)
                if data and str(data).lower() == current.lower():
                    idx = i
                    break
                if editor.itemText(i).split('  [')[0].strip().lower() == current.lower():
                    idx = i
                    break
        editor.setCurrentIndex(max(0, idx))

    def setModelData(self, editor, model, index):
        # Store bare Identifier (or '') — not the "Name [DEC(n)]" label
        data = editor.currentData()
        if data is None:
            text = editor.currentText().strip()
            # Strip optional "  [SPEC]" suffix if user somehow has free text
            if '  [' in text:
                text = text.split('  [', 1)[0].strip()
            model.setData(index, text, Qt.ItemDataRole.EditRole)
        else:
            model.setData(index, str(data), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class DatabaseDelegate(QStyledItemDelegate):
    """
    Combobox editor for the database column.
    Choices match the query database list (internal + public sources).
    Blank allowed for unfinished rows.
    """

    def __init__(self, databases, parent=None):
        super().__init__(parent)
        self.databases = list(databases) if databases else []

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.addItem('')  # blank allowed
        for name in self.databases:
            combo.addItem(name)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        return combo

    def setEditorData(self, editor, index):
        current = (index.data(Qt.ItemDataRole.DisplayRole) or '').strip()
        idx = editor.findText(current)
        if idx < 0 and current:
            # Unknown value from DB — keep visible so save does not wipe it
            editor.addItem(current)
            idx = editor.findText(current)
        editor.setCurrentIndex(max(0, idx))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class uiDataDictionary(QMainWindow):
    """Data dictionary editor: Manages labels for time-series IDs."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winDataDictionary.ui'), self)
        self.winMain = winMain

        # Define controls
        self.mainTable = self.findChild(QTableWidget, 'dataDictionaryTable')
        self.btnSave = self.findChild(QPushButton, 'btnSave')
        self.btnAddRow = self.findChild(QPushButton, 'btnAddRow')
        self.btnDeleteRow = self.findChild(QPushButton, 'btnDeleteRow')
        self.qleSearch = self.findChild(QLineEdit, 'qleSearch') # Find the search QLineEdit
        self._valuePrecisionDelegate = None
        self._databaseDelegate = None

        # Set up debounce timer for search
        self.searchTimer = QTimer(self)
        self.searchTimer.setSingleShot(True)
        self.searchTimer.timeout.connect(self.performFilter)

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnAddRow.clicked.connect(self.btnAddRowPressed)
        self.btnDeleteRow.clicked.connect(self.btnDeleteRowPressed)
        self.qleSearch.textChanged.connect(self.debounceFilter) # Connect textChanged for debounced filtering

        # Ctrl+S → save (same as toolbar Save)
        self._saveShortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._saveShortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._saveShortcut.activated.connect(self.btnSavePressed)

        # Set button style
        Utils.buttonStyle(self.btnSave, "Save", 36)
        Utils.buttonStyle(self.btnAddRow, "Plus", 36)
        Utils.buttonStyle(self.btnDeleteRow, "Delete", 36)

        # Larger default + visible resize grip (handle was too small / easy to miss)
        self.resize(max(self.width(), 1280), max(self.height(), 720))
        self.setMinimumSize(900, 500)
        sb = self.statusBar()
        if sb is not None:
            sb.setSizeGripEnabled(True)
            sb.show()

        self.applyDictionaryScrollStyle()
        
        if Config.debug:
            Logic.logMessage("DEBUG", "uiDataDictionary initialized with btnDeleteRow")

    def applyDictionaryScrollStyle(self):
        """Thick grip + retro green (or neutral) so 40k-row tables stay theme-consistent."""
        if self.mainTable is None:
            return
        # Prefer Config.retroMode; fall back to True (app default)
        retro = bool(getattr(Config, 'retroMode', True))
        self.mainTable.setStyleSheet(Utils.thickScrollBarStyle(retro=retro, minHandle=48, track=20))
        if Config.debug:
            Logic.logMessage("DEBUG", f"DataDictionary scrollbar style applied (retro={retro})")

    def _columnIndexByName(self, name):
        """Return column index for header name (case-insensitive), or -1."""
        if self.mainTable is None:
            return -1
        target = (name or '').strip().lower()
        for c in range(self.mainTable.columnCount()):
            h = self.mainTable.horizontalHeaderItem(c)
            if h and h.text().strip().lower() == target:
                return c
        return -1

    def applyValuePrecisionDelegate(self):
        """Attach combobox editor to the valuePrecision column (by header name)."""
        if self.mainTable is None:
            return
        col = self._columnIndexByName('valuePrecision')
        if col < 0:
            if Config.debug:
                Logic.logMessage("DEBUG", "applyValuePrecisionDelegate: valuePrecision column not found")
            return
        identifiers = Logic.aquariusIdentifierList()
        self._valuePrecisionDelegate = ValuePrecisionDelegate(identifiers, self.mainTable)
        self.mainTable.setItemDelegateForColumn(col, self._valuePrecisionDelegate)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"applyValuePrecisionDelegate: combo on col {col} with {len(identifiers)} identifiers",
            )

    def applyDatabaseDelegate(self):
        """Attach combobox editor to the database column (same list as query combos)."""
        if self.mainTable is None:
            return
        col = self._columnIndexByName('database')
        if col < 0:
            if Config.debug:
                Logic.logMessage("DEBUG", "applyDatabaseDelegate: database column not found")
            return
        # Full program list (internal-style) so AQUARIUS + HDB + USGS are all available
        databases = Utils.programDatabases(queryType='internal')
        self._databaseDelegate = DatabaseDelegate(databases, self.mainTable)
        self.mainTable.setItemDelegateForColumn(col, self._databaseDelegate)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"applyDatabaseDelegate: combo on col {col} with {len(databases)} databases",
            )
    
    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", f"uiDataDictionary showEvent")
        # Re-apply in case retro mode changed while window was closed
        self.applyDictionaryScrollStyle()
        self.applyValuePrecisionDelegate()
        self.applyDatabaseDelegate()
        Utils.centerWindowToParent(self)
        super().showEvent(event)
    
    def btnSavePressed(self):
        # Commit any open combobox editor before reading cells
        if self.mainTable is not None:
            # Force focus away from the editor so setModelData runs
            self.mainTable.setFocus()
            self.mainTable.clearFocus()

        columns = [
            self.mainTable.horizontalHeaderItem(c).text().strip()
            for c in range(self.mainTable.columnCount())
            if self.mainTable.horizontalHeaderItem(c)
        ]

        if not columns:
            Logic.logMessage("WARN", "No columns found in DataDictionary table for saving")
            return

        # REAL numeric columns (by name)
        realCols = {
            'expectedmin', 'expectedmax', 'cuttoffmin', 'cutoffmin',
            'cutoffmax', 'rateofchange',
        }
        dataRows = []
        badOverrides = []

        for r in range(self.mainTable.rowCount()):
            rowData = []
            isEmptyRow = True

            for c in range(self.mainTable.columnCount()):
                colName = columns[c] if c < len(columns) else ''
                colLower = colName.lower()
                item = self.mainTable.item(r, c)
                cellText = item.text().strip() if item and item.text() else ''

                if colLower == 'precisionoverride' and cellText:
                    if Logic.normalizeRoundingSpec(cellText) is None:
                        badOverrides.append((r + 1, cellText))

                if colLower in realCols:
                    try:
                        cellVal = float(cellText) if cellText else None
                    except ValueError:
                        cellVal = cellText if cellText else None
                else:
                    cellVal = cellText if cellText else None
                rowData.append(cellVal)

                if cellVal is not None and cellVal != '':
                    isEmptyRow = False
            if not isEmptyRow:
                dataRows.append(rowData)

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Saved row {r} with data: {rowData}")
            else:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Skipped empty row {r}")

        if badOverrides:
            preview = '\n'.join(f'  row {rn}: {val!r}' for rn, val in badOverrides[:8])
            extra = f'\n  ... and {len(badOverrides) - 8} more' if len(badOverrides) > 8 else ''
            QMessageBox.warning(
                self,
                "Invalid precisionOverride",
                "precisionOverride must be blank or SIG(#) / DEC(#) "
                "(optionally SIG(n,m) for Aquarius-style specs).\n\n"
                f"Invalid entries:\n{preview}{extra}\n\nSave canceled.",
            )
            return

        dbPath = Logic.resourcePath('core/bunker.db')

        try:
            Logic.ensureDataDictionarySchema()
            with sqlite3.connect(dbPath) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM dataDictionary")

                for row in dataRows:
                    placeholders = ','.join('?' for _ in row)
                    # Quote column names for safety
                    colSql = ','.join(f'"{c}"' for c in columns)
                    cur.execute(
                        f"INSERT INTO dataDictionary ({colSql}) VALUES ({placeholders})",
                        row,
                    )
                conn.commit()
        except Exception as e:
            Logic.logException("Failed to save DataDictionary to DB", e)
            QMessageBox.warning(self, "Save Failed", f"Could not save data dictionary:\n{e}")
            return
        for c in range(self.mainTable.columnCount()):
            self.mainTable.resizeColumnToContents(c)
        if Config.debug:
            Logic.logMessage("DEBUG", f"DataDictionary saved with {len(dataRows)} rows and columns resized")
        QMessageBox.information(
            self,
            "Saved",
            f"Data dictionary saved ({len(dataRows)} rows).",
        )
    
    def btnAddRowPressed(self):
        self.mainTable.setRowCount(self.mainTable.rowCount() + 1)
        self.mainTable.scrollToBottom()

        if Config.debug:
            Logic.logMessage("DEBUG", f"Added row to DataDictionary, scrolled to bottom, new row count: {self.mainTable.rowCount()}")
    
    def btnDeleteRowPressed(self):
        currentRow = self.mainTable.currentRow()

        if currentRow >= 0:
            self.mainTable.removeRow(currentRow)
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"Removed row {currentRow} from DataDictionary, new row count: {self.mainTable.rowCount()}")
        else:
            if Config.debug:
                Logic.logMessage("DEBUG", "No row selected for removal in DataDictionary")

    def debounceFilter(self, text):
        """Debounce the filter to avoid running on every keystroke."""
        if self.searchTimer.isActive():
            self.searchTimer.stop()
        self.searchTimer.start(300) # 300ms delay before filtering

        if Config.debug:
            Logic.logMessage("DEBUG", f"debounceFilter: Timer started for text '{text}'")

    def performFilter(self):
        """Perform the actual table filtering after debounce delay."""
        text = self.qleSearch.text()

        if Config.debug:
            Logic.logMessage("DEBUG", f"performFilter: Applying filter with text '{text}'")
        Logic.filterTable(self.mainTable, text, ['dataID', 'siteID', 'siteName', 'commonName'])

        if Config.debug:
            Logic.logMessage("DEBUG", "performFilter: Filtering completed")
