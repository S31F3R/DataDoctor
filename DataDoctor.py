import sys
import Logic
import keyring
import os
import json
from keyring.backends.null import Keyring as NullKeyring
from datetime import datetime
from PyQt6.QtGui import QGuiApplication, QIcon, QFont, QFontDatabase, QPixmap
from PyQt6.QtCore import Qt, QEvent, QTimer, QUrl
from PyQt6 import uic
from PyQt6.QtMultimedia import QSoundEffect
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QVBoxLayout,
                            QComboBox, QDateTimeEdit, QListWidget, QWidget, QGridLayout,
                            QMessageBox, QDialog, QSizePolicy, QTabWidget, QRadioButton, QButtonGroup,
                            QDialogButtonBox, QLineEdit, QLabel, QTextBrowser, QCheckBox, QMenu)

class uiMain(QMainWindow):
    """Main window for DataDoctor: Handles core UI, queries, and exports."""
    def __init__(self):
        super(uiMain, self).__init__()
        uic.loadUi(Logic.resourcePath('ui/winMain.ui'), self)

        # Load stylesheet
        with open(Logic.resourcePath('ui/stylesheet.qss'), 'r') as f:
            app.setStyleSheet(f.read())

        # Define the controls
        self.btnPublicQuery = self.findChild(QPushButton, 'btnPublicQuery')
        self.mainTable = self.findChild(QTableWidget, 'mainTable')
        self.btnDataDictionary = self.findChild(QPushButton, 'btnDataDictionary')
        self.btnExportCSV = self.findChild(QPushButton, 'btnExportCSV')
        self.btnOptions = self.findChild(QPushButton, 'btnOptions')
        self.btnInfo = self.findChild(QPushButton, 'btnInfo')
        self.btnInternalQuery = self.findChild(QPushButton, 'btnInternalQuery')
        self.btnRefresh = self.findChild(QPushButton, 'btnRefresh')
        self.btnUndo = self.findChild(QPushButton, 'btnUndo')
        self.lastQueryType = None
        self.lastQueryItems = []
        self.lastStartDate = None
        self.lastEndDate = None

        # Set button style
        Logic.buttonStyle(self.btnPublicQuery)
        Logic.buttonStyle(self.btnDataDictionary)
        Logic.buttonStyle(self.btnExportCSV)
        Logic.buttonStyle(self.btnOptions)
        Logic.buttonStyle(self.btnInfo)
        Logic.buttonStyle(self.btnInternalQuery)
        Logic.buttonStyle(self.btnUndo)
        Logic.buttonStyle(self.btnRefresh)

        # Set base layout
        centralLayout = self.centralWidget().layout()

        # Set up stretch for central grid layout
        if isinstance(centralLayout, QGridLayout):
            centralLayout.setContentsMargins(0, 0, 0, 0)
            centralLayout.setRowStretch(0, 0)
            centralLayout.setRowStretch(1, 1)
            centralLayout.setColumnStretch(0, 1)

        # Create events
        self.btnPublicQuery.clicked.connect(self.btnPublicQueryPressed)
        self.btnDataDictionary.clicked.connect(self.showDataDictionary)
        self.btnExportCSV.clicked.connect(self.btnExportCSVPressed)
        self.btnOptions.clicked.connect(self.btnOptionsPressed)
        self.btnInfo.clicked.connect(self.btnInfoPressed)
        self.btnInternalQuery.clicked.connect(self.btnInternalQueryPressed)
        self.btnRefresh.clicked.connect(self.btnRefreshPressed)
        self.btnUndo.clicked.connect(self.btnUndoPressed)
        self.mainTable.horizontalHeader().sectionClicked.connect(lambda col: Logic.customSortTable(self.mainTable, col, winDataDictionary.mainTable))
        self.mainTable.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainTable.horizontalHeader().customContextMenuRequested.connect(self.showHeaderContextMenu)
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
        self.tabWidget.tabCloseRequested.connect(self.onTabCloseRequested) # Connect close button signal
        self.tabMain = self.findChild(QWidget, 'tabMain')

        # Ensure tab widget expands        
        if self.tabWidget:
            self.tabWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)        
        
        # Set up Data Query tab        
        if self.tabMain:
            self.tabMain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            if not self.tabMain.layout():
                layout = QVBoxLayout(self.tabMain)
                layout.addWidget(self.mainTable)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

        self.mainTable.setGeometry(0, 0, 0, 0)
        self.mainTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Hide tabs on startup
        if self.tabWidget:
            dataQueryIndex = self.tabWidget.indexOf(self.tabMain)

            if dataQueryIndex != -1:
                self.tabWidget.removeTab(dataQueryIndex)

            sqlTab = self.findChild(QWidget, 'tabSQL')
            sqlIndex = self.tabWidget.indexOf(sqlTab)

            if sqlIndex != -1:
                self.tabWidget.removeTab(sqlIndex)

        # Center window
        rect = self.frameGeometry()
        centerPoint = QGuiApplication.primaryScreen().availableGeometry().center()
        rect.moveCenter(centerPoint)
        self.move(rect.topLeft())
        self.show()

        if Logic.debug:
            print("[DEBUG] uiMain initialized with header context menu")

    def showHeaderContextMenu(self, pos):
        header = self.mainTable.horizontalHeader()
        col = header.logicalIndexAt(pos)

        if col < 0 or col >= len(self.lastQueryItems):
            if Logic.debug:
                print("[DEBUG] showHeaderContextMenu: Invalid column {} clicked".format(col))
            return

        queryInfo = f"{self.lastQueryItems[col][0]}|{self.lastQueryItems[col][1]}|{self.lastQueryItems[col][2]}"
        menu = QMenu(self)
        action = menu.addAction("Show Query Info")
        action.triggered.connect(lambda: self.showDataIdMessage(queryInfo))
        menu.exec(header.mapToGlobal(pos))

        if Logic.debug: print("[DEBUG] showHeaderContextMenu: Displayed menu for column {}, queryInfo {}".format(col, queryInfo))

    def showDataIdMessage(self, queryInfo):
        QMessageBox.information(self, "Full Query Info", queryInfo)
        if Logic.debug: print("[DEBUG] showDataIdMessage: Showed queryInfo {}".format(queryInfo))

    def onTabCloseRequested(self, index):
        if self.tabWidget: self.tabWidget.removeTab(index)

    def btnPublicQueryPressed(self):
        winQuery.queryType = 'public'
        winQuery.show()
        if Logic.debug: print("[DEBUG] btnPublicQueryPressed: Opened uiQuery as public")

    def btnInternalQueryPressed(self):
        winQuery.queryType = 'internal'
        winQuery.show()
        if Logic.debug: print("[DEBUG] btnInternalQueryPressed: Opened uiQuery as internal")

    def btnOptionsPressed(self):
        winOptions.exec()

    def btnInfoPressed(self):
        winAbout.exec()

    def showDataDictionary(self):
        winDataDictionary.show()

    def btnExportCSVPressed(self):
        Logic.exportTableToCSV(self.mainTable, '', '')

    def exitPressed(self):
        app.exit()

    def btnRefreshPressed(self):
        if Logic.debug: print("[DEBUG] btnRefreshPressed: Starting refresh process.")

        if not self.lastQueryType:
            if Logic.debug:
                print("[DEBUG] No last query to refresh.")
            return

        now = datetime.now()
        endDateTime = datetime.strptime(self.lastEndDate, '%Y-%m-%d %H:%M')
        
        if endDateTime.date() == now.date():
            self.lastEndDate = now.strftime('%Y-%m-%d %H:%M')

            if Logic.debug:
                print(f"[DEBUG] Updated end date to current: {self.lastEndDate}")

        Logic.executeQuery(self, self.lastQueryItems, self.lastStartDate, self.lastEndDate, self.lastQueryType == 'internal', winDataDictionary.mainTable)

    def btnUndoPressed(self):
        if Logic.debug: print("[DEBUG] btnUndoPressed: Resetting to timestamp sort.")
        Logic.timestampSortTable(self.mainTable, winDataDictionary.mainTable)

