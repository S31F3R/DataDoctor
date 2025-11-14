# uiQuery.py

import json
import os
from PyQt6.QtWidgets import (QMainWindow, QLineEdit, QComboBox, QDateTimeEdit, QListWidget, QPushButton, QRadioButton,
                            QButtonGroup, QCheckBox, QMessageBox, QInputDialog)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QEvent
from PyQt6 import uic
from core import Logic, Query, Utils, Config
from ui.uiSearch import uiSearch

class uiQuery(QMainWindow):
    """Query window: Builds and executes public/internal API calls."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        ui_path = Logic.resourcePath('ui/winQuery.ui')

        if Config.debug:
            Logic.logMessage("DEBUG", f"Loading UI file: {ui_path}")
            if not os.path.exists(ui_path):
                Logic.logMessage("ERROR", f"UI file not found: {ui_path}")
        try:
            uic.loadUi(ui_path, self)
        except Exception as e:
            Logic.logMessage("ERROR", f"Failed to load UI file: {e}")
            raise

        # Define controls
        self.queryType = None
        self.winMain = winMain
        self.btnQuery = self.findChild(QPushButton, 'btnQuery')
        self.qleDataID = self.findChild(QLineEdit, 'qleDataID')
        self.cbDatabase = self.findChild(QComboBox, 'cbDatabase')
        self.cbInterval = self.findChild(QComboBox, 'cbInterval')
        self.dteStartDate = self.findChild(QDateTimeEdit, 'dteStartDate')
        self.dteEndDate = self.findChild(QDateTimeEdit, 'dteEndDate')
        self.listQueryList = self.findChild(QListWidget, 'listQueryList')
        self.btnAddQuery = self.findChild(QPushButton, 'btnAddQuery')
        self.btnRemoveQuery = self.findChild(QPushButton, 'btnRemoveQuery')
        self.btnSaveQuickLook = self.findChild(QPushButton, 'btnSaveQuickLook')
        self.cbQuickLook = self.findChild(QComboBox, 'cbQuickLook')
        self.btnLoadQuickLook = self.findChild(QPushButton, 'btnLoadQuickLook')
        self.btnDeleteQuickLook = self.findChild(QPushButton, 'btnDeleteQuickLook')
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery')
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo')
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo')
        self.rbCustomDateTime = self.findChild(QRadioButton, 'rbCustomDateTime')
        self.rbPrevDayToCurrent = self.findChild(QRadioButton, 'rbPrevDayToCurrent')
        self.rbPrevWeekToCurrent = self.findChild(QRadioButton, 'rbPrevWeekToCurrent')
        self.chkbDelta = self.findChild(QCheckBox, 'chkbDelta')
        self.chkbOverlay = self.findChild(QCheckBox, 'chkbOverlay')
        self.btnUpMax = self.findChild(QPushButton, 'btnUpMax')
        self.btnUp15 = self.findChild(QPushButton, 'btnUp15')
        self.btnUp5 = self.findChild(QPushButton, 'btnUp5')
        self.btnUp1 = self.findChild(QPushButton, 'btnUp1')
        self.btnDownMax = self.findChild(QPushButton, 'btnDownMax')
        self.btnDown15 = self.findChild(QPushButton, 'btnDown15')
        self.btnDown5 = self.findChild(QPushButton, 'btnDown5')
        self.btnDown1 = self.findChild(QPushButton, 'btnDown1')
        self.btnSearch.clicked.connect(self.showSearch)
        self.btnQueryOptionsInfo = self.findChild(QPushButton, 'btnQueryOptionsInfo')
        self.uiSearch = None

        # Group radio buttons
        self.radioGroup = QButtonGroup(self)
        self.radioGroup.addButton(self.rbCustomDateTime)
        self.radioGroup.addButton(self.rbPrevDayToCurrent)
        self.radioGroup.addButton(self.rbPrevWeekToCurrent)

        # Populate interval combobox
        self.cbInterval.addItem('HOUR')
        self.cbInterval.addItem('INSTANT:1')
        self.cbInterval.addItem('INSTANT:15')
        self.cbInterval.addItem('INSTANT:60')
        self.cbInterval.addItem('DAY')
        self.cbInterval.addItem('MONTH')
        self.cbInterval.addItem('YEAR')
        self.cbInterval.addItem('WATER YEAR')

        # Add blank combobox item
        self.cbDatabase.addItem('')

        # Map button style
        buttonIcons = [
                        (self.btnDataIdInfo, "Info", 24),
                        (self.btnIntervalInfo, "Info", 24),
                        (self.btnUpMax, "Up-MAX", 24),
                        (self.btnUp15, "Up-15", 24),
                        (self.btnUp5, "Up-5", 24),
                        (self.btnUp1, "Up-1", 24),
                        (self.btnDownMax, "Down-MAX", 24),
                        (self.btnDown15, "Down-15", 24),
                        (self.btnRemoveQuery, "Delete", 24),
                        (self.btnDown5, "Down-5", 24),
                        (self.btnDown1, "Down-1", 24),
                        (self.btnSearch, "Search", 24),
                        (self.btnQueryOptionsInfo, "Info", 24)
                      ]

        # Set button style        
        for btn, iconName, iconSize in buttonIcons:
            if btn:
                Utils.buttonStyle(btn, iconName, iconSize=iconSize)

        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed)
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed)
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed)
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed) 
        self.btnDeleteQuickLook.clicked.connect(self.btnDeleteQuickLookPressed)
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed)
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed)
        self.radioGroup.buttonClicked.connect(lambda btn: Logic.setQueryDateRange(self, btn, self.dteStartDate, self.dteEndDate))
        self.btnUpMax.clicked.connect(self.btnUpMaxPressed)
        self.btnUp15.clicked.connect(self.btnUp15Pressed)
        self.btnUp5.clicked.connect(self.btnUp5Pressed)
        self.btnUp1.clicked.connect(self.btnUp1Pressed)
        self.btnDownMax.clicked.connect(self.btnDownMaxPressed)
        self.btnDown15.clicked.connect(self.btnDown15Pressed)
        self.btnDown5.clicked.connect(self.btnDown5Pressed)
        self.btnDown1.clicked.connect(self.btnDown1Pressed)
        self.btnQueryOptionsInfo.clicked.connect(self.btnQueryOptionsInfoPressed)

        # Install event filters
        self.qleDataID.installEventFilter(self)
        self.installEventFilter(self)

        # Set initial state
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

        if Config.debug:
            Logic.logMessage("DEBUG", "uiQuery initialized")

    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", "uiQuery showEvent: queryType={}".format(self.queryType))
        Utils.centerWindowToParent(self)
        Logic.loadLastQuickLook(self.cbQuickLook)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)

        # Populate database combobox
        Utils.loadDatabase(self.cbDatabase, self.queryType)

        # Set window icon and title based on queryType
        if self.queryType == 'public':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/PublicQuery.png')))
            self.setWindowTitle("Public Query")

            if Config.debug:
                Logic.logMessage("DEBUG", "uiQuery showEvent: Set window icon to PublicQuery.png and title to Public Query")
        elif self.queryType == 'internal':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/InternalQuery.png')))
            self.setWindowTitle("Internal Query")

            if Config.debug:
                Logic.logMessage("DEBUG", "uiQuery showEvent: Set window icon to InternalQuery.png and title to Internal Query")
        else:
            Logic.logMessage("WARN", "uiQuery showEvent: queryType not set, defaulting to public")

            self.queryType = 'public'
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/PublicQuery.png')))
            self.setWindowTitle("Public Query")
        super().showEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            if Config.debug:
                Logic.logMessage("DEBUG", "qleDataID focus in, setting Add Query default")
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery)
        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            if Config.debug:
                Logic.logMessage("DEBUG", "qleDataID focus out, setting Query Data default")
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if Config.debug:
                Logic.logMessage("DEBUG", "Enter key pressed")
            if self.qleDataID.hasFocus():
                if Config.debug:
                    Logic.logMessage("DEBUG", "qleDataID focused, triggering btnAddQueryPressed")
                self.btnAddQueryPressed()
            elif self.btnQuery.isDefault():
                if Config.debug:
                    Logic.logMessage("DEBUG", "btnQuery is default, triggering btnQueryPressed")
                self.btnQueryPressed()
            return True
        return super().eventFilter(obj, event)

    def btnQueryPressed(self):
        if Config.debug:
            Logic.logMessage("DEBUG", "btnQueryPressed: Starting query process, queryType={}".format(self.queryType))
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm')
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm')
        queryItems = []

        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Config.debug:
                Logic.logMessage("DEBUG", f"Item text: '{itemText}', parts: {parts}, len: {len(parts)}")
            if len(parts) != 3:
                Logic.logMessage("WARN", f"Invalid item skipped: {itemText}")
                continue

            dataId, interval, database = parts
            mrid = '0'
            sdid = dataId

            if database.startswith('USBR-') and '-' in dataId:
                sdid, mrid = dataId.rsplit('-', 1)
            queryItems.append((dataId, interval, database, mrid, i))

            if Config.debug:
                Logic.logMessage("DEBUG", f"Added queryItem: {(dataId, interval, database, mrid, i)}")
        if not queryItems and self.qleDataID.text().strip():
            dataId = self.qleDataID.text().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'
            sdid = dataId

            if database.startswith('USBR-') and '-' in dataId:
                sdid, mrid = dataId.rsplit('-', 1)
            queryItems.append((dataId, interval, database, mrid, 0))

            if Config.debug:
                Logic.logMessage("DEBUG", f"Added single query: {(dataId, interval, database, mrid, 0)}")
        elif not queryItems:
            Logic.logMessage("WARN", "No valid query items.")
            return
        deltaChecked = self.chkbDelta.isChecked()
        overlayChecked = self.chkbOverlay.isChecked()

        if self.winMain:
            self.winMain.lastQueryType = self.queryType
            self.winMain.lastQueryItems = queryItems
            self.winMain.lastStartDate = startDate
            self.winMain.lastEndDate = endDate
            self.winMain.lastDatabase = self.cbDatabase.currentText() if not queryItems else None
            self.winMain.lastInterval = self.cbInterval.currentText() if not queryItems else None

            if Config.debug:
                Logic.logMessage("DEBUG", "Stored last query as {}".format(self.queryType))
            Query.executeQuery(self.winMain, queryItems, startDate, endDate,
                              self.queryType == 'internal', self.winMain.winDataDictionary.mainTable, deltaChecked, overlayChecked)
            self.close()

            if Config.debug:
                Logic.logMessage("DEBUG", "Query window closed after query.")

    def btnSaveQuickLookPressed(self):
        if Config.debug:
            Logic.logMessage("DEBUG", "btnSaveQuickLookPressed: Attempting to save Quick Look")
        if self.listQueryList.count() == 0:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnSaveQuickLookPressed: Empty query list, showing warning")
            QMessageBox.warning(self, "Empty Query List", "Cannot save Quick Look: No items in the query list.")
            return        
        name, ok = QInputDialog.getText(self, "Save Quick Look", "Quick Look name:")

        if ok and name:
            Logic.saveQuickLook(name, self.listQueryList)
            Utils.loadQuickLooks(self.cbQuickLook)

            if Config.debug:
                Logic.logMessage("DEBUG", f"btnSaveQuickLookPressed: Saved '{name}' and reloaded combo box")

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)
        configPath = Utils.getConfigPath()
        config = {}
        
        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Loaded config: {config}")
            except Exception as e:
                Logic.logMessage("ERROR", f"Failed to load user.config: {e}")
        config['lastQuickLook'] = self.cbQuickLook.currentText()

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2)
        if Config.debug:
            Logic.logMessage("DEBUG", f"Loaded quick look: {self.cbQuickLook.currentText()}")

    def btnDeleteQuickLookPressed(self):
        quickLookName = self.cbQuickLook.currentText()

        if not quickLookName:
            if Logic.Config.debug:
                Logic.logMessage("DEBUG", "btnDeleteQuickLookPressed: No Quick Look selected to delete")
            return
        
        # Confirm deletion with user
        reply = QMessageBox.question(self, "Delete Quick Look", f"Are you sure you want to delete '{quickLookName}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.No:
            return        
        deleted = Logic.deleteQuickLook(quickLookName)

        if deleted:
            currentIndex = self.cbQuickLook.currentIndex()
            self.cbQuickLook.removeItem(currentIndex)
            self.cbQuickLook.setCurrentIndex(-1)
            
            if Logic.Config.debug:
                Logic.logMessage("DEBUG", f"btnDeleteQuickLookPressed: Removed '{quickLookName}' from combo box and cleared selection")
        else:
            QMessageBox.warning(self, "Cannot Delete", "Example Quick Looks cannot be deleted.")
            if Logic.Config.debug:
                Logic.logMessage("DEBUG", f"btnDeleteQuickLookPressed: Attempted to delete example Quick Look '{quickLookName}'—skipped")

    def btnAddQueryPressed(self):
        dataID = self.qleDataID.text().strip()
        interval = self.cbInterval.currentText()
        database = self.cbDatabase.currentText()

        if not dataID:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnAddQueryPressed: No Data ID entered, skipping")
            return

        itemText = f"{dataID}|{interval}|{database}"
        self.listQueryList.addItem(itemText)
        self.qleDataID.clear()
        self.qleDataID.setFocus()
        self.listQueryList.scrollToBottom()

        if Config.debug:
            Logic.logMessage("DEBUG", f"btnAddQueryPressed: Added item: {itemText}")

    def btnRemoveQueryPressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnRemoveQueryPressed: No items selected, skipping")
            return
        for item in selectedItems:
            self.listQueryList.takeItem(self.listQueryList.row(item))
        if Config.debug:
            Logic.logMessage("DEBUG", f"btnRemoveQueryPressed: Removed {len(selectedItems)} items")

    def btnClearQueryPressed(self):
        self.listQueryList.clear()
        if Config.debug:
            Logic.logMessage("DEBUG", "btnClearQueryPressed: Cleared query list")

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", "AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter")
        if Config.debug:
            Logic.logMessage("DEBUG", "Data ID info displayed")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")
        if Config.debug:
            Logic.logMessage("DEBUG", "Interval info displayed")

    def btnUpMaxPressed(self):
        selectedItems = self.listQueryList.selectedItems()
        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUpMaxPressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)

            if currentRow == 0:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUpMaxPressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(0, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUpMaxPressed: Moved selected items to top")

    def btnUp15Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUp15Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 15)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUp15Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUp15Pressed: Moved selected items up by 15")

    def btnUp5Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUp5Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 5)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUp5Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUp5Pressed: Moved selected items up by 5")

    def btnUp1Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUp1Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 1)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUp1Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUp1Pressed: Moved selected items up by 1")

    def btnDownMaxPressed(self):
        selectedItems = self.listQueryList.selectedItems()
        
        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDownMaxPressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)

            if currentRow == bottomRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDownMaxPressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.addItem(item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDownMaxPressed: Moved selected items to bottom")

    def btnDown15Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDown15Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 15)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDown15Pressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDown15Pressed: Moved selected items down by 15")

    def btnDown5Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDown5Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 5)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDown5Pressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDown5Pressed: Moved selected items down by 5")

    def btnDown1Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDown1Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 1)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDown1Pressed: Item at row {currentRow} already at bottom")
                continue
            
            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDown1Pressed: Moved selected items down by 1")

    def btnQueryOptionsInfoPressed(self):
        QMessageBox.information(self, "Query Options Info",
                                "Delta: Calculate and display the change between consecutive values.\n\nOverlay: Display multiple datasets in a single view for comparison.")
        if Config.debug:
            Logic.logMessage("DEBUG", "btnQueryOptionsInfoPressed: Showed Query Options info dialog")

    def showSearch(self):
        if self.uiSearch is None:
            self.uiSearch = uiSearch(self)
        self.uiSearch.show()

        if Config.debug:
            Logic.logMessage("DEBUG", "showSearch: Opened uiSearch window")