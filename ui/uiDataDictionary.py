# uiDataDictionary.py

import sqlite3
from PyQt6.QtWidgets import (
    QMainWindow, QTableWidget, QPushButton, QLineEdit, QComboBox,
    QStyledItemDelegate, QMessageBox, QApplication, QAbstractItemView, QMenu,
    QAbstractItemDelegate,
)
from PyQt6.QtCore import QTimer, Qt, QObject, QEvent
from PyQt6.QtGui import QKeySequence, QShortcut, QFontMetrics
from PyQt6 import uic
from core import Logic, Utils, Config


def _indexIsBeingEdited(option, index) -> bool:
    """True when this cell currently has an open editor (combobox overlay)."""
    view = option.widget
    if not isinstance(view, QAbstractItemView):
        return False
    try:
        if view.state() != QAbstractItemView.State.EditingState:
            return False
        return view.currentIndex() == index
    except RuntimeError:
        return False


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
        # Precompute display labels once (avoid loadAquariusRoundingSpecs per item)
        _, byId = Logic.loadAquariusRoundingSpecs()
        self._labels = []  # list of (label, ident)
        self._labels.append(('', ''))
        for ident in self.identifiers:
            spec = byId.get(ident)
            label = f'{ident}  [{spec}]' if spec else ident
            self._labels.append((label, ident))

    def displayLabels(self):
        """Labels shown in the combobox (for column sizing)."""
        return [label for label, _ in self._labels if label]

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.setAutoFillBackground(True)
        combo.setFrame(True)
        for label, ident in self._labels:
            combo.addItem(label, ident)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        return combo

    def paint(self, painter, option, index):
        # While the combobox editor is open, skip drawing the cell text so it
        # does not overlay the combo's current item.
        if _indexIsBeingEdited(option, index):
            painter.fillRect(option.rect, option.palette.base())
            return
        super().paint(painter, option, index)

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

    def displayLabels(self):
        """Labels shown in the combobox (for column sizing)."""
        return list(self.databases)

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.setAutoFillBackground(True)
        combo.setFrame(True)
        combo.addItem('')  # blank allowed
        for name in self.databases:
            combo.addItem(name)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        return combo

    def paint(self, painter, option, index):
        if _indexIsBeingEdited(option, index):
            painter.fillRect(option.rect, option.palette.base())
            return
        super().paint(painter, option, index)

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


class dictionaryTableKeyFilter(QObject):
    """Ctrl+C copies selected Data Dictionary cells (TSV)."""

    def __init__(self, dictionaryWindow):
        super().__init__(dictionaryWindow)
        self.dictionaryWindow = dictionaryWindow

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier) or bool(
                mods & Qt.KeyboardModifier.MetaModifier
            )
            if ctrl and key == Qt.Key.Key_C:
                if self.dictionaryWindow.copySelectionToClipboard():
                    return True
        return super().eventFilter(obj, event)


