import sys
import Logic
import keyring
import os
import json
import keyring
from keyring.backends.null import Keyring as NullKeyring # Safe fallback if needed
#from datetime import datetime
from PyQt6.QtGui import QGuiApplication, QIcon, QFont, QFontDatabase, QPixmap 
from PyQt6.QtCore import Qt, QEvent, QTimer, QUrl
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QVBoxLayout,
                             QTextEdit, QComboBox, QDateTimeEdit, QListWidget, QWidget, QGridLayout,
                             QMessageBox, QDialog, QSizePolicy, QTabWidget, QRadioButton, QButtonGroup,
                             QDialogButtonBox, QLineEdit, QLabel, QTextBrowser, QCheckBox, QMenu)
from PyQt6 import uic
from PyQt6.QtMultimedia import QSoundEffect
#from collections import defaultdict

# No backend forcing: Rely on keyring defaults (KWallet on KDE/Linux, Credential Manager on Windows, Keychain on macOS)

class uiMain(QMainWindow):
    """Main window for DataDoctor: Handles core UI, queries, and exports."""
    def __init__(self):
            super(uiMain, self).__init__() # Call the inherited classes __init__ method
            uic.loadUi(Logic.resourcePath('ui/winMain.ui'), self) # Load the .ui file
            with open(Logic.resourcePath('ui/stylesheet.qss'), 'r') as f:
                app.setStyleSheet(f.read()) # Global stylesheet application

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
            self.lastQueryType = None # 'web' or 'internal'
            self.lastQueryItems = [] # List of (dataID, interval, database, mrid, origIndex)
            self.lastStartDate = None
            self.lastEndDate = None

            # Set button style (exclude btnRefresh and btnUndo)
            Logic.buttonStyle(self.btnPublicQuery)
            Logic.buttonStyle(self.btnDataDictionary)
            Logic.buttonStyle(self.btnExportCSV)
            Logic.buttonStyle(self.btnOptions)
            Logic.buttonStyle(self.btnInfo)
            Logic.buttonStyle(self.btnInternalQuery)
            Logic.buttonStyle(self.btnUndo)
            Logic.buttonStyle(self.btnRefresh)

            # Set up stretch for central grid layout (make tab row expand)
            centralLayout = self.centralWidget().layout()
            if isinstance(centralLayout, QGridLayout):
                centralLayout.setContentsMargins(0, 0, 0, 0)
                centralLayout.setRowStretch(0, 0) # Toolbar row fixed
                centralLayout.setRowStretch(1, 1) # Tab row expanding
                centralLayout.setColumnStretch(0, 1) # Single column expanding

            # Ensure tab widget expands
            self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
            if self.tabWidget:
                self.tabWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            # Connect close button signal
            self.tabWidget.tabCloseRequested.connect(self.onTabCloseRequested)

            # Set up Data Query tab (tabMain QWidget)
            self.tabMain = self.findChild(QWidget, 'tabMain')
            if self.tabMain:
                self.tabMain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            # Add layout if none exists
            if not self.tabMain.layout():
                layout = QVBoxLayout(self.tabMain)
                layout.addWidget(self.mainTable)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

            # Reset table geometry to let layout manage sizing
            self.mainTable.setGeometry(0, 0, 0, 0)

            # Set table to expand within its layout
            self.mainTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            # Hide tabs on startup (both Data Query and SQL)
            if self.tabWidget:
                # Hide Data Query
                dataQueryIndex = self.tabWidget.indexOf(self.tabMain)
                if dataQueryIndex != -1:
                    self.tabWidget.removeTab(dataQueryIndex)

                # Hide SQL
                sqlTab = self.findChild(QWidget, 'tabSQL')
                sqlIndex = self.tabWidget.indexOf(sqlTab)
                if sqlIndex != -1:
                    self.tabWidget.removeTab(sqlIndex)

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
            self.mainTable.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu) # Enable right-click menu
            self.mainTable.horizontalHeader().customContextMenuRequested.connect(self.showHeaderContextMenu) # Connect right-click signal

            # Center window when opened
            rect = self.frameGeometry()
            centerPoint = QGuiApplication.primaryScreen().availableGeometry().center()
            rect.moveCenter(centerPoint)
            self.move(rect.topLeft())

            # Show the GUI on application start
            self.show()
            if Logic.debug: print("[DEBUG] uiMain initialized with header context menu")

    def showHeaderContextMenu(self, pos):
        """Show context menu for header right-click to display full query info."""
        header = self.mainTable.horizontalHeader()
        col = header.logicalIndexAt(pos)
        if col < 0 or col >= len(self.lastQueryItems):
            if Logic.debug: print("[DEBUG] showHeaderContextMenu: Invalid column {} clicked".format(col))
            return
        queryInfo = f"{self.lastQueryItems[col][0]}|{self.lastQueryItems[col][1]}|{self.lastQueryItems[col][2]}"
        menu = QMenu(self)
        action = menu.addAction("Show Query Info")
        action.triggered.connect(lambda: self.showDataIdMessage(queryInfo))
        menu.exec(header.mapToGlobal(pos))
        if Logic.debug: print("[DEBUG] showHeaderContextMenu: Displayed menu for column {}, queryInfo {}".format(col, queryInfo))

    def showDataIdMessage(self, queryInfo):
        """Display QMessageBox with full query info."""
        QMessageBox.information(self, "Full Query Info", queryInfo)
        if Logic.debug: print("[DEBUG] showDataIdMessage: Showed queryInfo {}".format(queryInfo))

    def onTabCloseRequested(self, index):
        """Handle tab close button clicks by removing the tab."""
        if self.tabWidget:
            self.tabWidget.removeTab(index)

    def btnPublicQueryPressed(self): 
        winWebQuery.show()  

    def btnInternalQueryPressed(self): 
        winInternalQuery.show()

    def btnOptionsPressed(self): 
        winOptions.exec()  

    def btnInfoPressed(self): 
        winAbout.exec()

    def showDataDictionary(self):         
        winDataDictionary.show()    

    def btnExportCSVPressed(self):
        Logic.exportTableToCSV(self.mainTable, '', '') # Pass empty (uses dialog)

    def exitPressed(self):
        app.exit()

    def btnRefreshPressed(self):
        if Logic.debug: print("[DEBUG] btnRefreshPressed: Starting refresh process.")
        if not self.lastQueryType:
            if Logic.debug: print("[DEBUG] No last query to refresh.")
            return
        from datetime import datetime
        now = datetime.now()
        endDateTime = datetime.strptime(self.lastEndDate, '%Y-%m-%d %H:%M')
        if endDateTime.date() == now.date():
            self.lastEndDate = now.strftime('%Y-%m-%d %H:%M')
            if Logic.debug: print(f"[DEBUG] Updated end date to current: {self.lastEndDate}")
        Logic.executeQuery(self, self.lastQueryItems, self.lastStartDate, self.lastEndDate, self.lastQueryType == 'internal', winDataDictionary.mainTable)

    def btnUndoPressed(self):
        if Logic.debug: print("[DEBUG] btnUndoPressed: Resetting to timestamp sort.")
        Logic.timestampSortTable(self.mainTable, winDataDictionary.mainTable)

