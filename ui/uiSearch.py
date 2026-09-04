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

        # Populate with limited columns (must match bunker.db schema; datatype is lowercase)
        columns = ['dataID', 'siteID', 'database', 'commonName', 'datatype']
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

        self._headerFilters = None
        self._ensureHeaderFilters()

        if Config.debug:
            Logic.logMessage("DEBUG", "uiSearch initialized")

    def showEvent(self, event):
        self._ensureHeaderFilters()
        Utils.centerWindowToParent(self)
        super().showEvent(event)

    def _ensureHeaderFilters(self):
        if self.searchTable is None or self._headerFilters is not None:
            return
        from core.HeaderFilter import HeaderFilterBar
        self._headerFilters = HeaderFilterBar(
            self.searchTable, ("siteID", "database"), onChange=self.applyFilter, parent=self
        )

    def rebuildHeaderFilters(self):
        """Reload dictionary rows after a save, then refresh filter lists."""
        table = self.searchTable
        if table is None:
            return
        columns = ['dataID', 'siteID', 'database', 'commonName', 'datatype']
        parent = self.parent()
        qt = getattr(parent, 'queryType', None)
        whereClause = "database != 'AQUARIUS'" if qt == 'public' else None
        Logic.buildDataDictionary(table, columns=columns, whereClause=whereClause)
        if self._headerFilters is not None:
            self._headerFilters.rebuild()
        self.applyFilter()

    def startDebounce(self, text):
        self.debounceTimer.stop()
        self.debounceTimer.start(300)

    def applyFilter(self):
        searchText = self.qleSearch.text()
        equals = {}
        contains = {}
        filt = getattr(self, "_headerFilters", None)
        if filt is not None:
            equals = filt.activeEquals()
            contains = filt.activeContains()
        Logic.filterTable(
            self.searchTable, searchText, ['dataID', 'commonName', 'datatype'],
            columnEquals=equals, columnContains=contains,
        )

    def _cellText(self, row, columnName):
        for c in range(self.searchTable.columnCount()):
            header = self.searchTable.horizontalHeaderItem(c)
            if header is not None and header.text().strip() == columnName:
                item = self.searchTable.item(row, c)
                return item.text() if item is not None else ''
        return ''

    def addToQuery(self, item):
        row = item.row()
        dataID = self._cellText(row, 'dataID')
        database = self._cellText(row, 'database')
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
        dataID = self._cellText(row, 'dataID')
        database = self._cellText(row, 'database')
        interval = self.parent().cbInterval.currentText()
        itemText = f"{dataID}|{interval}|{database}"
        self.parent().listQueryList.addItem(itemText)
        self.parent().listQueryList.scrollToBottom()

        if Config.debug:
            Logic.logMessage("DEBUG", f"Added query from search context: {itemText}")