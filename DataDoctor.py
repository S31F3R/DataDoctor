import sys
import QueryUSBR
import QueryUSGS
import QueryAquarius
import Logic
import datetime
import configparser
import keyring
import os
from PyQt6.QtGui import QGuiApplication, QIcon, QFont, QFontDatabase, QPixmap 
from PyQt6.QtCore import Qt, QEvent, QTimer, QUrl 
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QVBoxLayout,
                             QTextEdit, QComboBox, QDateTimeEdit, QListWidget, QWidget, QGridLayout,
                             QMessageBox, QDialog, QSizePolicy, QTabWidget, QRadioButton,
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
        super(uiWebQuery, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winWebQuery.ui'), self)

        # Define the controls
        self.btnQuery = self.findChild(QPushButton, 'btnQuery')    
        self.textSDID = self.findChild(QTextEdit,'textSDID')    
        self.cbDatabase = self.findChild(QComboBox,'cbDatabase')  
        self.cbInterval = self.findChild(QComboBox,'cbInterval')
        self.dteStartDate = self.findChild(QDateTimeEdit, 'dteStartDate')
        self.dteEndDate = self.findChild(QDateTimeEdit, 'dteEndDate')
        self.listQueryList = self.findChild(QListWidget, 'listQueryList') 
        self.btnAddQuery = self.findChild(QPushButton,'btnAddQuery')
        self.btnRemoveQuery = self.findChild(QPushButton,'btnRemoveQuery')
        self.btnSaveQuickLook = self.findChild(QPushButton,'btnSaveQuickLook')
        self.cbQuickLook = self.findChild(QComboBox,'cbQuickLook')
        self.btnLoadQuickLook = self.findChild(QPushButton, 'btnLoadQuickLook') 
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery')
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo')
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo')

        # Set button style
        Logic.buttonStyle(self.btnDataIdInfo)  
        Logic.buttonStyle(self.btnIntervalInfo)     
        
        # Create events        
        self.btnQuery.clicked.connect(self.btnQueryPressed)  
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed) 
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed) 
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)   
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)     
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed)
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed)

        # Populate database combobox (public-specific)        
        self.cbDatabase.addItem('USBR-LCHDB') 
        self.cbDatabase.addItem('USBR-YAOHDB')  
        self.cbDatabase.addItem('USBR-UCHDB2') 
        self.cbDatabase.addItem('USGS-NWIS') 

        # Populate interval combobox        
        self.cbInterval.addItem('HOUR')   
        self.cbInterval.addItem('INSTANT')  
        self.cbInterval.addItem('DAY')  

        # Set default query times on DateTimeEdit controls        
        self.dteStartDate.setDateTime(datetime.now() - timedelta(hours = 72) )        
        self.dteEndDate.setDateTime(datetime.now())  

        # Load last quickLook from config
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath())

        if 'Settings' in config and 'lastQuickLook' in config['Settings']:
            lastQuickLook = config['Settings']['lastQuickLook']
            index = self.cbQuickLook.findText(lastQuickLook)
            if index != -1:
                self.cbQuickLook.setCurrentIndex(index)
        else:
            self.cbQuickLook.setCurrentIndex(-1) # Blank default        

        # Disable maximize button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

    def showEvent(self, event):
        if Logic.debug == True: print("[DEBUG] Query window showEvent, window:", self)
        Logic.centerWindowToParent(self)    
        self.cbQuickLook.setCurrentIndex(-1) # Remove this when lastQuickLook starts working
        super().showEvent(event)

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", f"AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", f"Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")

    def btnQueryPressed(self):
        if Logic.debug == True: print("[DEBUG] btnQueryPressed: Starting query process.")
        
        # Get start/end dates
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm')
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm')
        
        # Collect and parse query items
        queryItems = []

        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Logic.debug == True: print(f"[DEBUG] Item text: '{itemText}', parts: {parts}, len: {len(parts)}")

            if len(parts) != 3:
                print(f"[WARN] Invalid item skipped: {itemText}")
                continue

            dataID, interval, database = parts
            mrid = '0' # Default
            SDID = dataID

            if database.startswith('USBR-'):
                if '-' in dataID:
                    SDID, mrid = dataID.rsplit('-', 1) # Last - as mrid

            queryItems.append((dataID, interval, database, mrid, i)) # Include orig index
            if Logic.debug == True: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        
        # Add single query from textSDID if not empty and list blank
        if not queryItems and self.textSDID.toPlainText().strip():
            dataID = self.textSDID.toPlainText().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'  # Default
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)

            queryItems.append((dataID, interval, database, mrid, 0)) # origIndex=0

        elif not queryItems:
            print("[WARN] No valid query items.")
            return
        
        # Sort by orig index (though already in order)
        queryItems.sort(key=lambda x: x[4])
        
        # First interval for timestamps
        firstInterval = queryItems[0][1]
        firstDb = queryItems[0][2] # db of first

        if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
            firstInterval = 'HOUR' # Use hourly ts for USBR INSTANT quirk

        timestamps = Logic.buildTimestamps(startDate, endDate, firstInterval)

        if not timestamps:
            QMessageBox.warning(self, "Date Error", "Invalid dates or interval.")
            return
        
        # Default blanks for missing
        defaultBlanks = [''] * len(timestamps)
        
        # Group: dict of (db, mrid or None, interval) -> list of (origIndex, dataID)
        groups = defaultdict(list)

        for dataID, interval, db, mrid, origIndex in queryItems:
            groupKey = (db, mrid if db.startswith('USBR-') else None, interval)
            groups[groupKey].append((origIndex, dataID)) # Append dataID, recalc SDID later
        
        if Logic.debug == True: print(f"[DEBUG] Formed {len(groups)} groups.")
        
        # Collect values: dict {dataID: list of values len(timestamps)}
        valueSDIDct = {}
        
        for (db, mrid, interval), groupItems in groups.items():            
            if Logic.debug == True: print(f"[DEBUG] Processing group: db={db}, mrid={mrid}, interval={interval}, items={len(groupItems)}")
            
            # Recalc SDIDs per item
            SDIDs = []

            for origIndex, dataID in groupItems:
                SDID = dataID

                if db.startswith('USBR-'):
                    if '-' in dataID:
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
            
            # Map to dataID
            for idx, (origIndex, dataID) in enumerate(groupItems):
                SDID = SDIDs[idx]

                if SDID in result:
                    outputData = result[SDID]
                    alignedData = Logic.gapCheck(timestamps, outputData, dataID)
                    values = [line.split(',')[1] if line else '' for line in alignedData]
                    valueSDIDct[dataID] = values
                else:
                    valueSDIDct[dataID] = defaultBlanks # Full blanks
        
        # Recombine in original order
        originalDataIds = [item[0] for item in queryItems] # dataID
        originalIntervals = [item[1] for item in queryItems] # For labels

        # Build lookupIds for dict/QAQC (strip MRID for USBR)
        lookupIds = []

        for item in queryItems:
            dataID, interval, db, mrid, origIndex = item
            lookupId = dataID

            if db.startswith('USBR-') and '-' in dataID:
                lookupId = dataID.split('-')[0]  # Base SDID
            lookupIds.append(lookupId)
        
        # Build data: list of 'ts,value1,value2,...' strings
        data = []

        for r in range(len(timestamps)):
            rowValues = [valueSDIDct.get(dataID, defaultBlanks)[r] for dataID in originalDataIds] # val at r (str)
            data.append(f"{timestamps[r]},{','.join(rowValues)}")
        
        # Build headers: raw dataID for now, processed later
        buildHeader = originalDataIds
        
        # Intervals for labels
        intervalsForHeaders = originalIntervals
        
        # Build table
        winMain.mainTable.clear()
        Logic.buildTable(winMain.mainTable, data, buildHeader, winDataDictionary.mainTable, intervalsForHeaders, lookupIds)
        
        # Show tab if hidden
        if winMain.tabWidget.indexOf(winMain.tabMain) == -1:
            winMain.tabWidget.addTab(winMain.tabMain, 'Data Query')
        
        # Close query window
        winWebQuery.close()

    def btnAddQueryPressed(self):        
        item = f'{self.textSDID.toPlainText().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}'
        self.listQueryList.addItem(item)
        self.textSDID.clear()
        self.textSDID.setFocus()

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()       
        self.listQueryList.takeItem(self.listQueryList.row(item))

    def btnSaveQuickLookPressed(self):    
        # Set dynamic attrs for save/load
        winQuickLook.currentListQueryList = self.listQueryList 
        winQuickLook.CurrentCbQuickLook = self.cbQuickLook    
        winQuickLook.exec()

        # Re-raise/activate post-model to conuter Plasma focus loss
        self.raise_()
        self.activateWindow    
    
    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)

        # Save last selected quickLook to config
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath())

        if 'Settings' not in config:
            config['Settings'] = {}

        config['Settings']['lastQuickLook'] = self.cbQuickLook.currentText()

        with open(Logic.getConfigPath(), 'w') as configFile:
            config.write(configFile)

    def btnClearQueryPressed(self):
        self.listQueryList.clear()