class uiWebQuery(QMainWindow):
    """Public query window: Builds and executes public API calls."""
    def __init__(self, parent=None):
        super(uiWebQuery, self).__init__(parent) # Initialize parent
        uic.loadUi(Logic.resourcePath('ui/winWebQuery.ui'), self) # Load UI file

        # Define controls
        self.btnQuery = self.findChild(QPushButton, 'btnQuery') # Query Data button
        self.qleDataID = self.findChild(QLineEdit, 'qleDataID') # Data ID input (QLineEdit)
        self.cbDatabase = self.findChild(QComboBox, 'cbDatabase') # Database selector
        self.cbInterval = self.findChild(QComboBox, 'cbInterval') # Interval selector
        self.dteStartDate = self.findChild(QDateTimeEdit, 'dteStartDate') # Start date/time
        self.dteEndDate = self.findChild(QDateTimeEdit, 'dteEndDate') # End date/time
        self.listQueryList = self.findChild(QListWidget, 'listQueryList') # Query list
        self.btnAddQuery = self.findChild(QPushButton, 'btnAddQuery') # Add Query button
        self.btnRemoveQuery = self.findChild(QPushButton, 'btnRemoveQuery') # Remove Query button
        self.btnSaveQuickLook = self.findChild(QPushButton, 'btnSaveQuickLook') # Save Quick Look button
        self.cbQuickLook = self.findChild(QComboBox, 'cbQuickLook') # Quick Look selector
        self.btnLoadQuickLook = self.findChild(QPushButton, 'btnLoadQuickLook') # Load Quick Look button
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery') # Clear Query button
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo') # Data ID info button
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo') # Interval info button
        self.rbCustomDateTime = self.findChild(QRadioButton, 'rbCustomDateTime') # Custom date/time radio
        self.rbPrevDayToCurrent = self.findChild(QRadioButton, 'rbPrevDayToCurrent') # Prev day radio
        self.rbPrevWeekToCurrent = self.findChild(QRadioButton, 'rbPrevWeekToCurrent') # Prev week radio

        # Group radio buttons for clarity
        self.radioGroup = QButtonGroup(self) # Ensure mutual exclusivity
        self.radioGroup.addButton(self.rbCustomDateTime)
        self.radioGroup.addButton(self.rbPrevDayToCurrent)
        self.radioGroup.addButton(self.rbPrevWeekToCurrent)

        # Set button style
        Logic.buttonStyle(self.btnDataIdInfo) # Apply flat style
        Logic.buttonStyle(self.btnIntervalInfo) # Apply flat style      
        
        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed) # Query button
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed) # Add query
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed) # Remove query
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed) # Save quick look
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed) # Load quick look
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed) # Clear query list
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed) # Data ID info
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed) # Interval info
        self.radioGroup.buttonClicked.connect(lambda btn: Logic.setQueryDateRange(self, btn, self.dteStartDate, self.dteEndDate)) # Radio button date range

        # Install event filters for focus and keypress handling
        self.qleDataID.installEventFilter(self) # Handle qleDataID focus
        self.installEventFilter(self) # Handle window-level keypress

        # Populate database combobox (public-specific)
        self.cbDatabase.addItem('USBR-LCHDB') # Lower Colorado
        self.cbDatabase.addItem('USBR-YAOHDB') # Yuma Area
        self.cbDatabase.addItem('USBR-UCHDB2') # Upper Colorado
        self.cbDatabase.addItem('USGS-NWIS') # USGS

        # Populate interval combobox
        self.cbDatabase.addItem('AQUARIUS')
        self.cbDatabase.addItem('USBR-LCHDB')
        self.cbDatabase.addItem('USBR-YAOHDB')
        self.cbDatabase.addItem('USBR-UCHDB2')
        self.cbInterval.addItem('HOUR')
        self.cbInterval.addItem('INSTANT:1')
        self.cbInterval.addItem('INSTANT:15')
        self.cbInterval.addItem('INSTANT:60')
        self.cbInterval.addItem('DAY')

        # Set initial state
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate) # Set custom date, 72h range

        # Set default button
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery) # Query default initially

        # Disable maximize button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint) # Fixed size

    def showEvent(self, event):
        if Logic.debug: print("[DEBUG] Web query window showEvent")
        Logic.centerWindowToParent(self) # Center on parent
        Logic.loadLastQuickLook(self.cbQuickLook) # Load last quick look
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery) # Reset to Query default
        super().showEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            if Logic.debug: print("[DEBUG] qleDataID focus in, setting Add Query default")
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery) # Add Query default
        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            if Logic.debug: print("[DEBUG] qleDataID focus out, setting Query Data default")
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery) # Query default
        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if Logic.debug: print("[DEBUG] Enter key pressed")
            if self.qleDataID.hasFocus():
                if Logic.debug: print("[DEBUG] qleDataID focused, triggering btnAddQueryPressed")
                self.btnAddQueryPressed() # Trigger Add Query
            elif self.btnQuery.isDefault():
                if Logic.debug: print("[DEBUG] btnQuery is default, triggering btnQueryPressed")
                self.btnQueryPressed() # Trigger Query Data
            return True # Consume Enter key
        return super().eventFilter(obj, event)

    def btnQueryPressed(self):
        if Logic.debug: print("[DEBUG] btnQueryPressed: Starting query process.")
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
            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, i))
            if Logic.debug: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        if not queryItems and self.qleDataID.text().strip():
            dataID = self.qleDataID.text().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'
            SDID = dataID
            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, 0))
            if Logic.debug: print(f"[DEBUG] Added single query: {(dataID, interval, database, mrid, 0)}")
        elif not queryItems:
            print("[WARN] No valid query items.")
            return
        winMain.lastQueryType = 'web'
        winMain.lastQueryItems = queryItems
        winMain.lastStartDate = startDate
        winMain.lastEndDate = endDate
        winMain.lastDatabase = self.cbDatabase.currentText() if not queryItems else None
        winMain.lastInterval = self.cbInterval.currentText() if not queryItems else None
        if Logic.debug: print("[DEBUG] Stored last query as web.")
        Logic.executeQuery(winMain, queryItems, startDate, endDate, False, winDataDictionary.mainTable)
        self.close()
        if Logic.debug: print("[DEBUG] Web query window closed after query.")

    def btnAddQueryPressed(self):
        item = f'{self.qleDataID.text().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}' # Build query item
        self.listQueryList.addItem(item) # Add to list
        self.qleDataID.clear() # Clear input
        self.qleDataID.setFocus() # Refocus
        self.listQueryList.scrollToBottom() # Scroll to bottom to show new item
        if Logic.debug: print(f"[DEBUG] Added query item: {item}, scrolled to bottom")

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()
        if item:
            self.listQueryList.takeItem(self.listQueryList.row(item)) # Remove selected
            if Logic.debug: print(f"[DEBUG] Removed query item: {item.text()}")
        else:
            if Logic.debug: print("[DEBUG] No query item selected for removal")

    def btnSaveQuickLookPressed(self):
        winQuickLook.currentListQueryList = self.listQueryList # Set current list
        winQuickLook.CurrentCbQuickLook = self.cbQuickLook # Set current combo
        winQuickLook.exec() # Show dialog
        self.raise_() # Counter Plasma focus loss
        self.activateWindow()

        if Logic.debug: print("[DEBUG] Save Quick Look dialog opened")

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList) # Load selected quick look
        configPath = Logic.getConfigPath() # Get JSON path
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile) # Read JSON
            except Exception as e:
                if Logic.debug: print(f"[ERROR] Failed to load user.config: {e}")

        config['lastQuickLook'] = self.cbQuickLook.currentText() # Save quick look

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2) # Write JSON

        if Logic.debug: print(f"[DEBUG] Loaded quick look: {self.cbQuickLook.currentText()}")

    def btnClearQueryPressed(self):
        self.listQueryList.clear() # Clear query list
        if Logic.debug: print("[DEBUG] Query list cleared")

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", "AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter") # Show info
        if Logic.debug: print("[DEBUG] Data ID info displayed")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.") # Show info
        if Logic.debug: print("[DEBUG] Interval info displayed")