class uiQuery(QMainWindow):
    """Query window: Builds and executes database calls for public or internal queries."""
    def __init__(self, parent=None):
        super(uiQuery, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winQuery.ui'), self)
        self.queryType = None # 'public' or 'internal'

        # Define controls
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
        self.cbDelta = self.findChild(QCheckBox, 'cbDelta')
        self.cbOverlay = self.findChild(QCheckBox, 'cbOverlay')
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

        # Set button style
        Logic.buttonStyle(self.btnDataIdInfo)
        Logic.buttonStyle(self.btnIntervalInfo)
        Logic.buttonStyle(self.btnUpMax)
        Logic.buttonStyle(self.btnUp15)
        Logic.buttonStyle(self.btnUp5)
        Logic.buttonStyle(self.btnUp1)
        Logic.buttonStyle(self.btnDownMax)
        Logic.buttonStyle(self.btnDown15)
        Logic.buttonStyle(self.btnDown5)
        Logic.buttonStyle(self.btnDown1)
        Logic.buttonStyle(self.btnSearch)
        Logic.buttonStyle(self.btnQueryOptionsInfo)

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

        # Populate interval combobox
        self.cbInterval.addItem('HOUR')
        self.cbInterval.addItem('INSTANT:1')
        self.cbInterval.addItem('INSTANT:15')
        self.cbInterval.addItem('INSTANT:60')
        self.cbInterval.addItem('DAY')
        self.cbInterval.addItem('MONTH')
        self.cbInterval.addItem('YEAR')
        self.cbInterval.addItem('WATER YEAR')

        # Set initial state
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)
        if Logic.debug: print("[DEBUG] uiQuery initialized")

    def showEvent(self, event):
        if Logic.debug: print("[DEBUG] uiQuery showEvent: queryType={}".format(self.queryType))
        Logic.centerWindowToParent(self)
        Logic.loadLastQuickLook(self.cbQuickLook)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)

        # Populate database combobox based on queryType
        self.cbDatabase.clear()
        databases = [
            'USBR-LCHDB',
            'USBR-YAOHDB',
            'USBR-UCHDB2',
            'USBR-ECOHDB',
            'USBR-LBOHDB',
            'USBR-KBOHDB',
            'USBR-PNHYD',
            'USBR-GPHYD',
            'USGS-NWIS'
        ]

        if self.queryType == 'internal': databases.insert(0, 'AQUARIUS')
        for db in databases: self.cbDatabase.addItem(db)
        if Logic.debug: print("[DEBUG] uiQuery showEvent: Populated cbDatabase with {} items".format(self.cbDatabase.count()))

        # Set window icon based on queryType
        if self.queryType == 'public':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/PublicQuery.png')))
            if Logic.debug: print("[DEBUG] uiQuery showEvent: Set window icon to PublicQuery.png")
        elif self.queryType == 'internal':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/InternalQuery.png')))
            if Logic.debug: print("[DEBUG] uiQuery showEvent: Set window icon to InternalQuery.png")

        super().showEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            if Logic.debug: print("[DEBUG] qleDataID focus in, setting Add Query default")
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery)
        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            if Logic.debug: print("[DEBUG] qleDataID focus out, setting Query Data default")
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if Logic.debug: print("[DEBUG] Enter key pressed")
            if self.qleDataID.hasFocus():
                if Logic.debug: print("[DEBUG] qleDataID focused, triggering btnAddQueryPressed")
                self.btnAddQueryPressed()
            elif self.btnQuery.isDefault():
                if Logic.debug: print("[DEBUG] btnQuery is default, triggering btnQueryPressed")
                self.btnQueryPressed()
            return True

        return super().eventFilter(obj, event)

    def btnQueryPressed(self):
        if Logic.debug: print("[DEBUG] btnQueryPressed: Starting query process, queryType={}".format(self.queryType))
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm')
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm')
        queryItems = []

        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Logic.debug: print(f"[DEBUG] Item text: '{itemText}', parts: {parts}, len: {len(parts)}")
            if len(parts) != 3:
                print(f"[WARN] Invalid item skipped: {itemText}")
                continue

            dataID, interval, database = parts
            mrid = '0'
            SDID = dataID
            if database.startswith('USBR-') and '-' in dataID: SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, i))
            if Logic.debug: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        if not queryItems and self.qleDataID.text().strip():
            dataID = self.qleDataID.text().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'
            SDID = dataID
            if database.startswith('USBR-') and '-' in dataID: SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, 0))
            if Logic.debug: print(f"[DEBUG] Added single query: {(dataID, interval, database, mrid, 0)}")
        elif not queryItems:
            print("[WARN] No valid query items.")
            return

        winMain.lastQueryType = self.queryType
        winMain.lastQueryItems = queryItems
        winMain.lastStartDate = startDate
        winMain.lastEndDate = endDate
        winMain.lastDatabase = self.cbDatabase.currentText() if not queryItems else None
        winMain.lastInterval = self.cbInterval.currentText() if not queryItems else None
        if Logic.debug: print("[DEBUG] Stored last query as {}".format(self.queryType))
        Logic.executeQuery(winMain, queryItems, startDate, endDate, self.queryType == 'internal', winDataDictionary.mainTable)
        self.close()
        if Logic.debug: print("[DEBUG] Query window closed after query.")

    def btnAddQueryPressed(self):
        item = f'{self.qleDataID.text().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}'
        self.listQueryList.addItem(item)
        self.qleDataID.clear()
        self.qleDataID.setFocus()
        self.listQueryList.scrollToBottom()
        if Logic.debug: print(f"[DEBUG] Added query item: {item}, scrolled to bottom")

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()

        if item:
            self.listQueryList.takeItem(self.listQueryList.row(item))
            if Logic.debug: print(f"[DEBUG] Removed query item: {item.text()}")
        else:
            if Logic.debug: print("[DEBUG] No query item selected for removal")

    def btnSaveQuickLookPressed(self):
        winQuickLook.currentListQueryList = self.listQueryList
        winQuickLook.CurrentCbQuickLook = self.cbQuickLook
        winQuickLook.exec()
        self.raise_()
        self.activateWindow()
        if Logic.debug: print("[DEBUG] Save Quick Look dialog opened")

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)
        configPath = Logic.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
            except Exception as e:
                if Logic.debug: print(f"[ERROR] Failed to load user.config: {e}")

        config['lastQuickLook'] = self.cbQuickLook.currentText()
        with open(configPath, 'w', encoding='utf-8') as configFile: json.dump(config, configFile, indent=2)
        if Logic.debug: print(f"[DEBUG] Loaded quick look: {self.cbQuickLook.currentText()}")

    def btnClearQueryPressed(self):
        self.listQueryList.clear()
        if Logic.debug: print("[DEBUG] Query list cleared")

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats",
            "AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter")
        if Logic.debug: print("[DEBUG] Data ID info displayed")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info",
            "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")
        if Logic.debug: print("[DEBUG] Interval info displayed")

    def btnQueryOptionsInfoPressed(self):
        QMessageBox.information(self, "Query Options Info",
            "Deltas and overlay only work on data paris, ex: first and second item in query list = pair 1, second and third item in query list = pair 2.\n\n"
            "Deltas: uses pair groups and adds a column next to them, showing 1st minus 2nd.\n\n"
            "Overlay: uses pair groups and shows them in a single column, 1st being primary, 2nd being secondary.\n"
            "QAQC formatting will be applied, regardless of QAQC setting in options. Cells turn colors based on primary missing but secondary available and differences in 1st and 2nd.")
        if Logic.debug: print("[DEBUG] Query options info displayed")         

    def btnUpMaxPressed(self):
        if Logic.debug: print("[DEBUG] btnUpMaxPressed: Attempting to move item to top")
        currentRow = self.listQueryList.currentRow()
        if currentRow <= 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnUpMaxPressed: No valid item selected or already at top")
            return
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(0, item)
        self.listQueryList.setCurrentRow(0)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print("[DEBUG] btnUpMaxPressed: Moved item to index 0")

    def btnUp15Pressed(self):
        if Logic.debug: print("[DEBUG] btnUp15Pressed: Attempting to move item up 15 rows")
        currentRow = self.listQueryList.currentRow()
        if currentRow < 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnUp15Pressed: No valid item selected")
            return
        newRow = max(0, currentRow - 15)
        if newRow == currentRow:
            if Logic.debug: print("[DEBUG] btnUp15Pressed: Already at top")
            return
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(newRow, item)
        self.listQueryList.setCurrentRow(newRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnUp15Pressed: Moved item from {currentRow} to {newRow}")

    def btnUp5Pressed(self):
        if Logic.debug: print("[DEBUG] btnUp5Pressed: Attempting to move item up 5 rows")
        currentRow = self.listQueryList.currentRow()
        if currentRow < 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnUp5Pressed: No valid item selected")
            return
        newRow = max(0, currentRow - 5)
        if newRow == currentRow:
            if Logic.debug: print("[DEBUG] btnUp5Pressed: Already at top")
            return
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(newRow, item)
        self.listQueryList.setCurrentRow(newRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnUp5Pressed: Moved item from {currentRow} to {newRow}")

    def btnUp1Pressed(self):
        if Logic.debug: print("[DEBUG] btnUp1Pressed: Attempting to move item up 1 row")
        currentRow = self.listQueryList.currentRow()
        if currentRow <= 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnUp1Pressed: No valid item selected or already at top")
            return
        newRow = currentRow - 1
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(newRow, item)
        self.listQueryList.setCurrentRow(newRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnUp1Pressed: Moved item from {currentRow} to {newRow}")

    def btnDownMaxPressed(self):
        if Logic.debug: print("[DEBUG] btnDownMaxPressed: Attempting to move item to bottom")
        currentRow = self.listQueryList.currentRow()
        if currentRow < 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnDownMaxPressed: No valid item selected")
            return
        lastRow = self.listQueryList.count() - 1
        if currentRow == lastRow:
            if Logic.debug: print("[DEBUG] btnDownMaxPressed: Already at bottom")
            return
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(lastRow, item)
        self.listQueryList.setCurrentRow(lastRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnDownMaxPressed: Moved item from {currentRow} to {lastRow}")

    def btnDown15Pressed(self):
        if Logic.debug: print("[DEBUG] btnDown15Pressed: Attempting to move item down 15 rows")
        currentRow = self.listQueryList.currentRow()
        if currentRow < 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnDown15Pressed: No valid item selected")
            return
        lastRow = self.listQueryList.count() - 1
        newRow = min(lastRow, currentRow + 15)
        if newRow == currentRow:
            if Logic.debug: print("[DEBUG] btnDown15Pressed: Already at bottom")
            return
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(newRow, item)
        self.listQueryList.setCurrentRow(newRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnDown15Pressed: Moved item from {currentRow} to {newRow}")

    def btnDown5Pressed(self):
        if Logic.debug: print("[DEBUG] btnDown5Pressed: Attempting to move item down 5 rows")
        currentRow = self.listQueryList.currentRow()
        if currentRow < 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnDown5Pressed: No valid item selected")
            return
        lastRow = self.listQueryList.count() - 1
        newRow = min(lastRow, currentRow + 5)
        if newRow == currentRow:
            if Logic.debug: print("[DEBUG] btnDown5Pressed: Already at bottom")
            return
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(newRow, item)
        self.listQueryList.setCurrentRow(newRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnDown5Pressed: Moved item from {currentRow} to {newRow}")

    def btnDown1Pressed(self):
        if Logic.debug: print("[DEBUG] btnDown1Pressed: Attempting to move item down 1 row")
        currentRow = self.listQueryList.currentRow()
        if currentRow < 0 or currentRow >= self.listQueryList.count():
            if Logic.debug: print("[DEBUG] btnDown1Pressed: No valid item selected")
            return
        lastRow = self.listQueryList.count() - 1
        if currentRow == lastRow:
            if Logic.debug: print("[DEBUG] btnDown1Pressed: Already at bottom")
            return
        newRow = currentRow + 1
        item = self.listQueryList.takeItem(currentRow)
        self.listQueryList.insertItem(newRow, item)
        self.listQueryList.setCurrentRow(newRow)
        self.listQueryList.scrollToItem(item)
        if Logic.debug: print(f"[DEBUG] btnDown1Pressed: Moved item from {currentRow} to {newRow}")

    def btnSearchPressed(self):
        if Logic.debug: print("[DEBUG] btnSearchPressed: Not implemented")
        pass

class uiDataDictionary(QMainWindow):
    """Data dictionary editor: Manages labels for time-series IDs."""
    def __init__(self, parent=None):
        super(uiDataDictionary, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winDataDictionary.ui'), self)
        self.mainTable = self.findChild(QTableWidget, 'dataDictionaryTable')
        self.btnSave = self.findChild(QPushButton, 'btnSave')
        self.btnAddRow = self.findChild(QPushButton, 'btnAddRow')
        self.btnDeleteRow = self.findChild(QPushButton, 'btnDeleteRow')
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnAddRow.clicked.connect(self.btnAddRowPressed)
        self.btnDeleteRow.clicked.connect(self.btnDeleteRowPressed)
        Logic.buttonStyle(self.btnSave)
        Logic.buttonStyle(self.btnAddRow)
        Logic.buttonStyle(self.btnDeleteRow)
        if Logic.debug: print("[DEBUG] uiDataDictionary initialized with btnDeleteRow")

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self):
        data = []

        with open(Logic.resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
            header = f.readlines()[0].rstrip('\n')
            data.append(header)
            if Logic.debug: print(f"[DEBUG] Appended stripped header: {header}")
        for r in range(self.mainTable.rowCount()):
            rowData = []
            isEmptyRow = True

            for c in range(self.mainTable.columnCount()):
                item = self.mainTable.item(r, c)
                cellText = item.text().strip() if item else ''
                rowData.append(cellText)
                if cellText: isEmptyRow = False
            if not isEmptyRow:
                data.append(','.join(rowData))
                if Logic.debug: print(f"[DEBUG] Saved row {r} with data: {rowData}")
            else:
                if Logic.debug: print(f"[DEBUG] Skipped empty row {r}")

        with open(Logic.resourcePath('DataDictionary.csv'), 'w', encoding='utf-8-sig') as f: f.write('\n'.join(data) + '\n')

        for c in range(self.mainTable.columnCount()): self.mainTable.resizeColumnToContents(c)

        if Logic.debug: print(f"[DEBUG] DataDictionary saved with {len(data)-1} rows and columns resized")

    def btnAddRowPressed(self):
        self.mainTable.setRowCount(self.mainTable.rowCount() + 1)
        self.mainTable.scrollToBottom()
        if Logic.debug: print(f"[DEBUG] Added row to DataDictionary, scrolled to bottom, new row count: {self.mainTable.rowCount()}")

    def btnDeleteRowPressed(self):

        currentRow = self.mainTable.currentRow()
        if currentRow >= 0:
            self.mainTable.removeRow(currentRow)
            if Logic.debug: print(f"[DEBUG] Removed row {currentRow} from DataDictionary, new row count: {self.mainTable.rowCount()}")
        else:
            if Logic.debug: print("[DEBUG] No row selected for removal in DataDictionary")

class uiQuickLook(QDialog):
    """Quick look save dialog: Names and stores query presets."""
    def __init__(self, parent=None):
        super(uiQuickLook, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winQuickLook.ui'), self)
        self.btnSave = self.findChild(QPushButton, 'btnSave')
        self.btnCancel = self.findChild(QPushButton, 'btnCancel')
        self.qleQuickLookName = self.findChild(QLineEdit, 'qleQuickLookName')
        self.currentListQueryList = None
        self.CurrentCbQuickLook = None
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnCancel.clicked.connect(self.btnCancelPressed)
        if Logic.debug: print("[DEBUG] uiQuickLook initialized with QLineEdit qleQuickLookName")

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self):
        if self.currentListQueryList and self.CurrentCbQuickLook:
            if Logic.debug: print("[DEBUG] Saving quick look using currentListQueryList with count:", self.currentListQueryList.count())
            Logic.saveQuickLook(self.qleQuickLookName.text().strip(), self.currentListQueryList)
            Logic.loadAllQuickLooks(winQuery.cbQuickLook)
           
            self.clear()
            winQuickLook.close()
            if Logic.debug: print("[DEBUG] Quick look saved and window closed")

    def btnCancelPressed(self):
        self.clear()
        winQuickLook.close()

    def clear(self):
        self.qleQuickLookName.clear()
        if Logic.debug: print("[DEBUG] Cleared qleQuickLookName")

class uiOptions(QDialog):
    """Options editor: Stores database connection information and application settings."""
    def __init__(self, parent=None):
        super(uiOptions, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winOptions.ui'), self)

        # Define controls
        self.cbUTCOffset = self.findChild(QComboBox, 'cbUTCOffset')
        self.qleAQServer = self.findChild(QLineEdit, 'qleAQServer')
        self.qleAQUser = self.findChild(QLineEdit, 'qleAQUser')
        self.qleAQPassword = self.findChild(QLineEdit, 'qleAQPassword')
        self.qleUSGSAPIKey = self.findChild(QLineEdit, 'qleUSGSAPIKey')
        self.qleTNSNames = self.findChild(QLineEdit, 'qleTNSNames')
        self.rbBOP = self.findChild(QRadioButton, 'rbBOP')
        self.rbEOP = self.findChild(QRadioButton, 'rbEOP')
        self.btnbOptions = self.findChild(QDialogButtonBox, 'btnbOptions')
        self.cbRetroMode = self.findChild(QCheckBox, 'cbRetroMode')
        self.cbQAQC = self.findChild(QCheckBox, 'cbQAQC')
        self.cbRawData = self.findChild(QCheckBox, 'cbRawData')
        self.cbDebug = self.findChild(QCheckBox, 'cbDebug')
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
        self.btnShowPassword = self.findChild(QPushButton, 'btnShowPassword')
        self.btnShowUSGSKey = self.findChild(QPushButton, 'btnShowUSGSKey')
        self.qleOracleUser = self.findChild(QLineEdit, 'qleOracleUser')
        self.qleOraclePassword = self.findChild(QLineEdit, 'qleOraclePassword')
        self.btnShowOraclePassword = self.findChild(QPushButton, 'btnShowOraclePassword')

        # Set button style
        Logic.buttonStyle(self.btnShowPassword)
        Logic.buttonStyle(self.btnShowUSGSKey)
        Logic.buttonStyle(self.btnShowOraclePassword)

        # Timers for password and key show
        self.lastCharTimer = QTimer(self)
        self.lastCharTimer.setSingleShot(True)
        self.lastCharTimer.timeout.connect(self.maskLastChar)
        self.lastCharTimerUSGS = QTimer(self)
        self.lastCharTimerUSGS.setSingleShot(True)
        self.lastCharTimerUSGS.timeout.connect(self.maskLastCharUSGS)
        self.lastCharTimerOracle = QTimer(self)
        self.lastCharTimerOracle.setSingleShot(True)
        self.lastCharTimerOracle.timeout.connect(self.maskLastCharOracle)

        # Create events
        self.btnbOptions.accepted.connect(self.onSavePressed)
        self.btnShowPassword.clicked.connect(self.togglePasswordVisibility)
        self.btnShowUSGSKey.clicked.connect(self.toggleUSGSKeyVisibility)
        self.btnShowOraclePassword.clicked.connect(self.toggleOraclePasswordVisibility)

        # Mask password and key
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)
        self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password)
        self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Password)

        # Install event filters
        self.qleAQPassword.installEventFilter(self)
        self.qleUSGSAPIKey.installEventFilter(self)
        self.qleOraclePassword.installEventFilter(self)

        # Populate UTC offset combobox
        self.cbUTCOffset.addItem("UTC-12:00 | Baker Island")
        self.cbUTCOffset.addItem("UTC-11:00 | American Samoa")
        self.cbUTCOffset.addItem("UTC-10:00 | Hawaii")
        self.cbUTCOffset.addItem("UTC-09:30 | Marquesas Islands")
        self.cbUTCOffset.addItem("UTC-09:00 | Alaska")
        self.cbUTCOffset.addItem("UTC-08:00 | Pacific Time (US & Canada)")
        self.cbUTCOffset.addItem("UTC-07:00 | Mountain Time (US & Canada)/Arizona")
        self.cbUTCOffset.addItem("UTC-06:00 | Central Time (US & Canada)")
        self.cbUTCOffset.addItem("UTC-05:00 | Eastern Time (US & Canada)")
        self.cbUTCOffset.addItem("UTC-04:00 | Atlantic Time (Canada)")
        self.cbUTCOffset.addItem("UTC-03:30 | Newfoundland")
        self.cbUTCOffset.addItem("UTC-03:00 | Brasilia")
        self.cbUTCOffset.addItem("UTC-02:00 | Mid-Atlantic")
        self.cbUTCOffset.addItem("UTC-01:00 | Cape Verde Is.")
        self.cbUTCOffset.addItem("UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London")
        self.cbUTCOffset.addItem("UTC+01:00 | Central European Time : Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna")
        self.cbUTCOffset.addItem("UTC+02:00 | Eastern European Time : Athens, Bucharest, Istanbul")
        self.cbUTCOffset.addItem("UTC+03:00 | Moscow, St. Petersburg, Volgograd")
        self.cbUTCOffset.addItem("UTC+03:30 | Tehran")
        self.cbUTCOffset.addItem("UTC+04:00 | Abu Dhabi, Muscat")
        self.cbUTCOffset.addItem("UTC+04:30 | Kabul")
        self.cbUTCOffset.addItem("UTC+05:00 | Islamabad, Karachi, Tashkent")
        self.cbUTCOffset.addItem("UTC+05:30 | Chennai, Kolkata, Mumbai, New Delhi")
        self.cbUTCOffset.addItem("UTC+05:45 | Kathmandu")
        self.cbUTCOffset.addItem("UTC+06:00 | Astana, Dhaka")
        self.cbUTCOffset.addItem("UTC+06:30 | Yangon (Rangoon)")
        self.cbUTCOffset.addItem("UTC+07:00 | Bangkok, Hanoi, Jakarta")
        self.cbUTCOffset.addItem("UTC+08:00 | Beijing, Chongqing, Hong Kong, Urumqi")
        self.cbUTCOffset.addItem("UTC+08:45 | Eucla")
        self.cbUTCOffset.addItem("UTC+09:00 | Osaka, Sapporo, Tokyo")
        self.cbUTCOffset.addItem("UTC+09:30 | Adelaide, Darwin")
        self.cbUTCOffset.addItem("UTC+10:00 | Brisbane, Canberra, Melbourne, Sydney")
        self.cbUTCOffset.addItem("UTC+10:30 | Lord Howe Island")
        self.cbUTCOffset.addItem("UTC+11:00 | Solomon Is., New Caledonia")
        self.cbUTCOffset.addItem("UTC+12:00 | Auckland, Wellington")
        self.cbUTCOffset.addItem("UTC+12:45 | Chatham Islands")
        self.cbUTCOffset.addItem("UTC+13:00 | Samoa")
        self.cbUTCOffset.addItem("UTC+14:00 | Kiritimati")
        self.cbUTCOffset.setCurrentIndex(14)
        if Logic.debug: print("[DEBUG] uiOptions initialized")

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)
        self.loadSettings()
        self.tabWidget.setCurrentIndex(0)
        if Logic.debug: print("[DEBUG] uiOptions showEvent")

    def eventFilter(self, obj, event):
        if obj == self.qleAQPassword and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimer.isActive(): self.lastCharTimer.stop()
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimer.start(500)
            if Logic.debug: print("[DEBUG] AQ password keypress, showing temporarily")
        elif obj == self.qleUSGSAPIKey and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimerUSGS.isActive(): self.lastCharTimerUSGS.stop()
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerUSGS.start(500)
            if Logic.debug: print("[DEBUG] USGS API key keypress, showing temporarily")
        elif obj == self.qleOraclePassword and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimerOracle.isActive(): self.lastCharTimerOracle.stop()
            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerOracle.start(500)
            if Logic.debug: print("[DEBUG] Oracle password keypress, showing temporarily")
        elif obj == self.qleAQPassword and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimer.isActive(): self.lastCharTimer.stop()
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimer.start(500)
            if Logic.debug: print("[DEBUG] AQ password paste, showing temporarily")
        elif obj == self.qleUSGSAPIKey and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimerUSGS.isActive(): self.lastCharTimerUSGS.stop()
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerUSGS.start(500)
            if Logic.debug: print("[DEBUG] USGS API key paste, showing temporarily")
        elif obj == self.qleOraclePassword and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimerOracle.isActive(): self.lastCharTimerOracle.stop()
            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerOracle.start(500)
            if Logic.debug: print("[DEBUG] Oracle password paste, showing temporarily")
        return super().eventFilter(obj, event)

    def maskLastChar(self):
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)
        if Logic.debug: print("[DEBUG] AQ password re-masked")

    def maskLastCharUSGS(self):
        self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password)
        if Logic.debug: print("[DEBUG] USGS API key re-masked")

    def maskLastCharOracle(self):
        self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Password)
        if Logic.debug: print("[DEBUG] Oracle password re-masked")

    def loadSettings(self):
        configPath = Logic.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)

                if Logic.debug: print("[DEBUG] Loaded config from user.config: {}".format(config))
            except Exception as e:
                if Logic.debug: print("[ERROR] Failed to load user.config: {}".format(e))

        utcOffset = config.get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London")
        index = self.cbUTCOffset.findText(utcOffset)

        if index != -1:
            self.cbUTCOffset.setCurrentIndex(index)
            if Logic.debug: print("[DEBUG] Set cbUTCOffset to: {}".format(utcOffset))
        else:
            self.cbUTCOffset.setCurrentIndex(14)
            if Logic.debug: print("[DEBUG] utcOffset '{}' not found, set to default UTC+00:00".format(utcOffset))

        self.cbRetroMode.setChecked(bool(config.get('retroMode', True)))

        if Logic.debug: print("[DEBUG] Set cbRetroMode to: {}".format(self.cbRetroMode.isChecked()))
        self.cbQAQC.setChecked(bool(config.get('qaqc', True)))
        if Logic.debug: print("[DEBUG] Set cbQAQC to: {}".format(self.cbQAQC.isChecked()))
        self.cbRawData.setChecked(bool(config.get('rawData', False)))
        if Logic.debug: print("[DEBUG] Set cbRawData to: {}".format(self.cbRawData.isChecked()))
        self.cbDebug.setChecked(bool(config.get('debugMode', False)))
        if Logic.debug: print("[DEBUG] Set cbDebug to: {}".format(self.cbDebug.isChecked()))
        tnsPath = config.get('tnsNamesLocation', '')
        if tnsPath.startswith(Logic.appRoot): tnsPath = tnsPath.replace(Logic.appRoot, '%AppRoot%')
        self.qleTNSNames.setText(tnsPath)

        if not self.qleTNSNames.text():
            envTns = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin'))            
            if envTns.startswith(Logic.appRoot): envTns = envTns.replace(Logic.appRoot, '%AppRoot%')
            self.qleTNSNames.setText(envTns)
            if Logic.debug: print("[DEBUG] Set qleTNSNames to: {}".format(tnsPath))

        hourMethod = config.get('hourTimestampMethod', 'EOP')

        if hourMethod == 'EOP':
            self.rbEOP.setChecked(True)
        else:
            self.rbBOP.setChecked(True)
        if Logic.debug: print("[DEBUG] Set hourTimestampMethod to: {}".format(hourMethod))

        try:
            self.qleAQServer.setText(keyring.get_password("DataDoctor", "aqServer") or "")
            self.qleAQUser.setText(keyring.get_password("DataDoctor", "aqUser") or "")
            self.qleAQPassword.setText(keyring.get_password("DataDoctor", "aqPassword") or "")
            self.qleUSGSAPIKey.setText(keyring.get_password("DataDoctor", "usgsApiKey") or "")
            self.qleOracleUser.setText(keyring.get_password("DataDoctor", "oracleUser") or "")
            self.qleOraclePassword.setText(keyring.get_password("DataDoctor", "oraclePassword") or "")
            if Logic.debug: print("[DEBUG] Successfully loaded keyring credentials")
        except Exception as e:
            if Logic.debug: print("[ERROR] Failed to load keyring credentials: {}. Using empty strings".format(e))
            self.qleAQServer.setText("")
            self.qleAQUser.setText("")
            self.qleAQPassword.setText("")
            self.qleUSGSAPIKey.setText("")
            self.qleOracleUser.setText("")
            self.qleOraclePassword.setText("")

        if Logic.debug: print("[DEBUG] Settings loaded")

    def onSavePressed(self):
        configPath = Logic.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile: config = json.load(configFile)
                if Logic.debug: print("[DEBUG] Read existing user.config: {}".format(config))
            except Exception as e:
                if Logic.debug: print("[ERROR] Failed to load user.config for save: {}".format(e))

        previousRetro = config.get('retroMode', True)
        newRetro = self.cbRetroMode.isChecked()
        tnsPath = self.qleTNSNames.text()

        if '%AppRoot%' in tnsPath: tnsPath = tnsPath.replace('%AppRoot%', Logic.appRoot)

        config.update({
            'utcOffset': self.cbUTCOffset.currentText(),
            'retroMode': newRetro,
            'qaqc': self.cbQAQC.isChecked(),
            'rawData': self.cbRawData.isChecked(),
            'debugMode': self.cbDebug.isChecked(),
            'tnsNamesLocation': tnsPath,
            'hourTimestampMethod': 'EOP' if self.rbEOP.isChecked() else 'BOP',
            'lastExportPath': config.get('lastExportPath', '')
        })

        with open(configPath, 'w', encoding='utf-8') as configFile: json.dump(config, configFile, indent=2)

        if Logic.debug: print("[DEBUG] Saved user.config with retroMode: {}".format(newRetro))
        Logic.reloadGlobals()

        if newRetro != previousRetro:
            reply = QMessageBox.question(
                self, "Retro Mode Change",
                "Restart DataDoctor for the retro mode change to take effect?\nOK to restart now, Cancel to revert to previous setting.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )

            if reply == QMessageBox.StandardButton.Ok:
                python = sys.executable
                os.execl(python, python, *sys.argv)
            else:
                self.cbRetroMode.setChecked(previousRetro)
                config['retroMode'] = previousRetro

                with open(configPath, 'w', encoding='utf-8') as configFile: json.dump(config, configFile, indent=2)
                Logic.reloadGlobals()
                if Logic.debug: print("[DEBUG] Reverted retro mode to {}".format(previousRetro))

        credentials = [
            ("aqServer", self.qleAQServer.text()),
            ("aqUser", self.qleAQUser.text()),
            ("aqPassword", self.qleAQPassword.text()),
            ("usgsApiKey", self.qleUSGSAPIKey.text()),
            ("oracleUser", self.qleOracleUser.text()),
            ("oraclePassword", self.qleOraclePassword.text())
        ]

        for key, value in credentials:
            if value and isinstance(value, str) and value.strip():
                try:
                    keyring.set_password("DataDoctor", key, value)
                    if Logic.debug: print("[DEBUG] Saved {} to keyring".format(key))
                except Exception as e:
                    if Logic.debug: print("[ERROR] Failed to save {} to keyring: {}".format(key, e))
                    QMessageBox.warning(self, "Credential Save Error", "Failed to save {}: {}".format(key, e))
            elif Logic.debug: print("[DEBUG] Skipped saving {} to keyring: empty or invalid".format(key))

    def togglePasswordVisibility(self):
        if self.lastCharTimer.isActive(): self.lastCharTimer.stop()

        if self.qleAQPassword.echoMode() == QLineEdit.EchoMode.Password:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))
            if Logic.debug: print("[DEBUG] AQ password shown via button")
        else:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))
            if Logic.debug: print("[DEBUG] AQ password masked via button")

    def toggleUSGSKeyVisibility(self):
        if self.lastCharTimerUSGS.isActive(): self.lastCharTimerUSGS.stop()

        if self.qleUSGSAPIKey.echoMode() == QLineEdit.EchoMode.Password:
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))
            if Logic.debug: print("[DEBUG] USGS API key shown via button")
        else:
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password)
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))
            if Logic.debug: print("[DEBUG] USGS API key masked via button")

    def toggleOraclePasswordVisibility(self):
        if self.lastCharTimerOracle.isActive(): self.lastCharTimerOracle.stop()

        if self.qleOraclePassword.echoMode() == QLineEdit.EchoMode.Password:
            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btnShowOraclePassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))
            if Logic.debug: print("[DEBUG] Oracle password shown via button")
        else:
            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Password)
            self.btnShowOraclePassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))
            if Logic.debug: print("[DEBUG] Oracle password masked via button")

