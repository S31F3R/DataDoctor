# uiDataDictionary.py

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
        data = []

        with open(Logic.resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
            header = f.readlines()[0].rstrip('\n')
            data.append(header)

            if Config.debug:
                print(f"[DEBUG] Appended stripped header: {header}")
        for r in range(self.mainTable.rowCount()):
            rowData = []
            isEmptyRow = True

            for c in range(self.mainTable.columnCount()):
                item = self.mainTable.item(r, c)
                cellText = item.text().strip() if item else ''
                rowData.append(cellText)

                if cellText:
                    isEmptyRow = False
            if not isEmptyRow:
                data.append(','.join(rowData))
                
                if Config.debug:
                    print(f"[DEBUG] Saved row {r} with data: {rowData}")
            else:
                if Config.debug:
                    print(f"[DEBUG] Skipped empty row {r}")
        with open(Logic.resourcePath('DataDictionary.csv'), 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(data) + '\n')
        for c in range(self.mainTable.columnCount()):
            self.mainTable.resizeColumnToContents(c)
        if Config.debug:
            print(f"[DEBUG] DataDictionary saved with {len(data)-1} rows and columns resized")
    
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