class uiInternalQuery(QMainWindow):
    """Internal query window: Builds and executes internal queries."""
    def __init__(self, parent=None):
        super(uiInternalQuery, self).__init__(parent) # Initialize parent
        uic.loadUi(Logic.resourcePath('ui/winInternalQuery.ui'), self) # Load UI file

        # Define controls
        self.btnQuery = self.findChild(QPushButton, 'btnQuery') # Query Data button
        self.qleDataID = self.findChild(QLineEdit, 'qleDataID') # Data ID input (QLineEdit)
        self.cbDatabase = self.findChild(QComboBox, 'cbDatabase') # Database selector
        self.cbInterval = self.findChild(QComboBox, 'cbInterval') # Interval selector
        self.dteStartDate = self.findChild(QDateTimeEdit, 'dteStartDate') # Start date/time
        self.dteEndDate = self.findChild(QDateTimeEdit, 'dteEndDate') # End date/time
        self.listQueryList = self.findChild(QListWidget, 'listQueryList') # Query list
        self.btnAddQuery = self.findChild(QPushButton, 'btnAddQuery') # Add Query button
        self.btnRemoveQuery = self.findChild(QPushButton, 'btnRemoveQuery') # Remove Query button
        self.btnSaveQuickLook = self.findChild(QPushButton, 'btnSaveQuickLook') # Save Quick Look button
        self.cbQuickLook = self.findChild(QComboBox, 'cbQuickLook') # Quick Look selector
        self.btnLoadQuickLook = self.findChild(QPushButton, 'btnLoadQuickLook') # Load Quick Look button
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery') # Clear Query button
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo') # Data ID info button
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo') # Interval info button
        self.rbCustomDateTime = self.findChild(QRadioButton, 'rbCustomDateTime') # Custom date/time radio
        self.rbPrevDayToCurrent = self.findChild(QRadioButton, 'rbPrevDayToCurrent') # Prev day radio
        self.rbPrevWeekToCurrent = self.findChild(QRadioButton, 'rbPrevWeekToCurrent') # Prev week radio

        # Group radio buttons for clarity
        self.radioGroup = QButtonGroup(self) # Ensure mutual exclusivity
        self.radioGroup.addButton(self.rbCustomDateTime)
        self.radioGroup.addButton(self.rbPrevDayToCurrent)
        self.radioGroup.addButton(self.rbPrevWeekToCurrent)

        # Set button style
        Logic.buttonStyle(self.btnDataIdInfo) # Apply flat style
        Logic.buttonStyle(self.btnIntervalInfo) # Apply flat style
        
        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed) # Query button
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed) # Add query
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed) # Remove query
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed) # Save quick look
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed) # Load quick look
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed) # Clear query list
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed) # Data ID info
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed) # Interval info
        self.radioGroup.buttonClicked.connect(lambda btn: Logic.setQueryDateRange(self, btn, self.dteStartDate, self.dteEndDate)) # Radio button date range

        # Install event filters for focus and keypress handling
        self.qleDataID.installEventFilter(self) # Handle qleDataID focus
        self.installEventFilter(self) # Handle window-level keypress

        # Populate database combobox (internal-specific)
        self.cbDatabase.addItem('AQUARIUS') # Aquarius
        self.cbDatabase.addItem('USBR-LCHDB') # Lower Colorado
        self.cbDatabase.addItem('USBR-YAOHDB') # Yuma Area
        self.cbDatabase.addItem('USBR-UCHDB2') # Upper Colorado

        # Populate interval combobox
        self.cbDatabase.addItem('AQUARIUS')
        self.cbDatabase.addItem('USBR-LCHDB')
        self.cbDatabase.addItem('USBR-YAOHDB')
        self.cbDatabase.addItem('USBR-UCHDB2')
        self.cbInterval.addItem('HOUR')
        self.cbInterval.addItem('INSTANT:1')
        self.cbInterval.addItem('INSTANT:15')
        self.cbInterval.addItem('INSTANT:60')
        self.cbInterval.addItem('DAY')

        # Set initial state
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate) # Set custom date, 72h range

        # Set default button
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery) # Query default initially

        # Disable maximize button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint) # Fixed size

    def showEvent(self, event):
        if Logic.debug: print("[DEBUG] Internal query window showEvent")
        Logic.centerWindowToParent(self) # Center on parent
        Logic.loadLastQuickLook(self.cbQuickLook) # Load last quick look
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery) # Reset to Query default
        super().showEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            if Logic.debug: print("[DEBUG] qleDataID focus in, setting Add Query default")
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery) # Add Query default

        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            if Logic.debug: print("[DEBUG] qleDataID focus out, setting Query Data default")
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery) # Query default

        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if Logic.debug: print("[DEBUG] Enter key pressed")

            if self.qleDataID.hasFocus():
                if Logic.debug: print("[DEBUG] qleDataID focused, triggering btnAddQueryPressed")
                self.btnAddQueryPressed() # Trigger Add Query
            elif self.btnQuery.isDefault():
                if Logic.debug: print("[DEBUG] btnQuery is default, triggering btnQueryPressed")
                self.btnQueryPressed() # Trigger Query Data
            return True # Consume Enter key

        return super().eventFilter(obj, event)

    def btnQueryPressed(self):
        if Logic.debug: print("[DEBUG] btnQueryPressed: Starting query process.")
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
            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, i))
            if Logic.debug: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        if not queryItems and self.qleDataID.text().strip():
            dataID = self.qleDataID.text().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'
            SDID = dataID
            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, 0))
            if Logic.debug: print(f"[DEBUG] Added single query: {(dataID, interval, database, mrid, 0)}")
        elif not queryItems:
            print("[WARN] No valid query items.")
            return
        queryItems = [item for item in queryItems if item[2] != 'USGS-NWIS']
        if not queryItems:
            QMessageBox.warning(self, "No Valid Items", "No valid internal query items (USGS skipped).")
            return
        winMain.lastQueryType = 'internal'
        winMain.lastQueryItems = queryItems
        winMain.lastStartDate = startDate
        winMain.lastEndDate = endDate
        winMain.lastDatabase = self.cbDatabase.currentText() if not queryItems else None
        winMain.lastInterval = self.cbInterval.currentText() if not queryItems else None
        if Logic.debug: print("[DEBUG] Stored last query as internal.")
        Logic.executeQuery(winMain, queryItems, startDate, endDate, True, winDataDictionary.mainTable)
        self.close()
        if Logic.debug: print("[DEBUG] Internal query window closed after query.")

    def btnAddQueryPressed(self):
        item = f'{self.qleDataID.text().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}' # Build query item
        self.listQueryList.addItem(item) # Add to list
        self.qleDataID.clear() # Clear input
        self.qleDataID.setFocus() # Refocus
        self.listQueryList.scrollToBottom() # Scroll to bottom to show new item
        if Logic.debug: print(f"[DEBUG] Added query item: {item}, scrolled to bottom")

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()

        if item:
            self.listQueryList.takeItem(self.listQueryList.row(item)) # Remove selected
            if Logic.debug: print(f"[DEBUG] Removed query item: {item.text()}")
        else:
            if Logic.debug: print("[DEBUG] No query item selected for removal")

    def btnSaveQuickLookPressed(self):
        winQuickLook.currentListQueryList = self.listQueryList # Set current list
        winQuickLook.CurrentCbQuickLook = self.cbQuickLook # Set current combo
        winQuickLook.exec() # Show dialog
        self.raise_() # Counter Plasma focus loss
        self.activateWindow()

        if Logic.debug: print("[DEBUG] Save Quick Look dialog opened")

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList) # Load selected quick look
        configPath = Logic.getConfigPath() # Get JSON path
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile) # Read JSON
            except Exception as e:
                if Logic.debug: print(f"[ERROR] Failed to load user.config: {e}")

        config['lastQuickLook'] = self.cbQuickLook.currentText() # Save quick look

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2) # Write JSON
        if Logic.debug: print(f"[DEBUG] Loaded quick look: {self.cbQuickLook.currentText()}")

    def btnClearQueryPressed(self):
        self.listQueryList.clear() # Clear query list
        if Logic.debug: print("[DEBUG] Query list cleared")

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", "AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter") # Show info
        if Logic.debug: print("[DEBUG] Data ID info displayed")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.") # Show info
        if Logic.debug: print("[DEBUG] Interval info displayed")