class uiInternalQuery(QMainWindow):
    """Internal query window: Builds and executes internal queries."""
    def __init__(self, parent=None):
        super(uiInternalQuery, self).__init__(parent)
        uic.loadUi(Logic.resourcePath('ui/winInternalQuery.ui'), self)

        # Define the controls
        self.btnQuery = self.findChild(QPushButton, 'btnQuery')    
        self.textSDID = self.findChild(QTextEdit,'textSDID')    
        self.cbDatabase = self.findChild(QComboBox,'cbDatabase')  
        self.cbInterval = self.findChild(QComboBox,'cbInterval')
        self.dteStartDate = self.findChild(QDateTimeEdit, 'dteStartDate')
        self.dteEndDate = self.findChild(QDateTimeEdit, 'dteEndDate')
        self.listQueryList = self.findChild(QListWidget, 'listQueryList') 
        self.btnAddQuery = self.findChild(QPushButton,'btnAddQuery')
        self.btnRemoveQuery = self.findChild(QPushButton,'btnRemoveQuery')
        self.btnSaveQuickLook = self.findChild(QPushButton,'btnSaveQuickLook')
        self.cbQuickLook = self.findChild(QComboBox,'cbQuickLook')
        self.btnLoadQuickLook = self.findChild(QPushButton, 'btnLoadQuickLook') 
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery')
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo')
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo')

        # Set button style
        Logic.buttonStyle(self.btnDataIdInfo)  
        Logic.buttonStyle(self.btnIntervalInfo)     
        
        # Create events        
        self.btnQuery.clicked.connect(self.btnQueryPressed)  
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed) 
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed) 
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)   
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)     
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed)
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed)

        # Populate database combobox (internal-specific)        
        self.cbDatabase.addItem('AQUARIUS') 
        self.cbDatabase.addItem('USBR-LCHDB') 
        self.cbDatabase.addItem('USBR-YAOHDB')  
        self.cbDatabase.addItem('USBR-UCHDB2') 

        # Populate interval combobox        
        self.cbInterval.addItem('HOUR')   
        self.cbInterval.addItem('INSTANT')  
        self.cbInterval.addItem('DAY')  

        # Set default query times on DateTimeEdit controls        
        self.dteStartDate.setDateTime(datetime.now() - timedelta(hours = 72) )        
        self.dteEndDate.setDateTime(datetime.now())  

        # Load last quickLook from config
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath())

        if 'Settings' in config and 'lastQuickLook' in config['Settings']:
            lastQuickLook = config['Settings']['lastQuickLook']
            index = self.cbQuickLook.findText(lastQuickLook)
            if index != -1:
                self.cbQuickLook.setCurrentIndex(index)
        else:
            self.cbQuickLook.setCurrentIndex(-1) # Blank default        

        # Disable maximize button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

    def showEvent(self, event):
        if Logic.debug == True: print("[DEBUG] Query window showEvent, window:", self)
        Logic.centerWindowToParent(self)    
        self.cbQuickLook.setCurrentIndex(-1) # Remove this when lastQuickLook starts working
        super().showEvent(event)

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", f"AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", f"Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")

    def btnQueryPressed(self):
        if Logic.debug == True: print("[DEBUG] btnQueryPressed: Starting query process.")
        
        # Get start/end dates
        startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm')
        endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm')
        
        # Collect and parse query items
        queryItems = []

        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if Logic.debug == True: print(f"[DEBUG] Item text: '{itemText}', parts: {parts}, len: {len(parts)}")

            if len(parts) != 3:
                print(f"[WARN] Invalid item skipped: {itemText}")
                continue

            dataID, interval, database = parts
            mrid = '0' # Default
            SDID = dataID

            if database.startswith('USBR-'):
                if '-' in dataID:
                    SDID, mrid = dataID.rsplit('-', 1) # Last - as mrid

            queryItems.append((dataID, interval, database, mrid, i)) # Include orig index
            if Logic.debug == True: print(f"[DEBUG] Added queryItem: {(dataID, interval, database, mrid, i)}")
        
        # Add single query from textSDID if not empty and list blank
        if not queryItems and self.textSDID.toPlainText().strip():
            dataID = self.textSDID.toPlainText().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'  # Default
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)

            queryItems.append((dataID, interval, database, mrid, 0)) # origIndex=0

        elif not queryItems:
            print("[WARN] No valid query items.")
            return
        
        # Filter out USGS-NWIS items (from quickLooks)
        queryItems = [item for item in queryItems if item[2] != 'USGS-NWIS']

        if not queryItems:
            QMessageBox.warning(self, "No Valid Items", "No valid internal query items (USGS skipped).")
            return
        
        # Sort by orig index (though already in order)
        queryItems.sort(key=lambda x: x[4])
        
        # First interval for timestamps
        firstInterval = queryItems[0][1]
        firstDb = queryItems[0][2] # db of first

        if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
            firstInterval = 'HOUR' # Use hourly ts for USBR INSTANT quirk

        timestamps = Logic.buildTimestamps(startDate, endDate, firstInterval)

        if not timestamps:
            QMessageBox.warning(self, "Date Error", "Invalid dates or interval.")
            return
        
        # Default blanks for missing
        defaultBlanks = [''] * len(timestamps)
        
        labelsDict = {} # For Aquarius API label fallback
        
        # Group: dict of (db, mrid or None, interval) -> list of (origIndex, dataID)
        groups = defaultdict(list)

        for dataID, interval, db, mrid, origIndex in queryItems:
            groupKey = (db, mrid if db.startswith('USBR-') else None, interval)
            groups[groupKey].append((origIndex, dataID)) # Append dataID, recalc SDID later
        
        if Logic.debug == True: print(f"[DEBUG] Formed {len(groups)} groups.")
        
        # Collect values: dict {dataID: list of values len(timestamps)}
        valueSDIDct = {}
        
        for (db, mrid, interval), groupItems in groups.items():            
            if Logic.debug == True: print(f"[DEBUG] Processing group: db={db}, mrid={mrid}, interval={interval}, items={len(groupItems)}")
            
            # Recalc SDIDs per item
            SDIDs = []

            for origIndex, dataID in groupItems:
                SDID = dataID

                if db.startswith('USBR-'):
                    if '-' in dataID:
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

            # Map to dataID
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
                    valueSDIDct[dataID] = values
                else:
                    valueSDIDct[dataID] = defaultBlanks # Full blanks
        
        # Recombine in original order
        originalDataIds = [item[0] for item in queryItems] # dataID
        originalIntervals = [item[1] for item in queryItems] # For labels

        # Build lookupIds for dict/QAQC (strip MRID for USBR)
        lookupIds = []

        for item in queryItems:
            dataID, interval, db, mrid, origIndex = item
            lookupId = dataID

            if db.startswith('USBR-') and '-' in dataID:
                lookupId = dataID.split('-')[0]  # Base SDID
            lookupIds.append(lookupId)
        
        # Build data: list of 'ts,value1,value2,...' strings
        data = []

        for r in range(len(timestamps)):
            rowValues = [valueSDIDct.get(dataID, defaultBlanks)[r] for dataID in originalDataIds] # val at r (str)
            data.append(f"{timestamps[r]},{','.join(rowValues)}")
        
        # Build headers: raw dataID for now, processed later
        buildHeader = originalDataIds
        
        # Intervals for labels
        intervalsForHeaders = originalIntervals
        
        # Build table
        winMain.mainTable.clear()
        Logic.buildTable(winMain.mainTable, data, buildHeader, winDataDictionary.mainTable, intervalsForHeaders, lookupIds, labelsDict)
        
        # Show tab if hidden
        if winMain.tabWidget.indexOf(winMain.tabMain) == -1:
            winMain.tabWidget.addTab(winMain.tabMain, 'Data Query')
        
        # Close query window
        winInternalQuery.close()

    def btnAddQueryPressed(self):        
        item = f'{self.textSDID.toPlainText().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}'
        self.listQueryList.addItem(item)
        self.textSDID.clear()
        self.textSDID.setFocus()

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()       
        self.listQueryList.takeItem(self.listQueryList.row(item))

    def btnSaveQuickLookPressed(self):    
        # Set dynamic attrs for save/load
        winQuickLook.currentListQueryList = self.listQueryList 
        winQuickLook.CurrentCbQuickLook = self.cbQuickLook    
        winQuickLook.exec()

        # Re-raise/activate post-model to conuter Plasma focus loss
        self.raise_()
        self.activateWindow    
    
    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)

        # Save last selected quickLook to config
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath())

        if 'Settings' not in config:
            config['Settings'] = {}

        config['Settings']['lastQuickLook'] = self.cbQuickLook.currentText()

        with open(Logic.getConfigPath(), 'w') as configFile:
            config.write(configFile)

    def btnClearQueryPressed(self):
        self.listQueryList.clear()

