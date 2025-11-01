# uiDataDictionary.py

import sqlite3
from PyQt6.QtWidgets import QMainWindow, QTableWidget, QPushButton
from PyQt6 import uic
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
        
        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnAddRow.clicked.connect(self.btnAddRowPressed)
        self.btnDeleteRow.clicked.connect(self.btnDeleteRowPressed)
        
        # Set button style
        Utils.buttonStyle(self.btnSave)
        Utils.buttonStyle(self.btnAddRow)
        Utils.buttonStyle(self.btnDeleteRow)
        
        if Config.debug:
            print("[DEBUG] uiDataDictionary initialized with btnDeleteRow")
    
    def showEvent(self, event):
        if Config.debug:
            print(f"[DEBUG] uiDataDictionary showEvent")
        Utils.centerWindowToParent(self)
        super().showEvent(event)
    
    def btnSavePressed(self):
        columns = [self.mainTable.horizontalHeaderItem(c).text().strip() for c in range(self.mainTable.columnCount()) if self.mainTable.horizontalHeaderItem(c)]

        if not columns:
            if Config.debug:
                print("[WARN] No columns found in DataDictionary table for saving")
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
                    print(f"[DEBUG] Saved row {r} with data: {rowData}")
            else:
                if Config.debug:
                    print(f"[DEBUG] Skipped empty row {r}")
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
            if Config.debug:
                print(f"[ERROR] Failed to save DataDictionary to DB: {e}")
            return
        for c in range(self.mainTable.columnCount()):
            self.mainTable.resizeColumnToContents(c)
        if Config.debug:
            print(f"[DEBUG] DataDictionary saved with {len(dataRows)} rows and columns resized")
    
    def btnAddRowPressed(self):
        self.mainTable.setRowCount(self.mainTable.rowCount() + 1)
        self.mainTable.scrollToBottom()

        if Config.debug:
            print(f"[DEBUG] Added row to DataDictionary, scrolled to bottom, new row count: {self.mainTable.rowCount()}")
    
    def btnDeleteRowPressed(self):
        currentRow = self.mainTable.currentRow()

        if currentRow >= 0:
            self.mainTable.removeRow(currentRow)
            
            if Config.debug:
                print(f"[DEBUG] Removed row {currentRow} from DataDictionary, new row count: {self.mainTable.rowCount()}")
        else:
            if Config.debug:
                print("[DEBUG] No row selected for removal in DataDictionary")