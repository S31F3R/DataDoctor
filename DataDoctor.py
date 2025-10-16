import sys
import QueryUSBR
import QueryUSGS
import QueryAquarius
import Logic
import datetime
import configparser
import keyring
import os
import json
from PyQt6.QtGui import QGuiApplication, QIcon, QFont, QFontDatabase, QPixmap 
from PyQt6.QtCore import Qt, QEvent, QTimer, QUrl 
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QVBoxLayout,
                             QTextEdit, QComboBox, QDateTimeEdit, QListWidget, QWidget, QGridLayout,
                             QMessageBox, QDialog, QSizePolicy, QTabWidget, QRadioButton, QButtonGroup,
                             QDialogButtonBox, QLineEdit, QLabel, QTextBrowser, QCheckBox)
from datetime import datetime, timedelta
from PyQt6 import uic
from PyQt6.QtMultimedia import QSoundEffect
from collections import defaultdict
import keyring
from keyring.backends.null import Keyring as NullKeyring # Safe fallback if needed

# No backend forcing: Rely on keyring defaults (KWallet on KDE/Linux, Credential Manager on Windows, Keychain on macOS)

class uiMain(QMainWindow):
    """Main window for DataDoctor: Handles core UI, queries, and exports."""
    def __init__(self):
        super(uiMain, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi(Logic.resourcePath('ui/winMain.ui'), self) # Load the .ui file   
        
        # Define the controls
        self.btnPublicQuery = self.findChild(QPushButton, 'btnPublicQuery')
        self.mainTable = self.findChild(QTableWidget, 'mainTable')          
        self.btnDataDictionary = self.findChild(QPushButton,'btnDataDictionary')           
        self.btnExportCSV = self.findChild(QPushButton, 'btnExportCSV')       
        self.btnOptions = self.findChild(QPushButton, 'btnOptions')   
        self.btnInfo = self.findChild(QPushButton, 'btnInfo')    
        self.btnInternalQuery = self.findChild(QPushButton, 'btnInternalQuery')

        # Set button style
        Logic.buttonStyle(self.btnPublicQuery)
        Logic.buttonStyle(self.btnDataDictionary)        
        Logic.buttonStyle(self.btnExportCSV)
        Logic.buttonStyle(self.btnOptions)
        Logic.buttonStyle(self.btnInfo)
        Logic.buttonStyle(self.btnInternalQuery)
        
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

        # Center window when opened
        rect = self.frameGeometry()
        centerPoint = QGuiApplication.primaryScreen().availableGeometry().center()
        rect.moveCenter(centerPoint)
        self.move(rect.topLeft())
        
        # Show the GUI on application start
        self.show()      

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
        self.cbInterval.addItem('HOUR') # Hourly data
        self.cbInterval.addItem('INSTANT') # Instantaneous data
        self.cbInterval.addItem('DAY') # Daily data

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
        
        # Get start/end dates
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm') # Format for query
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm') # Format for query
        
        # Collect and parse query items
        queryItems = []
        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Logic.debug: print(f"[DEBUG] Item text: '{itemText}', parts: {parts}, len: {len(parts)}")
            if len(parts) != 3:
                print(f"[WARN] Invalid item skipped: {itemText}")
                continue

            dataID, interval, database = parts
            mrid = '0' # Default MRID
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1) # Split SDID-MRID
            queryItems.append((dataID, interval, database, mrid, i)) # Include orig index

            if Logic.debug: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        
        # Add single query from qleDataID if list empty
        if not queryItems and self.qleDataID.text().strip():
            dataID = self.qleDataID.text().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0' # Default
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, 0)) # origIndex=0

            if Logic.debug: print(f"[DEBUG] Added single query: {(dataID, interval, database, mrid, 0)}")
        elif not queryItems:
            print("[WARN] No valid query items.")
            return
        
        # Sort by original index
        queryItems.sort(key=lambda x: x[4]) # Ensure order
        
        # First interval for timestamps
        firstInterval = queryItems[0][1]
        firstDb = queryItems[0][2] # First database

        if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
            firstInterval = 'HOUR' # USBR INSTANT quirk
        timestamps = Logic.buildTimestamps(startDate, endDate, firstInterval)

        if not timestamps:
            QMessageBox.warning(self, "Date Error", "Invalid dates or interval.")
            return
        
        # Default blanks for missing data
        defaultBlanks = [''] * len(timestamps)
        
        # Group by (db, mrid, interval)
        groups = defaultdict(list)

        for dataID, interval, db, mrid, origIndex in queryItems:
            groupKey = (db, mrid if db.startswith('USBR-') else None, interval)
            groups[groupKey].append((origIndex, dataID)) # Group by key

        if Logic.debug: print(f"[DEBUG] Formed {len(groups)} groups.")
        
        # Collect values
        valueDict = {}
        for (db, mrid, interval), groupItems in groups.items():
            if Logic.debug: print(f"[DEBUG] Processing group: db={db}, mrid={mrid}, interval={interval}, items={len(groupItems)}")
            SDIDs = []

            for origIndex, dataID in groupItems:
                SDID = dataID

                if db.startswith('USBR-') and '-' in dataID:
                    SDID, _ = dataID.rsplit('-', 1) # Recalc SDID
                SDIDs.append(SDID)
            try:
                if db.startswith('USBR-'):
                    svr = db.split('-')[1].lower()
                    table = 'M' if mrid != '0' else 'R'
                    result = QueryUSBR.apiRead(svr, SDIDs, startDate, endDate, interval, mrid, table)
                elif db == 'USGS-NWIS':
                    result = QueryUSGS.apiRead(SDIDs, interval, startDate, endDate)
                else:
                    print(f"[WARN] Unknown db skipped: {db}")
                    continue
            except Exception as e:
                QMessageBox.warning(self, "Query Error", f"Query failed for group {db}: {e}")
                continue
            for idx, (origIndex, dataID) in enumerate(groupItems):
                SDID = SDIDs[idx]

                if SDID in result:
                    outputData = result[SDID]
                    alignedData = Logic.gapCheck(timestamps, outputData, dataID)
                    values = [line.split(',')[1] if line else '' for line in alignedData]
                    valueDict[dataID] = values
                else:
                    valueDict[dataID] = defaultBlanks # Full blanks
                if Logic.debug: print(f"[DEBUG] Processed dataID {dataID}: {len(valueDict[dataID])} values")
        
        # Recombine in original order
        originalDataIds = [item[0] for item in queryItems] # dataID
        originalIntervals = [item[1] for item in queryItems] # For labels
        lookupIds = []

        for item in queryItems:
            dataID, interval, db, mrid, origIndex = item
            lookupId = dataID

            if db.startswith('USBR-') and '-' in dataID:
                lookupId = dataID.split('-')[0] # Base SDID
            lookupIds.append(lookupId)
        
        # Build data
        data = []

        for r in range(len(timestamps)):
            rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
            data.append(f"{timestamps[r]},{','.join(rowValues)}")

        if Logic.debug: print(f"[DEBUG] Built {len(data)} data rows")
        
        # Build headers
        buildHeader = originalDataIds
        intervalsForHeaders = originalIntervals
        
        # Build table
        winMain.mainTable.clear() # Clear existing
        Logic.buildTable(winMain.mainTable, data, buildHeader, winDataDictionary.mainTable, intervalsForHeaders, lookupIds)
        
        # Show tab if hidden
        if winMain.tabWidget.indexOf(winMain.tabMain) == -1:
            winMain.tabWidget.addTab(winMain.tabMain, 'Data Query') # Show Data Query tab
        
        # Close query window
        self.close()

        if Logic.debug: print("[DEBUG] Web query window closed after query")

    def btnAddQueryPressed(self):
        item = f'{self.qleDataID.text().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}' # Build query item
        self.listQueryList.addItem(item) # Add to list
        self.qleDataID.clear() # Clear input
        self.qleDataID.setFocus() # Refocus

        if Logic.debug: print(f"[DEBUG] Added query item: {item}")

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
        self.cbInterval.addItem('HOUR') # Hourly data
        self.cbInterval.addItem('INSTANT') # Instantaneous data
        self.cbInterval.addItem('DAY') # Daily data

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
        
        # Get start/end dates
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm') # Format for query
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm') # Format for query
        
        # Collect and parse query items
        queryItems = []
        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Logic.debug: print(f"[DEBUG] Item text: '{itemText}', parts: {parts}, len: {len(parts)}")
            if len(parts) != 3:
                print(f"[WARN] Invalid item skipped: {itemText}")
                continue
            dataID, interval, database = parts
            mrid = '0' # Default MRID
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1) # Split SDID-MRID
            queryItems.append((dataID, interval, database, mrid, i)) # Include orig index

            if Logic.debug: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        
        # Add single query from qleDataID if list empty
        if not queryItems and self.qleDataID.text().strip():
            dataID = self.qleDataID.text().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0' # Default
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)
            queryItems.append((dataID, interval, database, mrid, 0)) # origIndex=0
            if Logic.debug: print(f"[DEBUG] Added single query: {(dataID, interval, database, mrid, 0)}")
        elif not queryItems:
            print("[WARN] No valid query items.")
            return
        
        # Filter out USGS-NWIS items (from quickLooks)
        queryItems = [item for item in queryItems if item[2] != 'USGS-NWIS']

        if not queryItems:
            QMessageBox.warning(self, "No Valid Items", "No valid internal query items (USGS skipped).")
            return
        
        # Sort by original index
        queryItems.sort(key=lambda x: x[4]) # Ensure order
        
        # First interval for timestamps
        firstInterval = queryItems[0][1]
        firstDb = queryItems[0][2] # First database

        if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
            firstInterval = 'HOUR' # USBR INSTANT quirk

        timestamps = Logic.buildTimestamps(startDate, endDate, firstInterval)

        if not timestamps:
            QMessageBox.warning(self, "Date Error", "Invalid dates or interval.")
            return
        
        # Default blanks for missing data
        defaultBlanks = [''] * len(timestamps)
        labelsDict = {} # For Aquarius API labels
        
        # Group by (db, mrid, interval)
        groups = defaultdict(list)
        for dataID, interval, db, mrid, origIndex in queryItems:
            groupKey = (db, mrid if db.startswith('USBR-') else None, interval)
            groups[groupKey].append((origIndex, dataID)) # Group by key

        if Logic.debug: print(f"[DEBUG] Formed {len(groups)} groups.")
        
        # Collect values
        valueDict = {}
        for (db, mrid, interval), groupItems in groups.items():
            if Logic.debug: print(f"[DEBUG] Processing group: db={db}, mrid={mrid}, interval={interval}, items={len(groupItems)}")
            SDIDs = []

            for origIndex, dataID in groupItems:
                SDID = dataID

                if db.startswith('USBR-') and '-' in dataID:
                    SDID, _ = dataID.rsplit('-', 1) # Recalc SDID
                SDIDs.append(SDID)
            try:
                if db.startswith('USBR-'):
                    svr = db.split('-')[1].lower()
                    table = 'M' if mrid != '0' else 'R'
                    result = QueryUSBR.apiRead(svr, SDIDs, startDate, endDate, interval, mrid, table)
                elif db == 'AQUARIUS':
                    result = QueryAquarius.apiRead(SDIDs, startDate, endDate, interval)
                else:
                    print(f"[WARN] Unknown db skipped: {db}")
                    continue
            except Exception as e:
                QMessageBox.warning(self, "Query Error", f"Query failed for group {db}: {e}")
                continue
            for idx, (origIndex, dataID) in enumerate(groupItems):
                SDID = SDIDs[idx]

                if SDID in result:
                    if db == 'AQUARIUS':
                        outputData = result[SDID]['data']
                        labelsDict[dataID] = result[SDID].get('label', dataID)
                    else:
                        outputData = result[SDID]
                    alignedData = Logic.gapCheck(timestamps, outputData, dataID)
                    values = [line.split(',')[1] if line else '' for line in alignedData]
                    valueDict[dataID] = values
                else:
                    valueDict[dataID] = defaultBlanks # Full blanks
                if Logic.debug: print(f"[DEBUG] Processed dataID {dataID}: {len(valueDict[dataID])} values")
        
        # Recombine in original order
        originalDataIds = [item[0] for item in queryItems] # dataID
        originalIntervals = [item[1] for item in queryItems] # For labels
        lookupIds = []

        for item in queryItems:
            dataID, interval, db, mrid, origIndex = item
            lookupId = dataID

            if db.startswith('USBR-') and '-' in dataID:
                lookupId = dataID.split('-')[0] # Base SDID
            lookupIds.append(lookupId)
        
        # Build data
        data = []

        for r in range(len(timestamps)):
            rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
            data.append(f"{timestamps[r]},{','.join(rowValues)}")

        if Logic.debug: print(f"[DEBUG] Built {len(data)} data rows")
        
        # Build headers
        buildHeader = originalDataIds
        intervalsForHeaders = originalIntervals
        
        # Build table
        winMain.mainTable.clear() # Clear existing
        Logic.buildTable(winMain.mainTable, data, buildHeader, winDataDictionary.mainTable, intervalsForHeaders, lookupIds, labelsDict)
        
        # Show tab if hidden
        if winMain.tabWidget.indexOf(winMain.tabMain) == -1:
            winMain.tabWidget.addTab(winMain.tabMain, 'Data Query') # Show Data Query tab
        
        # Close query window
        self.close()

        if Logic.debug: print("[DEBUG] Internal query window closed after query")

    def btnAddQueryPressed(self):
        item = f'{self.qleDataID.text().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}' # Build query item
        self.listQueryList.addItem(item) # Add to list
        self.qleDataID.clear() # Clear input
        self.qleDataID.setFocus() # Refocus

        if Logic.debug: print(f"[DEBUG] Added query item: {item}")

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

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed) # Save dictionary
        self.btnAddRow.clicked.connect(self.btnAddRowPressed) # Add row

        # Set button style
        Logic.buttonStyle(self.btnSave)
        Logic.buttonStyle(self.btnAddRow) 

    def showEvent(self, event):
        Logic.centerWindowToParent(self) # Center on parent
        super().showEvent(event)

    def btnSavePressed(self):
        data = [] # Initialize data list

        with open(Logic.resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') as f:
            data.append(f.readlines()[0]) # Keep header

        for r in range(self.mainTable.rowCount()):
            rowData = []

            for c in range(self.mainTable.columnCount()):
                item = self.mainTable.item(r, c)
                rowData.append(item.text() if item else '') # Collect row data
            data.append(','.join(rowData)) # Add row as CSV

        with open(Logic.resourcePath('DataDictionary.csv'), 'w', encoding='utf-8-sig') as f:
            f.writelines('\n'.join(data)) # Write CSV
        for c in range(self.mainTable.columnCount()):
            self.mainTable.resizeColumnToContents(c) # Auto-size columns

        if Logic.debug: print("[DEBUG] DataDictionary saved and columns resized")
    
    def btnAddRowPressed(self):
        self.mainTable.setRowCount(self.mainTable.rowCount() + 1) # Add new row
        if Logic.debug: print("[DEBUG] Added row to DataDictionary")
        
class uiQuickLook(QDialog):
    """Quick look save dialog: Names and stores query presets."""
    def __init__(self, parent=None):
        super(uiQuickLook, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winQuickLook.ui'), self) # Load the .ui file

        # Define the controls
        self.btnSave = self.findChild(QPushButton, 'btnSave')   
        self.btnCancel = self.findChild(QPushButton, 'btnCancel')  
        self.textQuickLookName = self.findChild(QTextEdit,'textQuickLookName')  

        # Temp attrs for dynamic query widgets
        self.currentListQueryList = None
        self.CurrentCbQuickLook = None

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnCancel.clicked.connect(self.btnCancelPressed)  

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self):       
        # Save quick look
        if self.currentListQueryList and self.CurrentCbQuickLook:
            Logic.saveQuickLook(self.textQuickLookName, winWebQuery.listQueryList)

            # Load quick looks
            Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)

        # Clear the controls
        self.clear()

        # Close the window
        winQuickLook.close() 

    def btnCancelPressed(self): 
        # Clear the controls
        self.clear()

        # Close the window
        winQuickLook.close() 

    def clear(self):
        # Clear all controls
        self.textQuickLookName.clear()

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
        self.cbRetroFont = self.findChild(QCheckBox, 'cbRetroFont') # Retro font toggle
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
        self.cbUTCOffset.addItem("UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, \nLisbon, London")
        self.cbUTCOffset.addItem("UTC+01:00 | Central European Time : Amsterdam, Berlin, Bern, \nRome, Stockholm, Vienna")
        self.cbUTCOffset.addItem("UTC+02:00 | Eastern European Time : Athens, Bucharest, \nIstanbul")
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
                if Logic.debug: print(f"[DEBUG] Loaded config from user.config: {config}")
            except Exception as e:
                if Logic.debug: print(f"[ERROR] Failed to load user.config: {e}")
        utcOffset = config.get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, \nLisbon, London") # Get UTC
        index = self.cbUTCOffset.findText(utcOffset)
        if index != -1:
            self.cbUTCOffset.setCurrentIndex(index) # Set UTC
            if Logic.debug: print(f"[DEBUG] Set cbUTCOffset to {utcOffset}")
        else:
            self.cbUTCOffset.setCurrentIndex(14) # Default UTC+00:00
            if Logic.debug: print("[DEBUG] utcOffset not found, set to default UTC+00:00")
        self.cbRetroFont.setChecked(bool(config.get('retroFont', True))) # Set retro
        if Logic.debug: print(f"[DEBUG] Set cbRetroFont to {self.cbRetroFont.isChecked()}")
        self.cbQAQC.setChecked(bool(config.get('qaqc', True))) # Set QAQC
        if Logic.debug: print(f"[DEBUG] Set cbQAQC to {self.cbQAQC.isChecked()}")
        self.cbRawData.setChecked(bool(config.get('rawData', False))) # Set raw
        if Logic.debug: print(f"[DEBUG] Set cbRawData to {self.cbRawData.isChecked()}")
        self.cbDebug.setChecked(bool(config.get('debugMode', False))) # Set debug
        if Logic.debug: print(f"[DEBUG] Set cbDebug to {self.cbDebug.isChecked()}")
        tnsPath = config.get('tnsNamesLocation', '') # Get TNS path
        if tnsPath.startswith(Logic.appRoot):
            tnsPath = tnsPath.replace(Logic.appRoot, '%AppRoot%') # Shorten path
        self.textTNSNames.setPlainText(tnsPath) # Set TNS path
        if not self.textTNSNames.toPlainText():
            envTns = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin')) # Default TNS
            if envTns.startswith(Logic.appRoot):
                envTns = envTns.replace(Logic.appRoot, '%AppRoot%') # Shorten
            self.textTNSNames.setPlainText(envTns) # Set TNS
        if Logic.debug: print(f"[DEBUG] Set textTNSNames to {tnsPath}")
        hourMethod = config.get('hourTimestampMethod', 'EOP') # Get period
        if hourMethod == 'EOP':
            self.rbEOP.setChecked(True) # Set EOP
        else:
            self.rbBOP.setChecked(True) # Set BOP
        if Logic.debug: print(f"[DEBUG] Set hourTimestampMethod to {hourMethod}")
        self.textAQServer.setPlainText(keyring.get_password("DataDoctor", "aqServer") or "") # Load AQ server
        self.textAQUser.setPlainText(keyring.get_password("DataDoctor", "aqUser") or "") # Load AQ user
        self.qleAQPassword.setText(keyring.get_password("DataDoctor", "aqPassword") or "") # Load AQ password
        self.qleUSGSAPIKey.setText(keyring.get_password("DataDoctor", "usgsApiKey") or "") # Load USGS key
        if Logic.debug: print("[DEBUG] Settings loaded")

    def onSavePressed(self):
        configPath = Logic.getConfigPath() # Get JSON path
        config = {}
        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile) # Read existing
                if Logic.debug: print(f"[DEBUG] Read existing user.config: {config}")
            except Exception as e:
                if Logic.debug: print(f"[ERROR] Failed to load user.config for save: {e}")
        previousRetro = config.get('retroFont', True) # Save previous retro
        tnsPath = self.textTNSNames.toPlainText() # Get TNS path
        if '%AppRoot%' in tnsPath:
            tnsPath = tnsPath.replace('%AppRoot%', Logic.appRoot) # Expand path
        config.update({
            'utcOffset': self.cbUTCOffset.currentText(), # Save UTC
            'retroFont': self.cbRetroFont.isChecked(), # Save retro
            'qaqc': self.cbQAQC.isChecked(), # Save QAQC
            'rawData': self.cbRawData.isChecked(), # Save raw
            'debugMode': self.cbDebug.isChecked(), # Save debug
            'tnsNamesLocation': tnsPath, # Save TNS
            'hourTimestampMethod': 'EOP' if self.rbEOP.isChecked() else 'BOP', # Save period
            'colorMode': config.get('colorMode', 'light'), # Preserve color
            'lastExportPath': config.get('lastExportPath', '') # Preserve export
        })
        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2) # Write JSON
        if Logic.debug: print("[DEBUG] Saved user.config")
        Logic.reloadGlobals() # Reload globals
        if self.cbRetroFont.isChecked():
            fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf') # Load retro font
            fontId = QFontDatabase.addApplicationFont(fontPath)
            if fontId != -1:
                fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
                retroFontObj = QFont(fontFamily, 10) # Fixed size
                retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing
                app.setFont(retroFontObj) # Set app font
                for window in [winMain, winWebQuery, winDataDictionary, winQuickLook, winOptions, winAbout]:
                    Logic.applyRetroFont(window) # Apply to all windows
                if Logic.debug: print("[DEBUG] Applied retro font")
        else:
            app.setFont(QFont()) # System default font
            if Logic.debug: print("[DEBUG] Reverted to system font")
        newRetro = self.cbRetroFont.isChecked()
        if newRetro != previousRetro:
            reply = QMessageBox.question(self, "Font Change", "Restart DataDoctor for the font change to take effect?\nOK to restart now, Cancel to revert to previous setting.", QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Ok:
                python = sys.executable
                os.execl(python, python, *sys.argv) # Relaunch app
            else:
                self.cbRetroFont.setChecked(previousRetro) # Revert checkbox
                config['retroFont'] = previousRetro # Update config
                with open(configPath, 'w', encoding='utf-8') as configFile:
                    json.dump(config, configFile, indent=2) # Write reverted
                Logic.reloadGlobals() # Reload globals
                if Logic.debug: print("[DEBUG] Reverted retro font setting")
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
                    if Logic.debug: print(f"[DEBUG] Saved {key} to keyring")
                except Exception as e:
                    if Logic.debug: print(f"[ERROR] Failed to save {key} to keyring: {e}")
                    QMessageBox.warning(self, "Credential Save Error", f"Failed to save {key}: {e}")
            elif Logic.debug:
                print(f"[DEBUG] Skipped saving {key} to keyring: empty or invalid")

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
Logic.retroFont = config.get('retroFont', True) # Set global

# Apply retro font if enabled
if Logic.retroFont:
    fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
    fontId = QFontDatabase.addApplicationFont(fontPath)

    if fontId != -1:
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
        retroFontObj = QFont(fontFamily, 10) # Fixed size
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing for crisp retro
        app.setFont(retroFontObj)

# Load minimal qss if system dark
if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark:
    qssPath = Logic.resourcePath('ui/stylesheet.qss')
    
    with open(qssPath, 'r') as f:
        app.setStyleSheet(f.read())

# Load in data dictionary
Logic.buildDataDictionary(winDataDictionary.mainTable) 

# Load quick looks for both windows
Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)
Logic.loadAllQuickLooks(winInternalQuery.cbQuickLook)

# Start the application
app.exec()