class uiDataDictionary(QMainWindow):
    """Data dictionary editor: Manages labels for time-series IDs."""
    def __init__(self, parent=None):
        super(uiDataDictionary, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winDataDictionary.ui'), self) # Load the .ui file

        # Define the controls
        self.mainTable = self.findChild(QTableWidget, 'dataDictionaryTable')  
        self.btnSave = self.findChild(QPushButton, 'btnSave') 
        self.btnAddRow = self.findChild(QPushButton, 'btnAddRow') 

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnAddRow.clicked.connect(self.btnAddRowPressed) 

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self):
        data = []    

        # Open the data dictionary file
        f = open(Logic.resourcePath('DataDictionary.csv'), 'r', encoding='utf-8-sig') 
        data.append(f.readlines()[0]) 
    
        # Close the file
        f.close()

        # Check each column and each row in the table. Place data into array
        for r in range(0, self.mainTable.rowCount()):            
            for c in range(0, self.mainTable.columnCount()):            
                if c == 0: data.append(self.mainTable.item(r, c).text())
                else: data[r + 1] = f'{data[r + 1]},{self.mainTable.item(r, c).text()}'

        # Write the data to the file
        f = open(Logic.resourcePath('DataDictionary.csv'), 'w', encoding='utf-8-sig')  
        f.writelines(data)  

        # Close the file
        f.close()

    def btnAddRowPressed(self):
        self.mainTable.setRowCount(self.mainTable.rowCount() + 1)   
        
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
        super(uiOptions, self).__init__(parent) # Call the inherited classes __init__ method
        uic.loadUi(Logic.resourcePath('ui/winOptions.ui'), self) # Load the .ui file

        # Define the controls            
        self.cbUTCOffset = self.findChild(QComboBox,'cbUTCOffset')  
        self.textAQServer = self.findChild(QTextEdit,'textAQServer') 
        self.textAQUser = self.findChild(QTextEdit,'textAQUser') 
        self.qleAQPassword = self.findChild(QLineEdit,'qleAQPassword') 
        self.textUSGSAPIKey = self.findChild(QTextEdit,'textUSGSAPIKey') 
        self.textTNSNames = self.findChild(QTextEdit, 'textTNSNames')
        self.textSQLNetOra = self.findChild(QTextEdit, 'textSQLNetOra')
        self.textOracleWallet = self.findChild(QTextEdit, 'textOracleWallet')
        self.rbBOP = self.findChild(QRadioButton, 'rbBOP')
        self.rbEOP = self.findChild(QRadioButton, 'rbEOP')
        self.btnbOptions = self.findChild(QDialogButtonBox, 'btnbOptions') 
        self.cbRetroFont = self.findChild(QCheckBox, 'cbRetroFont')
        self.cbQAQC = self.findChild(QCheckBox, 'cbQAQC')
        self.cbRawData = self.findChild(QCheckBox, 'cbRawData')
        self.cbDebug = self.findChild(QCheckBox, 'cbDebug')
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget') 
        self.btnShowPassword = self.findChild(QPushButton, 'btnShowPassword')   

        # Add to general tab
        generalTab = self.tabWidget.widget(0)     

        # Set button style
        Logic.buttonStyle(self.btnShowPassword)       

        # Timer for password show (restored to fix error)
        self.lastCharTimer = QTimer(self) # Timer for masking after show
        self.lastCharTimer.timeout.connect(self.maskLastChar)

        # Create events
        self.btnbOptions.accepted.connect(self.onSavePressed)
        self.btnShowPassword.clicked.connect(self.togglePasswordVisibility)

        # Mask password by default
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)  

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

        # Set default for first-time usage (UTC+00:00 in the "middle")
        self.cbUTCOffset.setCurrentIndex(14)

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)
        self.loadSettings()
        self.tabWidget.setCurrentIndex(0) # Default to tabGeneral (index 0)

    def eventFilter(self, obj, event):
        if obj == self.qleAQPassword and event.type() == QEvent.Type.KeyPress:
            # Show last char on key press
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimer.start(500) # 500ms delay then mask
        return super().eventFilter(obj, event)

    def maskLastChar(self):
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)

    def loadSettings(self):
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath()) # Use helper

        # Non-sensitive from config.ini (with defaults if new)
        if 'Settings' in config:
            self.cbUTCOffset.setCurrentText(config['Settings'].get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, \nLisbon, London"))
            retroFont = config['Settings'].getboolean('retroFont', True) # Default checked
            self.cbRetroFont.setChecked(retroFont)
            qaqc = config['Settings'].getboolean('qaqc', True) # Default checked
            self.cbQAQC.setChecked(qaqc)
            rawData = config['Settings'].getboolean('rawData', False) # Default unchecked
            self.cbRawData.setChecked(rawData)
            debugMode = config['Settings'].getboolean('debugMode', False)
            self.cbDebug.setChecked(debugMode)
            tnsPath = config['Settings'].get('tnsNamesLocation', '')
            sqlNetPath = config['Settings'].get('sqlNetOraLocation', '')
            walletPath = config['Settings'].get('oracleWalletLocation', '')

            # Shorten if starts with appRoot
            if tnsPath.startswith(Logic.appRoot):
                tnsPath = tnsPath.replace(Logic.appRoot, '%AppRoot%')
            if sqlNetPath.startswith(Logic.appRoot):
                sqlNetPath = sqlNetPath.replace(Logic.appRoot, '%AppRoot%')
            if walletPath.startswith(Logic.appRoot):
                walletPath = walletPath.replace(Logic.appRoot, '%AppRoot%')

            self.textTNSNames.setPlainText(tnsPath)
            self.textSQLNetOra.setPlainText(sqlNetPath)
            self.textOracleWallet.setPlainText(walletPath)
            hourMethod = config['Settings'].get('hourTimestampMethod', 'EOP')

            if hourMethod == 'EOP':
                self.rbEOP.setChecked(True)
            else:
                self.rbBOP.setChecked(True)  

        # Auto-populate Oracle from env if blank
        if not self.textTNSNames.toPlainText():
            envTns = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin'))

            if envTns.startswith(Logic.appRoot):
                envTns = envTns.replace(Logic.appRoot, '%AppRoot%')
            self.textTNSNames.setPlainText(envTns)
        if not self.textSQLNetOra.toPlainText():
            envSql = os.environ.get('SQLNET_ORA', Logic.resourcePath('oracle/network/admin'))

            if envSql.startswith(Logic.appRoot):
                envSql = envSql.replace(Logic.appRoot, '%AppRoot%')
            self.textSQLNetOra.setPlainText(envSql)
        if not self.textOracleWallet.toPlainText():
            envWallet = os.environ.get('ORACLE_WALLET', Logic.resourcePath('oracle/network/admin/wallet'))

            if envWallet.startswith(Logic.appRoot):
                envWallet = envWallet.replace(Logic.appRoot, '%AppRoot%')
            self.textOracleWallet.setPlainText(envWallet)

        # Sensitive from keyring (defaults to empty)
        self.textAQServer.setPlainText(keyring.get_password("DataDoctor", "aqServer") or "")
        self.textAQUser.setPlainText(keyring.get_password("DataDoctor", "aqUser") or "")
        self.qleAQPassword.setText(keyring.get_password("DataDoctor", "aqPassword") or "") 
        self.textUSGSAPIKey.setPlainText(keyring.get_password("DataDoctor", "usgsApiKey") or "")

    def onSavePressed(self):
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath()) # Read existing to preserve keys

        # Read previous retro before update
        previousRetro = config['Settings'].getboolean('retroFont', True) if 'Settings' in config else True

        tnsPath = self.textTNSNames.toPlainText()
        sqlNetPath = self.textSQLNetOra.toPlainText()
        walletPath = self.textOracleWallet.toPlainText()

        # Expand %AppRoot% to full if present
        if '%AppRoot%' in tnsPath:
            tnsPath = tnsPath.replace('%AppRoot%', Logic.appRoot)
        if '%AppRoot%' in sqlNetPath:
            sqlNetPath = sqlNetPath.replace('%AppRoot%', Logic.appRoot)
        if '%AppRoot%' in walletPath:
            walletPath = walletPath.replace('%AppRoot%', Logic.appRoot)

        # Update only options keys (preserve others)
        if 'Settings' not in config:
            config['Settings'] = {}

        config['Settings']['utcOffset'] = self.cbUTCOffset.currentText()
        config['Settings']['retroFont'] = 'True' if self.cbRetroFont.isChecked() else 'False'
        config['Settings']['qaqc'] = 'True' if self.cbQAQC.isChecked() else 'False'
        config['Settings']['rawData'] = 'True' if self.cbRawData.isChecked() else 'False'
        config['Settings']['debugMode'] = 'True' if self.cbDebug.isChecked() else 'False'
        config['Settings']['tnsNamesLocation'] = tnsPath
        config['Settings']['sqlNetOraLocation'] = sqlNetPath
        config['Settings']['oracleWalletLocation'] = walletPath
        config['Settings']['hourTimestampMethod'] = 'EOP' if self.rbEOP.isChecked() else 'BOP'

        with open(Logic.getConfigPath(), 'w') as configFile:
            config.write(configFile)

        # Reload and set globals after save
        Logic.reloadGlobals()

        # Apply retro font if checked
        if self.cbRetroFont.isChecked():
            fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
            fontId = QFontDatabase.addApplicationFont(fontPath)

            if fontId != -1:
                fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
                retroFontObj = QFont(fontFamily, 10)  # Fixed size
                retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias) # Disable anti-aliasing
                app.setFont(retroFontObj)
                
                # Re-apply to all open windows
                for window in [winMain, winWebQuery, winDataDictionary, winQuickLook, winOptions, winAbout]:
                    Logic.applyRetroFont(window)
        else:
            app.setFont(QFont()) # System default

        # Show restart message if retro font changed (in either direction)
        newRetro = self.cbRetroFont.isChecked()
        if newRetro != previousRetro:
            reply = QMessageBox.question(self, "Font Change", "Restart DataDoctor for the font change to take effect?\nOK to restart now, Cancel to revert to previous setting.", QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Ok:
                # Auto-restart app (cross-platform)
                python = sys.executable
                os.execl(python, python, *sys.argv) # Relaunch with same args
            else:
                # Revert checkbox and config
                self.cbRetroFont.setChecked(previousRetro)
                config = configparser.ConfigParser()
                config.read(Logic.getConfigPath())
                config['Settings']['retroFont'] = 'True' if previousRetro else 'False'

                with open(Logic.getConfigPath(), 'w') as configFile:
                    config.write(configFile)

                # Re-apply previous font setting
                Logic.reloadGlobals() # Reload to apply revert immediately

        # Sensitive to keyring
        keyring.set_password("DataDoctor", "aqServer", self.textAQServer.toPlainText())
        keyring.set_password("DataDoctor", "aqUser", self.textAQUser.toPlainText())
        keyring.set_password("DataDoctor", "aqPassword", self.qleAQPassword.text())
        keyring.set_password("DataDoctor", "usgsApiKey", self.textUSGSAPIKey.toPlainText())

    def togglePasswordVisibility(self):
        if self.qleAQPassword.echoMode() == QLineEdit.EchoMode.Password:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)         
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png'))) 
        else:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)         
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

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