class uiAbout(QDialog):
    """About dialog: Retro PNG bg with transparent info overlay and looping sound."""
    def __init__(self, parent=None):
        super(uiAbout, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winAbout.ui'), self)
        self.backgroundLabel = self.findChild(QLabel, 'backgroundLabel')
        self.textInfo = self.findChild(QTextBrowser, 'textInfo')
        self.setFixedSize(900, 479)
        self.setWindowTitle('About Data Doctor')
        pngPath = Logic.resourcePath('ui/DataDoctor.png')
        pixmap = QPixmap(pngPath)
        scaledPixmap = pixmap.scaled(900, 479, Qt.AspectRatioMode.KeepAspectRatio)
        self.backgroundLabel.setPixmap(scaledPixmap)
        self.backgroundLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
        fontId = QFontDatabase.addApplicationFont(fontPath)
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0] if fontId != -1 else "Courier"
        retroFontObj = QFont(fontFamily, 10)
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.textInfo.setFont(retroFontObj)
        infoList = [
            ('Version', '3.0.0'),
            ('GitHub', 'https://github.com/S31F3R/DataDoctor'),
            ('Author', 'S31F3R'),
            ('License', 'GPL-3.0'),
            ('Music', 'By Eric Matyas at www.soundimage.org')
        ]

        htmlContent = '<html><body style="color: white; font-family: \'' + fontFamily + '\'; font-size: 10pt; padding-left: 50px; white-space: nowrap; line-height: 2.0;">'

        for label, content in infoList:
            if 'GitHub' in label:
                htmlContent += f'{label}: <a href="{content}" style="color: white;">{content}</a><br>'
            else:
                htmlContent += f'{label}: {content}<br>'

        htmlContent += '</body></html>'
        self.textInfo.setHtml(htmlContent)
        self.textInfo.setOpenExternalLinks(True)
        self.textInfo.setStyleSheet("background-color: transparent; border: none;")
        self.textInfo.setGeometry(70, 140, 800, 200)
        self.soundEffect = None

        try:
            wavPath = Logic.resourcePath('ui/sounds/8-Bit-Perplexion.wav')
            self.soundEffect = QSoundEffect(self)
            self.soundEffect.setSource(QUrl.fromLocalFile(wavPath))
            self.soundEffect.setLoopCount(QSoundEffect.Infinite)
            self.soundEffect.setVolume(0.8)
        except Exception as e:
            return

    def showEvent(self, event):
        Logic.centerWindowToParent(self)

        if self.soundEffect:
            self.soundEffect.play()

        super().showEvent(event)

    def closeEvent(self, event):
        if self.soundEffect: self.soundEffect.stop()
        super().closeEvent(event)

