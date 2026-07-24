# uiDataDictionary.py

import sqlite3
from PyQt6.QtWidgets import QMainWindow, QTableWidget, QPushButton, QLineEdit
from PyQt6 import uic
from PyQt6.QtCore import QTimer
from core import Logic, Utils, Config

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

        # Set up debounce timer for search
        self.searchTimer = QTimer(self)
        self.searchTimer.setSingleShot(True)
        self.searchTimer.timeout.connect(self.performFilter)

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnAddRow.clicked.connect(self.btnAddRowPressed)
        self.btnDeleteRow.clicked.connect(self.btnDeleteRowPressed)
        self.qleSearch.textChanged.connect(self.debounceFilter) # Connect textChanged for debounced filtering

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

        # 40k+ dictionary rows shrink the vertical scrollbar grip to a few pixels;
        # force a thick track + min handle so it can actually be grabbed.
        if self.mainTable is not None:
            self.mainTable.setStyleSheet("""
                QScrollBar:vertical {
                    width: 20px;
                    margin: 0px;
                    background: #2a2a2a;
                }
                QScrollBar::handle:vertical {
                    min-height: 48px;
                    background: #6a6a6a;
                    border-radius: 4px;
                    margin: 2px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #8a8a8a;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QScrollBar:horizontal {
                    height: 16px;
                    background: #2a2a2a;
                }
                QScrollBar::handle:horizontal {
                    min-width: 48px;
                    background: #6a6a6a;
                    border-radius: 4px;
                }
            """)
        
        if Config.debug:
            Logic.logMessage("DEBUG", "uiDataDictionary initialized with btnDeleteRow")
    
    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", f"uiDataDictionary showEvent")
        Utils.centerWindowToParent(self)
        super().showEvent(event)
    
    def btnSavePressed(self):
        columns = [self.mainTable.horizontalHeaderItem(c).text().strip() for c in range(self.mainTable.columnCount()) if self.mainTable.horizontalHeaderItem(c)]

        if not columns:
            Logic.logMessage("WARN", "No columns found in DataDictionary table for saving")
            return
        dataRows = []

        for r in range(self.mainTable.rowCount()):
            rowData = []
            isEmptyRow = True

            for c in range(self.mainTable.columnCount()):
                item = self.mainTable.item(r, c)
                cellText = item.text().strip() if item else ''

                # Attempt float conversion for REAL columns (based on naming pattern)
                if columns[c].startswith('123_'):
                    try:
                        cellText = float(cellText) if cellText else None
                    except ValueError:
                        pass # Keep as str if invalid
                else:
                    cellText = cellText if cellText else None
                rowData.append(cellText)

                if cellText is not None and cellText != '':
                    isEmptyRow = False
            if not isEmptyRow:
                dataRows.append(rowData)

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Saved row {r} with data: {rowData}")
            else:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Skipped empty row {r}")
        dbPath = Logic.resourcePath('core/bunker.db')

        try:
            with sqlite3.connect(dbPath) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM dataDictionary")

                for row in dataRows:
                    placeholders = ','.join('?' for _ in row)
                    cur.execute(f"INSERT INTO dataDictionary ({','.join(columns)}) VALUES ({placeholders})", row)
                conn.commit()
        except Exception as e:
            Logic.logMessage("ERROR", f"Failed to save DataDictionary to DB: {e}")
            return
        for c in range(self.mainTable.columnCount()):
            self.mainTable.resizeColumnToContents(c)
        if Config.debug:
            Logic.logMessage("DEBUG", f"DataDictionary saved with {len(dataRows)} rows and columns resized")
    
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