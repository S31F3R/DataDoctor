import json
import os
from PyQt6.QtWidgets import QMainWindow, QLineEdit, QComboBox, QDateTimeEdit, QListWidget, QPushButton, QRadioButton, QButtonGroup, QCheckBox, QMessageBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QEvent
from PyQt6 import uic
from core import Logic, Query, Utils, Config

class uiQuery(QMainWindow):
    """Query window: Builds and executes public/internal API calls."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        ui_path = Logic.resourcePath('ui/winQuery.ui')

        if Config.debug:
            print(f"[DEBUG] Loading UI file: {ui_path}")
            if not os.path.exists(ui_path):
                print(f"[ERROR] UI file not found: {ui_path}")
        try:
            uic.loadUi(ui_path, self)
        except Exception as e:
            if Config.debug:
                print(f"[ERROR] Failed to load UI file: {e}")
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
        self.btnSearch = self.findChild(QPushButton, 'btnSearch')
        self.btnQueryOptionsInfo = self.findChild(QPushButton, 'btnQueryOptionsInfo')

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

        # Set button style
        for btn in [self.btnDataIdInfo, self.btnIntervalInfo, self.btnUpMax, self.btnUp15,
                    self.btnUp5, self.btnUp1, self.btnDownMax, self.btnDown15,
                    self.btnDown5, self.btnDown1, self.btnSearch, self.btnQueryOptionsInfo]:
            if btn:
                Utils.buttonStyle(btn)

        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed)
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed)
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed)
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)
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
        self.btnSearch.clicked.connect(self.btnSearchPressed)
        self.btnQueryOptionsInfo.clicked.connect(self.btnQueryOptionsInfoPressed)

        # Install event filters
        self.qleDataID.installEventFilter(self)
        self.installEventFilter(self)

        # Set initial state
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

        if Config.debug:
            print("[DEBUG] uiQuery initialized")

    def showEvent(self, event):
        if Config.debug:
            print("[DEBUG] uiQuery showEvent: queryType={}".format(self.queryType))
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
                print("[DEBUG] uiQuery showEvent: Set window icon to PublicQuery.png and title to Public Query")
        elif self.queryType == 'internal':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/InternalQuery.png')))
            self.setWindowTitle("Internal Query")

            if Config.debug:
                print("[DEBUG] uiQuery showEvent: Set window icon to InternalQuery.png and title to Internal Query")
        else:
            if Config.debug:
                print("[WARN] uiQuery showEvent: queryType not set, defaulting to public")

            self.queryType = 'public'
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/PublicQuery.png')))
            self.setWindowTitle("Public Query")
        super().showEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            if Config.debug:
                print("[DEBUG] qleDataID focus in, setting Add Query default")
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery)
        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            if Config.debug:
                print("[DEBUG] qleDataID focus out, setting Query Data default")
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if Config.debug:
                print("[DEBUG] Enter key pressed")
            if self.qleDataID.hasFocus():
                if Config.debug:
                    print("[DEBUG] qleDataID focused, triggering btnAddQueryPressed")
                self.btnAddQueryPressed()
            elif self.btnQuery.isDefault():
                if Config.debug:
                    print("[DEBUG] btnQuery is default, triggering btnQueryPressed")
                self.btnQueryPressed()
            return True
        return super().eventFilter(obj, event)

    def btnQueryPressed(self):
        if Config.debug:
            print("[DEBUG] btnQueryPressed: Starting query process, queryType={}".format(self.queryType))
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm')
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm')
        queryItems = []

        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Config.debug:
                print(f"[DEBUG] Item text: '{itemText}', parts: {parts}, len: {len(parts)}")
            if len(parts) != 3:
                print(f"[WARN] Invalid item skipped: {itemText}")
                continue

            dataId, interval, database = parts
            mrid = '0'
            sdid = dataId

            if database.startswith('USBR-') and '-' in dataId:
                sdid, mrid = dataId.rsplit('-', 1)
            queryItems.append((dataId, interval, database, mrid, i))

            if Config.debug:
                print(f"[DEBUG] Added queryItem: {(dataId, interval, database, mrid, i)}")
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
                print(f"[DEBUG] Added single query: {(dataId, interval, database, mrid, 0)}")
        elif not queryItems:
            print("[WARN] No valid query items.")
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
                print("[DEBUG] Stored last query as {}".format(self.queryType))
            Query.executeQuery(self.winMain, queryItems, startDate, endDate,
                              self.queryType == 'internal', self.winMain.winDataDictionary.mainTable, deltaChecked, overlayChecked)
            self.close()

            if Config.debug:
                print("[DEBUG] Query window closed after query.")

    def btnSaveQuickLookPressed(self):
        if Config.debug:
            print("[DEBUG] btnSaveQuickLookPressed: Attempting to open Save Quick Look dialog")
        if self.listQueryList.count() == 0:
            if Config.debug:
                print("[DEBUG] btnSaveQuickLookPressed: Empty query list, showing warning")
            QMessageBox.warning(self, "Empty Query List", "Cannot save Quick Look: No items in the query list.")
            return
        if self.winMain:
            self.winMain.winQuickLook.currentListQueryList = self.listQueryList
            self.winMain.winQuickLook.CurrentCbQuickLook = self.cbQuickLook
            self.winMain.winQuickLook.exec()
            self.raise_()
            self.activateWindow()

            if Config.debug:
                print("[DEBUG] btnSaveQuickLookPressed: Save Quick Look dialog opened and closed")

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)
        configPath = Utils.getConfigPath()
        config = {}
        
        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    print(f"[DEBUG] Loaded config: {config}")
            except Exception as e:
                if Config.debug:
                    print(f"[ERROR] Failed to load user.config: {e}")
        config['lastQuickLook'] = self.cbQuickLook.currentText()

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2)
        if Config.debug:
            print(f"[DEBUG] Loaded quick look: {self.cbQuickLook.currentText()}")

    def btnAddQueryPressed(self):
        dataID = self.qleDataID.text().strip()
        interval = self.cbInterval.currentText()
        database = self.cbDatabase.currentText()

        if not dataID:
            if Config.debug:
                print("[DEBUG] btnAddQueryPressed: No Data ID entered, skipping")
            return

        itemText = f"{dataID}|{interval}|{database}"
        self.listQueryList.addItem(itemText)
        self.qleDataID.clear()
        self.qleDataID.setFocus()
        self.listQueryList.scrollToBottom()

        if Config.debug:
            print(f"[DEBUG] btnAddQueryPressed: Added item: {itemText}")

    def btnRemoveQueryPressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnRemoveQueryPressed: No items selected, skipping")
            return
        for item in selectedItems:
            self.listQueryList.takeItem(self.listQueryList.row(item))
        if Config.debug:
            print(f"[DEBUG] btnRemoveQueryPressed: Removed {len(selectedItems)} items")

    def btnClearQueryPressed(self):
        self.listQueryList.clear()
        if Config.debug:
            print("[DEBUG] btnClearQueryPressed: Cleared query list")

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", "AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter")
        if Config.debug:
            print("[DEBUG] Data ID info displayed")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")
        if Config.debug:
            print("[DEBUG] Interval info displayed")

    def btnUpMaxPressed(self):
        selectedItems = self.listQueryList.selectedItems()
        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnUpMaxPressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)

            if currentRow == 0:
                if Config.debug:
                    print(f"[DEBUG] btnUpMaxPressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(0, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnUpMaxPressed: Moved selected items to top")

    def btnUp15Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnUp15Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 15)

            if currentRow == newRow:
                if Config.debug:
                    print(f"[DEBUG] btnUp15Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnUp15Pressed: Moved selected items up by 15")

    def btnUp5Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnUp5Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 5)

            if currentRow == newRow:
                if Config.debug:
                    print(f"[DEBUG] btnUp5Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnUp5Pressed: Moved selected items up by 5")

    def btnUp1Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnUp1Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 1)

            if currentRow == newRow:
                if Config.debug:
                    print(f"[DEBUG] btnUp1Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnUp1Pressed: Moved selected items up by 1")

    def btnDownMaxPressed(self):
        selectedItems = self.listQueryList.selectedItems()
        
        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnDownMaxPressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)

            if currentRow == bottomRow:
                if Config.debug:
                    print(f"[DEBUG] btnDownMaxPressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.addItem(item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnDownMaxPressed: Moved selected items to bottom")

    def btnDown15Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnDown15Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 15)

            if currentRow == newRow:
                if Config.debug:
                    print(f"[DEBUG] btnDown15Pressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnDown15Pressed: Moved selected items down by 15")

    def btnDown5Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnDown5Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 5)

            if currentRow == newRow:
                if Config.debug:
                    print(f"[DEBUG] btnDown5Pressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnDown5Pressed: Moved selected items down by 5")

    def btnDown1Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                print("[DEBUG] btnDown1Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 1)

            if currentRow == newRow:
                if Config.debug:
                    print(f"[DEBUG] btnDown1Pressed: Item at row {currentRow} already at bottom")
                continue
            
            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            print("[DEBUG] btnDown1Pressed: Moved selected items down by 1")

    def btnSearchPressed(self):
        if Config.debug:
            print("[DEBUG] btnSearchPressed: Search functionality not implemented")
        QMessageBox.information(self, "Search", "Search functionality is not yet implemented.")

    def btnQueryOptionsInfoPressed(self):
        QMessageBox.information(self, "Query Options Info",
                                "Delta: Calculate and display the change between consecutive values.\n\nOverlay: Display multiple datasets in a single view for comparison.")
        if Config.debug:
            print("[DEBUG] btnQueryOptionsInfoPressed: Showed Query Options info dialog")