# Create QApplication
app = QApplication(sys.argv)
app.setApplicationName("Data Doctor")

# Create instances
winMain = uiMain()
winQuery = uiQuery(winMain)
winDataDictionary = uiDataDictionary(winMain)
winQuickLook = uiQuickLook(winMain)
winOptions = uiOptions(winMain)
winAbout = uiAbout(winMain)

# Load config
config = Logic.loadConfig()
Logic.debug = config['debugMode']
Logic.utcOffset = config['utcOffset']
Logic.periodOffset = config['periodOffset']
Logic.retroMode = config.get('retroMode', True)

# Apply retro font if enabled
if Logic.retroMode:
    fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
    fontId = QFontDatabase.addApplicationFont(fontPath)

    if fontId != -1:
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
        retroFontObj = QFont(fontFamily, 10)
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        app.setFont(retroFontObj)
        if Logic.debug: print("[DEBUG] Applied retro font at startup")
    Logic.setRetroStyles(app, True, winMain.mainTable, winQuery.listQueryList)
else:
    Logic.setRetroStyles(app, False, winMain.mainTable, winQuery.listQueryList)

# Load stylesheet
with open(Logic.resourcePath('ui/stylesheet.qss'), 'r') as f: app.setStyleSheet(f.read())

# Load data dictionary
Logic.buildDataDictionary(winDataDictionary.mainTable)

# Load quick looks
Logic.loadAllQuickLooks(winQuery.cbQuickLook)

# Start application
app.exec()