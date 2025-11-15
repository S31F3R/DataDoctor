# uiSearch.py

import os
from PyQt6.QtWidgets import QMainWindow, QLineEdit, QTableWidget, QMenu
from PyQt6.QtCore import Qt, QTimer
from PyQt6 import uic
from core import Logic, Utils, Config

class uiSearch(QMainWindow):
    """Search window: Quick lookup for dataIDs to add to winQuery."""
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        uiPath = Logic.resourcePath('ui/winSearch.ui')

        if Config.debug:
            Logic.logMessage("DEBUG", f"Loading UI file: {uiPath}")
            
            if not os.path.exists(uiPath):
                Logic.logMessage("ERROR", f"UI file not found: {uiPath}")
        try:
            uic.loadUi(uiPath, self)
        except Exception as e:
            Logic.logMessage("ERROR", f"Failed to load UI file: {e}")
            raise

        # Define controls
        self.qleSearch = self.findChild(QLineEdit, 'qleSearch')
        self.searchTable = self.findChild(QTableWidget, 'searchTable')

        # Set window flags to stay on top
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # Setup table
        self.searchTable.setSelectionBehavior(self.searchTable.SelectionBehavior.SelectRows)
        self.searchTable.setEditTriggers(self.searchTable.EditTrigger.NoEditTriggers)

        # Populate with limited columns
        columns = ['dataID', 'database', 'commonName', 'dataType']
        whereClause = "database != 'AQUARIUS'" if self.parent().queryType == 'public' else None
        Logic.buildDataDictionary(self.searchTable, columns=columns, whereClause=whereClause)

        # Setup debounce timer for filter
        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)
        self.debounceTimer.timeout.connect(self.applyFilter)

        # Connect search input
        self.qleSearch.textChanged.connect(self.startDebounce)

        # Connect double-click
        self.searchTable.itemDoubleClicked.connect(self.addToQuery)

        # Setup context menu
        self.searchTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.searchTable.customContextMenuRequested.connect(self.showContextMenu)

        if Config.debug:
            Logic.logMessage("DEBUG", "uiSearch initialized")

    def showEvent(self, event):
        Utils.centerWindowToParent(self)
        super().showEvent(event)

    def startDebounce(self, text):
        self.debounceTimer.stop()
        self.debounceTimer.start(300)

    def applyFilter(self):
        searchText = self.qleSearch.text()
        Logic.filterTable(self.searchTable, searchText, ['dataID', 'commonName', 'dataType'])

    def addToQuery(self, item):
        row = item.row()
        dataID = self.searchTable.item(row, 0).text()
        database = self.searchTable.item(row, 1).text()
        interval = self.parent().cbInterval.currentText()
        itemText = f"{dataID}|{interval}|{database}"
        self.parent().listQueryList.addItem(itemText)
        self.parent().listQueryList.scrollToBottom()

        if Config.debug:
            Logic.logMessage("DEBUG", f"Added query from search: {itemText}")

    def showContextMenu(self, pos):
        item = self.searchTable.itemAt(pos)

        if item:
            row = item.row()
            menu = QMenu(self)
            addAction = menu.addAction("Add to query")
            addAction.triggered.connect(lambda: self.addToQueryFromRow(row))
            menu.exec(self.searchTable.viewport().mapToGlobal(pos))

    def addToQueryFromRow(self, row):
        dataID = self.searchTable.item(row, 0).text()
        database = self.searchTable.item(row, 1).text()
        interval = self.parent().cbInterval.currentText()
        itemText = f"{dataID}|{interval}|{database}"
        self.parent().listQueryList.addItem(itemText)
        self.parent().listQueryList.scrollToBottom()

        if Config.debug:
            Logic.logMessage("DEBUG", f"Added query from search context: {itemText}")