class uiDataDictionary(QMainWindow):
    """Data dictionary editor: Manages labels for time-series IDs."""
    def __init__(self, parent=None):
        super(uiDataDictionary, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winDataDictionary.ui'), self) # Load the .ui file

        # Define the controls
        self.mainTable = self.findChild(QTableWidget, 'dataDictionaryTable') # Data dictionary table
        self.btnSave = self.findChild(QPushButton, 'btnSave') # Save button
        self.btnAddRow = self.findChild(QPushButton, 'btnAddRow') # Add row button
        self.btnDeleteRow = self.findChild(QPushButton, 'btnDeleteRow') # Remove row button

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed) # Save dictionary
        self.btnAddRow.clicked.connect(self.btnAddRowPressed) # Add row
        self.btnDeleteRow.clicked.connect(self.btnDeleteRowPressed) # Remove selected row

        # Set button style
        Logic.buttonStyle(self.btnSave)
        Logic.buttonStyle(self.btnAddRow)
        Logic.buttonStyle(self.btnDeleteRow)
        if Logic.debug: print("[DEBUG] uiDataDictionary initialized with btnDeleteRow")

    def showEvent(self, event):
        Logic.centerWindowToParent(self) # Center on parent
        super().showEvent(event)

    def btnSavePressed(self):
        data = [] # Initialize data list

        with open(Logic.resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
            header = f.readlines()[0].rstrip('\n') # Keep header, strip trailing \n
            data.append(header)
            if Logic.debug: print(f"[DEBUG] Appended stripped header: {header}")

        for r in range(self.mainTable.rowCount()):
            rowData = []
            isEmptyRow = True # Track if row is empty

            for c in range(self.mainTable.columnCount()):
                item = self.mainTable.item(r, c)
                cellText = item.text().strip() if item else ''
                rowData.append(cellText) # Collect row data
                if cellText: # Non-empty cell found
                    isEmptyRow = False

            if not isEmptyRow: # Only append non-empty rows
                data.append(','.join(rowData)) # Add row as CSV
                if Logic.debug: print(f"[DEBUG] Saved row {r} with data: {rowData}")
            else:
                if Logic.debug: print(f"[DEBUG] Skipped empty row {r}")

        with open(Logic.resourcePath('DataDictionary.csv'), 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(data) + '\n') # Write with \n between, add final \n for standard

        for c in range(self.mainTable.columnCount()):
            self.mainTable.resizeColumnToContents(c) # Auto-size columns
            
        if Logic.debug: print(f"[DEBUG] DataDictionary saved with {len(data)-1} rows and columns resized")
    
    def btnAddRowPressed(self):
        self.mainTable.setRowCount(self.mainTable.rowCount() + 1) # Add new row
        self.mainTable.scrollToBottom() # Scroll to show the new row
        if Logic.debug: print(f"[DEBUG] Added row to DataDictionary, scrolled to bottom, new row count: {self.mainTable.rowCount()}")

    def btnDeleteRowPressed(self):
        currentRow = self.mainTable.currentRow() # Get the currently selected row

        if currentRow >= 0: # Valid row selected
            self.mainTable.removeRow(currentRow) # Remove the selected row
            if Logic.debug: print(f"[DEBUG] Removed row {currentRow} from DataDictionary, new row count: {self.mainTable.rowCount()}")
        else:
            if Logic.debug: print("[DEBUG] No row selected for removal in DataDictionary")
        
class uiQuickLook(QDialog):
    """Quick look save dialog: Names and stores query presets."""
    def __init__(self, parent=None):
        super(uiQuickLook, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winQuickLook.ui'), self) # Load the .ui file

        # Define the controls
        self.btnSave = self.findChild(QPushButton, 'btnSave')
        self.btnCancel = self.findChild(QPushButton, 'btnCancel')
        self.qleQuickLookName = self.findChild(QLineEdit, 'qleQuickLookName')

        # Temp attrs for dynamic query widgets
        self.currentListQueryList = None
        self.CurrentCbQuickLook = None

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnCancel.clicked.connect(self.btnCancelPressed)
        if Logic.debug: print("[DEBUG] uiQuickLook initialized with QLineEdit qleQuickLookName")

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self):
        # Save quick look
        if self.currentListQueryList and self.CurrentCbQuickLook:
            if Logic.debug: print("[DEBUG] Saving quick look using currentListQueryList with count:", self.currentListQueryList.count())
            Logic.saveQuickLook(self.qleQuickLookName.text().strip(), self.currentListQueryList)

        # Reload quick looks on both windows
        if Logic.debug: print("[DEBUG] Reloading quick looks on web and internal windows")
        Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)
        Logic.loadAllQuickLooks(winInternalQuery.cbQuickLook)

        # Clear the controls
        self.clear()

        # Close the window
        winQuickLook.close()
        if Logic.debug: print("[DEBUG] Quick look saved and window closed")

    def btnCancelPressed(self): 
        # Clear the controls
        self.clear()

        # Close the window
        winQuickLook.close() 

    def clear(self):
        # Clear all controls
        self.qleQuickLookName.clear()
        if Logic.debug: print("[DEBUG] Cleared qleQuickLookName")