class uiDataDictionary(QMainWindow):
    """Data dictionary editor: Manages labels for time-series IDs."""
    def __init__(self, winMain=None):
        # No Qt parent: child QMainWindows shade-minimize instead of taskbar.
        super().__init__(None)
        uic.loadUi(Logic.resourcePath('ui/winDataDictionary.ui'), self)
        self.winMain = winMain
        self._saveInProgress = False
        Utils.bindIndependentWindow(self, owner=winMain, allowMaximize=True)

        # Define controls
        self.mainTable = self.findChild(QTableWidget, 'dataDictionaryTable')
        self.btnSave = self.findChild(QPushButton, 'btnSave')
        self.btnAddRow = self.findChild(QPushButton, 'btnAddRow')
        self.btnDeleteRow = self.findChild(QPushButton, 'btnDeleteRow')
        self.qleSearch = self.findChild(QLineEdit, 'qleSearch') # Find the search QLineEdit
        self._valuePrecisionDelegate = None
        self._databaseDelegate = None

        # Cell-level multi-select (not whole-row) so copy can grab one or many cells
        if self.mainTable is not None:
            self.mainTable.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.mainTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
            self.mainTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.mainTable.customContextMenuRequested.connect(self.showTableContextMenu)
            self._dictKeyFilter = dictionaryTableKeyFilter(self)
            self.mainTable.installEventFilter(self._dictKeyFilter)
            self.mainTable.viewport().installEventFilter(self._dictKeyFilter)

        # Set up debounce timer for search
        self.searchTimer = QTimer(self)
        self.searchTimer.setSingleShot(True)
        self.searchTimer.timeout.connect(self.performFilter)

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnAddRow.clicked.connect(self.btnAddRowPressed)
        self.btnDeleteRow.clicked.connect(self.btnDeleteRowPressed)
        self.qleSearch.textChanged.connect(self.debounceFilter) # Connect textChanged for debounced filtering

        # Ctrl+S → save (same as toolbar Save). Widget shortcut so it wins over
        # an open combobox editor without fighting a modal popup event loop.
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
        self._headerFilters = None
        
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
        databases = Utils.programDatabases(queryType='internal', applyAccessList=False)
        self._databaseDelegate = DatabaseDelegate(databases, self.mainTable)
        self.mainTable.setItemDelegateForColumn(col, self._databaseDelegate)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"applyDatabaseDelegate: combo on col {col} with {len(databases)} databases",
            )

    def sizeComboColumns(self):
        """
        Width for database + valuePrecision from longest combobox label (and header).

        Uses a real QComboBox sizeHint (arrow + frame) plus scrollbar extent so
        the dropdown list does not clip the longest item when a vertical bar shows.
        """
        if self.mainTable is None:
            return
        from PyQt6.QtWidgets import QStyle, QStyleOptionComboBox
        from PyQt6.QtCore import QSize

        tableFont = self.mainTable.font()
        metrics = QFontMetrics(tableFont)

        pairs = (
            ('database', self._databaseDelegate),
            ('valuePrecision', self._valuePrecisionDelegate),
        )
        for colName, delegate in pairs:
            col = self._columnIndexByName(colName)
            if col < 0:
                continue
            headerItem = self.mainTable.horizontalHeaderItem(col)
            headerText = headerItem.text() if headerItem else colName
            headerW = metrics.horizontalAdvance(headerText)

            labels = []
            if delegate is not None and hasattr(delegate, 'displayLabels'):
                labels = [str(x) for x in (delegate.displayLabels() or []) if x]

            # Sample stored cell values (unknown DBs / bare identifiers)
            sampleN = min(100, self.mainTable.rowCount())
            for r in range(sampleN):
                it = self.mainTable.item(r, col)
                if it and it.text():
                    labels.append(it.text())

            # Measure with a live combo so style includes frame + drop arrow
            combo = QComboBox()
            combo.setFont(tableFont)
            if labels:
                combo.addItems(labels)
            else:
                combo.addItem(headerText or 'M')
            opt = QStyleOptionComboBox()
            combo.initStyleOption(opt)
            textW = max(
                (metrics.horizontalAdvance(t) for t in labels),
                default=headerW,
            )
            textW = max(textW, headerW)
            style = combo.style()
            content = style.sizeFromContents(
                QStyle.ContentsType.CT_ComboBox,
                opt,
                QSize(textW, metrics.height()),
                combo,
            )
            # Popup list always gets a vertical scrollbar with many valuePrecision items
            sb = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, opt, combo)
            # Thick themed bars in this app are wider than the style default (~14)
            sb = max(sb, 20)
            # Extra fudge: list view margins + selection highlight padding
            fudge = 12
            finalW = max(content.width(), textW) + sb + fudge
            self.mainTable.setColumnWidth(col, finalW)
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"sizeComboColumns: {colName} col={col} width={finalW} "
                    f"(text={textW}, content={content.width()}, sb={sb}, "
                    f"{len(labels)} labels)",
                )

    def _commitOpenEditor(self):
        """
        Commit and close any open cell editor (combobox/line edit) so save
        reads the latest value. Avoids modal-popup / QMessageBox deadlocks when
        Ctrl+S fires while a combo dropdown is open.
        """
        table = self.mainTable
        if table is None:
            return

        fw = QApplication.focusWidget()
        # Hide combobox popup first if open (modal sub-window)
        if isinstance(fw, QComboBox):
            try:
                fw.hidePopup()
            except Exception:
                pass

        if table.state() == QAbstractItemView.State.EditingState:
            editor = fw
            # Editor is usually a child of the viewport, not the table itself
            if editor is not None and (
                editor is table or table.isAncestorOf(editor) or isinstance(editor, QComboBox)
            ):
                try:
                    table.commitData(editor)
                    table.closeEditor(
                        editor, QAbstractItemDelegate.EndEditHint.SubmitModelCache
                    )
                except Exception as e:
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"_commitOpenEditor: commit/close failed: {e}")

        # Move focus off the table so any remaining editor finishes cleanly
        if self.btnSave is not None:
            self.btnSave.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.processEvents()
    
    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", f"uiDataDictionary showEvent")
        # Re-apply in case retro mode changed while window was closed
        self.applyDictionaryScrollStyle()
        self.applyValuePrecisionDelegate()
        self.applyDatabaseDelegate()
        # Combo columns sized to dropdown contents (not just bare cell text)
        self.sizeComboColumns()
        # Keep cell selection even if .ui defaults to SelectRows
        if self.mainTable is not None:
            self.mainTable.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.mainTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._ensureHeaderFilters()
        Utils.centerWindowToParent(self)
        super().showEvent(event)

    def _ensureHeaderFilters(self):
        if self.mainTable is None or self._headerFilters is not None:
            return
        from core.HeaderFilter import HeaderFilterBar
        self._headerFilters = HeaderFilterBar(
            self.mainTable, ("siteID", "database"), onChange=self.performFilter, parent=self
        )

    def showTableContextMenu(self, pos):
        """Right-click → Copy selected cell(s) as TSV."""
        table = self.mainTable
        if table is None:
            return
        index = table.indexAt(pos)
        if not index.isValid():
            return

        # If the right-clicked cell is outside the current multi-selection,
        # select only that cell so Copy targets the intended cell.
        sel = table.selectionModel()
        if sel is not None and not sel.isSelected(index):
            table.clearSelection()
            table.setCurrentIndex(index)
            sel.select(index, sel.SelectionFlag.ClearAndSelect)

        menu = QMenu(table)
        copyAction = menu.addAction("Copy")
        copyAction.setShortcut(QKeySequence.StandardKey.Copy)
        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == copyAction:
            self.copySelectionToClipboard()

    def copySelectionToClipboard(self):
        """Copy the selected rectangular range as TSV (Excel/Sheets-friendly)."""
        table = self.mainTable
        if table is None or table.rowCount() == 0:
            return False
        if table.state() == QAbstractItemView.State.EditingState:
            return False

        indexes = table.selectedIndexes()
        if not indexes:
            current = table.currentIndex()
            if current is None or not current.isValid():
                return False
            indexes = [current]

        rows = [i.row() for i in indexes]
        cols = [i.column() for i in indexes]
        minR, maxR = min(rows), max(rows)
        minC, maxC = min(cols), max(cols)

        lines = []
        for r in range(minR, maxR + 1):
            cells = []
            for c in range(minC, maxC + 1):
                item = table.item(r, c)
                text = item.text() if item is not None else ''
                text = text.replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
                cells.append(text)
            lines.append('\t'.join(cells))
        tsv = '\n'.join(lines)

        clip = QApplication.clipboard()
        if clip is None:
            return False
        clip.setText(tsv)

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"uiDataDictionary.copySelectionToClipboard: "
                f"{maxR - minR + 1}x{maxC - minC + 1} → clipboard ({len(tsv)} chars)",
            )
        return True
    
    def btnSavePressed(self):
        if self._saveInProgress:
            return
        if self.mainTable is None:
            return

        self._saveInProgress = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        sortingWasOn = False
        try:
            # Commit open combobox / line editor before reading cells
            self._commitOpenEditor()

            sortingWasOn = self.mainTable.isSortingEnabled()
            if sortingWasOn:
                self.mainTable.setSortingEnabled(False)

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
            rowCount = self.mainTable.rowCount()
            colCount = self.mainTable.columnCount()

            for r in range(rowCount):
                rowData = []
                isEmptyRow = True

                for c in range(colCount):
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

            if badOverrides:
                preview = '\n'.join(f'  row {rn}: {val!r}' for rn, val in badOverrides[:8])
                extra = f'\n  ... and {len(badOverrides) - 8} more' if len(badOverrides) > 8 else ''
                QApplication.restoreOverrideCursor()
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
                    if dataRows:
                        placeholders = ','.join('?' for _ in columns)
                        colSql = ','.join(f'"{c}"' for c in columns)
                        cur.executemany(
                            f"INSERT INTO dataDictionary ({colSql}) VALUES ({placeholders})",
                            dataRows,
                        )
                    conn.commit()
            except Exception as e:
                Logic.logException("Failed to save DataDictionary to DB", e)
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "Save Failed", f"Could not save data dictionary:\n{e}")
                return

            # Size combo columns only — never full resizeColumnToContents on 30k rows
            self.sizeComboColumns()
            if self._headerFilters is not None:
                self._headerFilters.rebuild()
            q = getattr(self.winMain, "winQuery", None) if self.winMain is not None else None
            search = getattr(q, "uiSearch", None) if q is not None else None
            if search is not None and hasattr(search, "rebuildHeaderFilters"):
                search.rebuildHeaderFilters()

            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"DataDictionary saved with {len(dataRows)} rows (of {rowCount} table rows)",
                )
            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self,
                "Saved",
                f"Data dictionary saved ({len(dataRows)} rows).",
            )
        finally:
            if self.mainTable is not None and sortingWasOn:
                self.mainTable.setSortingEnabled(True)
            # Ensure cursor restored if we returned early without dialogs
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self._saveInProgress = False
    
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
        equals = {}
        contains = {}
        filt = getattr(self, "_headerFilters", None)
        if filt is not None:
            equals = filt.activeEquals()
            contains = filt.activeContains()
        Logic.filterTable(
            self.mainTable, text, ['dataID', 'siteName', 'commonName'],
            columnEquals=equals, columnContains=contains,
        )

        if Config.debug:
            Logic.logMessage("DEBUG", "performFilter: Filtering completed")