class uiOptions(QDialog):
    """Options editor: Stores database connection information and application settings."""
    def __init__(self, parent=None):
        super(uiOptions, self).__init__(parent) # Call inherited __init__
        uic.loadUi(Logic.resourcePath('ui/winOptions.ui'), self) # Load UI file

        # Define controls
        self.cbUTCOffset = self.findChild(QComboBox, 'cbUTCOffset') # UTC offset selector
        self.textAQServer = self.findChild(QTextEdit, 'textAQServer') # Aquarius server
        self.textAQUser = self.findChild(QTextEdit, 'textAQUser') # Aquarius user
        self.qleAQPassword = self.findChild(QLineEdit, 'qleAQPassword') # Aquarius password
        self.qleUSGSAPIKey = self.findChild(QLineEdit, 'qleUSGSAPIKey') # USGS API key
        self.textTNSNames = self.findChild(QTextEdit, 'textTNSNames') # TNS names path
        self.rbBOP = self.findChild(QRadioButton, 'rbBOP') # Begin of period
        self.rbEOP = self.findChild(QRadioButton, 'rbEOP') # End of period
        self.btnbOptions = self.findChild(QDialogButtonBox, 'btnbOptions') # Save/Cancel buttons
        self.cbRetroMode = self.findChild(QCheckBox, 'cbRetroMode') # Retro mode toggle
        self.cbQAQC = self.findChild(QCheckBox, 'cbQAQC') # QAQC toggle
        self.cbRawData = self.findChild(QCheckBox, 'cbRawData') # Raw data toggle
        self.cbDebug = self.findChild(QCheckBox, 'cbDebug') # Debug toggle
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget') # Settings tabs
        self.btnShowPassword = self.findChild(QPushButton, 'btnShowPassword') # AQ password toggle
        self.btnShowUSGSKey = self.findChild(QPushButton, 'btnShowUSGSKey') # USGS key toggle

        # Set button style
        Logic.buttonStyle(self.btnShowPassword) # Apply flat style
        Logic.buttonStyle(self.btnShowUSGSKey) # Apply flat style

        # Timers for password and USGS key show
        self.lastCharTimer = QTimer(self) # Timer for AQ password
        self.lastCharTimer.setSingleShot(True) # Single-shot to prevent overlap
        self.lastCharTimer.timeout.connect(self.maskLastChar) # Re-mask AQ password
        self.lastCharTimerUSGS = QTimer(self) # Timer for USGS key
        self.lastCharTimerUSGS.setSingleShot(True) # Single-shot to prevent overlap
        self.lastCharTimerUSGS.timeout.connect(self.maskLastCharUSGS) # Re-mask USGS key

        # Create events
        self.btnbOptions.accepted.connect(self.onSavePressed) # Save settings
        self.btnShowPassword.clicked.connect(self.togglePasswordVisibility) # Toggle AQ password
        self.btnShowUSGSKey.clicked.connect(self.toggleUSGSKeyVisibility) # Toggle USGS key

        # Mask password and USGS key by default
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password) # Mask AQ password
        self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password) # Mask USGS key

        # Install event filters for keypress
        self.qleAQPassword.installEventFilter(self) # AQ password
        self.qleUSGSAPIKey.installEventFilter(self) # USGS key

        # Populate UTC offset combobox
        self.cbUTCOffset.addItem("UTC-12:00 | Baker Island") # Add UTC options
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

        # Set default UTC offset
        self.cbUTCOffset.setCurrentIndex(14) # UTC+00:00 default
        if Logic.debug: print("[DEBUG] uiOptions initialized")

    def showEvent(self, event):
        Logic.centerWindowToParent(self) # Center on parent
        super().showEvent(event)
        self.loadSettings() # Load settings
        self.tabWidget.setCurrentIndex(0) # Default to general tab
        if Logic.debug: print("[DEBUG] uiOptions showEvent")

    def eventFilter(self, obj, event):
        if obj == self.qleAQPassword and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimer.isActive():
                self.lastCharTimer.stop() # Stop timer to prevent overlap
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal) # Show AQ password
            self.lastCharTimer.start(500) # 500ms re-mask
            if Logic.debug: print("[DEBUG] AQ password keypress, showing temporarily")
        elif obj == self.qleUSGSAPIKey and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimerUSGS.isActive():
                self.lastCharTimerUSGS.stop() # Stop timer to prevent overlap
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal) # Show USGS key
            self.lastCharTimerUSGS.start(500) # 500ms re-mask
            if Logic.debug: print("[DEBUG] USGS API key keypress, showing temporarily")
        elif obj == self.qleUSGSAPIKey and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimerUSGS.isActive():
                self.lastCharTimerUSGS.stop() # Stop timer for paste
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal) # Show for paste
            self.lastCharTimerUSGS.start(500) # 500ms re-mask
            if Logic.debug: print("[DEBUG] USGS API key paste, showing temporarily")
        elif obj == self.qleAQPassword and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimer.isActive():
                self.lastCharTimer.stop() # Stop timer for paste
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal) # Show for paste
            self.lastCharTimer.start(500) # 500ms re-mask
            if Logic.debug: print("[DEBUG] AQ password paste, showing temporarily")
        return super().eventFilter(obj, event)

    def maskLastChar(self):
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password) # Re-mask AQ password
        if Logic.debug: print("[DEBUG] AQ password re-masked")

    def maskLastCharUSGS(self):
        self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password) # Re-mask USGS key
        if Logic.debug: print("[DEBUG] USGS API key re-masked")

    def loadSettings(self):
        configPath = Logic.getConfigPath() # Get JSON path
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile) # Read JSON
                if Logic.debug: print("[DEBUG] Loaded config from user.config: {}".format(config))
            except Exception as e:
                if Logic.debug: print("[ERROR] Failed to load user.config: {}".format(e))

        utcOffset = config.get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London") # Get UTC string
        index = self.cbUTCOffset.findText(utcOffset)

        if index != -1:
            self.cbUTCOffset.setCurrentIndex(index) # Set UTC
            if Logic.debug: print("[DEBUG] Set cbUTCOffset to: {}".format(utcOffset))
        else:
            self.cbUTCOffset.setCurrentIndex(14) # Default UTC+00:00
            if Logic.debug: print("[DEBUG] utcOffset '{}' not found, set to default UTC+00:00".format(utcOffset))
        self.cbRetroMode.setChecked(bool(config.get('retroMode', True))) # Set retro
        if Logic.debug: print("[DEBUG] Set cbRetroMode to: {}".format(self.cbRetroMode.isChecked()))
        self.cbQAQC.setChecked(bool(config.get('qaqc', True))) # Set QAQC
        if Logic.debug: print("[DEBUG] Set cbQAQC to: {}".format(self.cbQAQC.isChecked()))
        self.cbRawData.setChecked(bool(config.get('rawData', False))) # Set raw
        if Logic.debug: print("[DEBUG] Set cbRawData to: {}".format(self.cbRawData.isChecked()))
        self.cbDebug.setChecked(bool(config.get('debugMode', False))) # Set debug
        if Logic.debug: print("[DEBUG] Set cbDebug to: {}".format(self.cbDebug.isChecked()))
        tnsPath = config.get('tnsNamesLocation', '') # Get TNS path
        if tnsPath.startswith(Logic.appRoot):
            tnsPath = tnsPath.replace(Logic.appRoot, '%AppRoot%') # Shorten path
        self.textTNSNames.setPlainText(tnsPath) # Set TNS path

        if not self.textTNSNames.toPlainText():
            envTns = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin')) # Default TNS
            if envTns.startswith(Logic.appRoot):
                envTns = envTns.replace(Logic.appRoot, '%AppRoot%') # Shorten
            self.textTNSNames.setPlainText(envTns) # Set TNS

        if Logic.debug: print("[DEBUG] Set textTNSNames to: {}".format(tnsPath))
        hourMethod = config.get('hourTimestampMethod', 'EOP') # Get period

        if hourMethod == 'EOP':
            self.rbEOP.setChecked(True) # Set EOP
        else:
            self.rbBOP.setChecked(True) # Set BOP
        if Logic.debug: print("[DEBUG] Set hourTimestampMethod to: {}".format(hourMethod))

        try:
            self.textAQServer.setPlainText(keyring.get_password("DataDoctor", "aqServer") or "") # Load AQ server
            self.textAQUser.setPlainText(keyring.get_password("DataDoctor", "aqUser") or "") # Load AQ user
            self.qleAQPassword.setText(keyring.get_password("DataDoctor", "aqPassword") or "") # Load AQ password
            self.qleUSGSAPIKey.setText(keyring.get_password("DataDoctor", "usgsApiKey") or "") # Load USGS key
            if Logic.debug: print("[DEBUG] Successfully loaded keyring credentials")
        except Exception as e:
            if Logic.debug: print("[ERROR] Failed to load keyring credentials: {}. Using empty strings".format(e))
            self.textAQServer.setPlainText("") # Fallback
            self.textAQUser.setPlainText("") # Fallback
            self.qleAQPassword.setText("") # Fallback
            self.qleUSGSAPIKey.setText("") # Fallback
        if Logic.debug: print("[DEBUG] Settings loaded")

    def onSavePressed(self):
        configPath = Logic.getConfigPath() # Get JSON path
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile) # Read existing
                if Logic.debug: print("[DEBUG] Read existing user.config: {}".format(config))
            except Exception as e:
                if Logic.debug: print("[ERROR] Failed to load user.config for save: {}".format(e))

        previousRetro = config.get('retroMode', True) # Save previous retro
        newRetro = self.cbRetroMode.isChecked()
        tnsPath = self.textTNSNames.toPlainText() # Get TNS path

        if '%AppRoot%' in tnsPath:
            tnsPath = tnsPath.replace('%AppRoot%', Logic.appRoot) # Expand path
        config.update({
            'utcOffset': self.cbUTCOffset.currentText(), # Save UTC
            'retroMode': newRetro, # Save retro
            'qaqc': self.cbQAQC.isChecked(), # Save QAQC
            'rawData': self.cbRawData.isChecked(), # Save raw
            'debugMode': self.cbDebug.isChecked(), # Save debug
            'tnsNamesLocation': tnsPath, # Save TNS
            'hourTimestampMethod': 'EOP' if self.rbEOP.isChecked() else 'BOP', # Save period
            'lastExportPath': config.get('lastExportPath', '') # Preserve export
        })

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2) # Write JSON
        if Logic.debug: print("[DEBUG] Saved user.config with retroMode: {}".format(newRetro))

        Logic.reloadGlobals() # Reload globals

        if newRetro != previousRetro:
            reply = QMessageBox.question(self, "Retro Mode Change", "Restart DataDoctor for the retro mode change to take effect?\nOK to restart now, Cancel to revert to previous setting.", QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Ok:
                python = sys.executable
                os.execl(python, python, *sys.argv) # Relaunch app
            else:
                self.cbRetroMode.setChecked(previousRetro) # Revert checkbox
                config['retroMode'] = previousRetro # Update config
                with open(configPath, 'w', encoding='utf-8') as configFile:
                    json.dump(config, configFile, indent=2) # Write reverted
                Logic.reloadGlobals() # Reload globals
                if Logic.debug: print("[DEBUG] Reverted retro mode to {}".format(previousRetro))

        # Save credentials to keyring with validation
        credentials = [
            ("aqServer", self.textAQServer.toPlainText()),
            ("aqUser", self.textAQUser.toPlainText()),
            ("aqPassword", self.qleAQPassword.text()),
            ("usgsApiKey", self.qleUSGSAPIKey.text())
        ]

        for key, value in credentials:
            if value and isinstance(value, str) and value.strip(): # Save only valid strings
                try:
                    keyring.set_password("DataDoctor", key, value) # Save to keyring
                    if Logic.debug: print("[DEBUG] Saved {} to keyring".format(key))
                except Exception as e:
                    if Logic.debug: print("[ERROR] Failed to save {} to keyring: {}".format(key, e))
                    QMessageBox.warning(self, "Credential Save Error", "Failed to save {}: {}".format(key, e))
            elif Logic.debug:
                print("[DEBUG] Skipped saving {} to keyring: empty or invalid".format(key))

    def togglePasswordVisibility(self):
        if self.lastCharTimer.isActive():
            self.lastCharTimer.stop() # Stop timer to prevent conflict
        if self.qleAQPassword.echoMode() == QLineEdit.EchoMode.Password:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal) # Show AQ password
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png'))) # Update icon
            if Logic.debug: print("[DEBUG] AQ password shown via button")
        else:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password) # Mask AQ password
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png'))) # Update icon
            if Logic.debug: print("[DEBUG] AQ password masked via button")

    def toggleUSGSKeyVisibility(self):
        if self.lastCharTimerUSGS.isActive():
            self.lastCharTimerUSGS.stop() # Stop timer to prevent conflict
        if self.qleUSGSAPIKey.echoMode() == QLineEdit.EchoMode.Password:
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal) # Show USGS key
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png'))) # Update icon
            if Logic.debug: print("[DEBUG] USGS API key shown via button")
        else:
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password) # Mask USGS key
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png'))) # Update icon
            if Logic.debug: print("[DEBUG] USGS API key masked via button")

class uiAbout(QDialog):
    """About dialog: Retro PNG bg with transparent info overlay and looping sound."""
    def __init__(self, parent=None):
        super(uiAbout, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winAbout.ui'), self) # Load the .ui file

        # Define controls
        self.backgroundLabel = self.findChild(QLabel, 'backgroundLabel')
        self.textInfo = self.findChild(QTextBrowser, 'textInfo') # For overlay

        # Set window size
        self.setFixedSize(900, 479)

        # Set window title
        self.setWindowTitle('About Data Doctor')

        # Load PNG bg (scale to window)
        pngPath = Logic.resourcePath('ui/DataDoctor.png')
        pixmap = QPixmap(pngPath)
        scaledPixmap = pixmap.scaled(900, 479, Qt.AspectRatioMode.KeepAspectRatio) # Preserve aspect
        self.backgroundLabel.setPixmap(scaledPixmap)
        self.backgroundLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Load pixel font
        fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
        fontId = QFontDatabase.addApplicationFont(fontPath)
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0] if fontId != -1 else "Courier" # Fallback monospace
        retroFontObj = QFont(fontFamily, 10) # Fixed size
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing for crisp retro
        self.textInfo.setFont(retroFontObj) # Explicit for bypass

        # Info list: easy-edit tuples (label, content)
        infoList = [
            ('Version', '3.0.0'),
            ('GitHub', 'https://github.com/S31F3R/DataDoctor'),
            ('Author', 'S31F3R'),
            ('License', 'GPL-3.0'),
            ('Music', 'By Eric Matyas at www.soundimage.org')
        ]

        # Build HTML for textInfo: small white, clickable GitHub, left-padded, no wrap, spaced lines
        htmlContent = '<html><body style="color: white; font-family: \'' + fontFamily + '\'; font-size: 10pt; padding-left: 50px; white-space: nowrap; line-height: 2.0;">' # No wrap, tweak 10pt/50px/line 2.0

        for label, content in infoList:
            if 'GitHub' in label: # Clickable link
                htmlContent += f'{label}: <a href="{content}" style="color: white;">{content}</a><br>'
            else:
                htmlContent += f'{label}: {content}<br>'

        htmlContent += '</body></html>'
        self.textInfo.setHtml(htmlContent)
        self.textInfo.setOpenExternalLinks(True) # Opens GitHub in browser

        # Transparent bg for textInfo overlay
        self.textInfo.setStyleSheet("background-color: transparent; border: none;") # No bg/border

        # Position textInfo overlay
        self.textInfo.setGeometry(70, 140, 800, 200)

        # Audio setup (QSoundEffect infinite loop at 80% vol)
        self.soundEffect = None
        
        try:
            wavPath = Logic.resourcePath('ui/sounds/8-Bit-Perplexion.wav')
            self.soundEffect = QSoundEffect(self)
            self.soundEffect.setSource(QUrl.fromLocalFile(wavPath))
            self.soundEffect.setLoopCount(QSoundEffect.Infinite) # Infinite loop
            self.soundEffect.setVolume(0.8) # 80% (tweak 0.0-1.0)           
        except Exception as e: # Silent fail if missing/error
            return

    def showEvent(self, event):
        Logic.centerWindowToParent(self) # Center on parent

        if self.soundEffect:
            self.soundEffect.play() # Start infinite loop

        super().showEvent(event)

    def closeEvent(self, event):
        if self.soundEffect:
            self.soundEffect.stop() # Stop loop

        super().closeEvent(event)

# Create an instance of QApplication
app = QApplication(sys.argv)
app.setApplicationName("Data Doctor")

# Create an instance of our class
winMain = uiMain()
winWebQuery = uiWebQuery(winMain) # Pass parent
winInternalQuery = uiInternalQuery(winMain) # Pass parent
winDataDictionary = uiDataDictionary(winMain) # Pass parent
winQuickLook = uiQuickLook(winMain) # Pass parent
winOptions = uiOptions(winMain) # Pass Parent
winAbout = uiAbout(winMain) # Pass Parent

# Load config
config = Logic.loadConfig()
Logic.debug = config['debugMode']
Logic.utcOffset = config['utcOffset']
Logic.periodOffset = config['periodOffset'] # True for EOP
Logic.retroMode = config.get('retroMode', True) # Set global

# Apply retro font if enabled
if Logic.retroMode:
    fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
    fontId = QFontDatabase.addApplicationFont(fontPath)
    if fontId != -1:
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
        retroFontObj = QFont(fontFamily, 10) # Fixed size
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing for crisp retro
        app.setFont(retroFontObj)
        if Logic.debug: print("[DEBUG] Applied retro font at startup")
    Logic.setRetroStyles(app, True, winMain.mainTable, winWebQuery.listQueryList, winInternalQuery.listQueryList) # Apply retro styles
else:
    Logic.setRetroStyles(app, False, winMain.mainTable, winWebQuery.listQueryList, winInternalQuery.listQueryList) # Reset styles

# Load stylesheet
with open(Logic.resourcePath('ui/stylesheet.qss'), 'r') as f:
    app.setStyleSheet(f.read())

# Load in data dictionary
Logic.buildDataDictionary(winDataDictionary.mainTable)

# Load quick looks for both windows
Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)
Logic.loadAllQuickLooks(winInternalQuery.cbQuickLook)

# Start the application
app.exec()