import sys
import QueryUSBR
import QueryUSGS
import QueryAquarius
import Logic
import datetime
import breeze_resources # Registers Qt resources for stylesheets
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtCore import QIODevice, QFile, QTextStream, QEvent, QObject
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QVBoxLayout,
                             QTextEdit, QComboBox, QDateTimeEdit, QListWidget, QWidget, QGridLayout,
                             QListWidgetItem, QMessageBox, QDialog, QSizePolicy, QTabWidget, QRadioButton,
                             QDialogButtonBox)
from datetime import datetime, timedelta
from PyQt6 import uic
from collections import defaultdict

class uiMain(QMainWindow):
    """Main window for DataDoctor: Handles core UI, queries, and exports."""
    def __init__(self):
        super(uiMain, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi(Logic.resourcePath('ui/winMain.ui'), self) # Load the .ui file
        
        # Define the controls
        self.btnPublicQuery = self.findChild(QPushButton, 'btnPublicQuery')
        self.mainTable = self.findChild(QTableWidget, 'mainTable')          
        self.btnDataDictionary = self.findChild(QPushButton,'btnDataDictionary')  
        self.btnDarkMode = self.findChild(QPushButton,'btnDarkMode')  
        self.btnExportCSV = self.findChild(QPushButton, 'btnExportCSV')       
        self.btnOptions = self.findChild(QPushButton, 'btnOptions')   
        self.btnInfo = self.findChild(QPushButton, 'btnInfo')    
        self.btnInternalQuery = self.findChild(QPushButton, 'btnInternalQuery')

        # Set button style
        Logic.buttonStyle(self.btnPublicQuery)
        Logic.buttonStyle(self.btnDataDictionary)
        Logic.buttonStyle(self.btnDarkMode)  
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
        self.btnDarkMode.clicked.connect(self.toggleDarkMode)    
        self.btnExportCSV.clicked.connect(self.btnExportCSVPressed) 
        self.btnOptions.clicked.connect(self.btnOptionsPressed) 
        self.btnInfo.clicked.connect(self.btnInfoPressed) 

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

    def btnOptionsPressed(self): 
        winOptions.exec()  

    def btnInfoPressed(self): 
        print('Not complete yet')

    def toggleDarkMode(self):
        try:
            with open(Logic.resourcePath('config.ini'), 'r', encoding='utf-8-sig') as f:
                data = f.readlines()
                colorMode = data[0].strip()
        except FileNotFoundError:
            colorMode = 'light' # Default if no config
            data = [colorMode + '\n']

        # Toggle
        colorMode = 'dark' if colorMode == 'light' else 'light'

        # Load and apply stylesheet (resource first, then fallback to file)
        stylesheetPath = f":/{colorMode}/stylesheet.qss"
        f = QFile(stylesheetPath)

        if not f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
            # Fallback to filesystem
            stylesheetPath = Logic.resourcePath(f"{colorMode}/stylesheet.qss")
            f = QFile(stylesheetPath)

            if not f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
                QMessageBox.warning(self, "Style Error", f"Could not load {colorMode} stylesheet from {stylesheetPath}.\nError: {f.errorString()}")
                f.close()
                return
        stream = QTextStream(f)
        app.setStyleSheet(stream.readAll())
        f.close()

        # Save
        data[0] = colorMode + '\n'
        with open(Logic.resourcePath('config.ini'), 'w', encoding='utf-8-sig') as f:
            f.writelines(data)

    def showDataDictionary(self):         
        winDataDictionary.show()    

    def btnExportCSVPressed(self):
        Logic.exportTableToCSV(self.mainTable, '', '') # Pass empty (uses dialog)

    def exitPressed(self):
        app.exit()    

class uiWebQuery(QMainWindow):
    """Query window: Builds and executes USBR/USGS API calls."""
    def __init__(self, parent=None):
        super(uiWebQuery, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winWebQuery.ui'), self) # Load the .ui file

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

        # Populate database combobox        
        self.cbDatabase.addItem('AQUARIUS') 
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

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
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
            sdi = dataID

            if database.startswith('USBR-') and '-' in dataID:
                sdi, mrid = dataID.rsplit('-', 1)

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
                    result = QueryUSBR.api(svr, SDIDs, startDate, endDate, interval, mrid)
                elif db == 'USGS-NWIS':
                    result = QueryUSGS.api(SDIDs, interval, startDate, endDate)
                elif db == 'Aquarius':
                    result = QueryAquarius.api(SDIDs, startDate, endDate, interval)
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
        winQuickLook.exec()  
    
    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)

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

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnCancel.clicked.connect(self.btnCancelPressed)  

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self): 
        # Save quick look
        Logic.saveQuickLook(self.textQuickLookName, winWebQuery.listQueryList)

        # Clear the controls
        self.clear()

        # Load quick looks
        Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)

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
        super(uiOptions, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resourcePath('ui/winOptions.ui'), self) # Load the .ui file

        # Attach controls             
        self.textUTCOffset = self.findChild(QTextEdit,'textUTCOffset')  
        self.textAQServer = self.findChild(QTextEdit,'textAQServer') 
        self.textAQUser = self.findChild(QTextEdit,'textAQUser') 
        self.textAQPassword = self.findChild(QTextEdit,'textAQPassword') 
        self.textUSGSAPIKey = self.findChild(QTextEdit,'textUSGSAPIKey') 
        self.textTNSNames = self.findChild(QTextEdit, 'textTNSNames')
        self.textSQLNetOra = self.findChild(QTextEdit, 'textSQLNetOra')
        self.textOracleWallet = self.findChild(QTextEdit, 'textSQLNetora')
        self.rbBOP = self.findChild(QRadioButton, 'rbBOP')
        self.rbEOP = self.findChild(QRadioButton, 'rbEOP')
        self.qbtnbOptions = self.findChild(QDialogButtonBox, 'qbtnbOptions') 
        self.rbTRUE = self.findChild(QRadioButton, 'rbTRUE')
        self.rbFALSE = self.findChild(QRadioButton, 'rbFALSE')       

        # Create events
        self.qbtnbOptions.accepted.connect(self.onSavePressed)

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        super().showEvent(event)

    def onSavePressed(self):
        # Placeholder for save logic (e.g., store text fields to config)
        pass  # We'll expand this later

# Create an instance of QApplication     
app = QApplication(sys.argv) 

# Create an instance of our class
winMain = uiMain() 
winWebQuery = uiWebQuery(winMain) # Pass parent
winDataDictionary = uiDataDictionary(winMain) # Pass parent
winQuickLook = uiQuickLook(winMain) # Pass parent
winOptions = uiOptions(winMain) # Pass Parent

# Load in configuration files
try:
    config = Logic.loadConfig()
except (FileNotFoundError, ValueError) as e:
    print(f"Config load failed: {e}. Defaulting to light mode.")
    config = ['light'] # Fallback list

if config[0].strip() == 'dark': winMain.btnDarkMode.setChecked(True)       
  
# Set stylesheet
colorMode = config[0].strip() # Strip any whitespace
stylesheetLoaded = False

# Try resource path first
stylesheetPath = f":/{colorMode}/stylesheet.qss"
f = QFile(stylesheetPath)

if f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
    stream = QTextStream(f)
    app.setStyleSheet(stream.readAll())
    f.close()
    stylesheetLoaded = True

# Fallback to filesystem if resource failed
if not stylesheetLoaded:
    stylesheetPath = Logic.resourcePath(f"{colorMode}/stylesheet.qss")
    f = QFile(stylesheetPath)

    if f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        stream = QTextStream(f)
        app.setStyleSheet(stream.readAll())
        f.close()
        stylesheetLoaded = True
    else:
        print(f"Initial {colorMode} stylesheet load failed (both paths): {f.errorString()}")
        f.close() # App continues with default Qt style—no crash        

if not stylesheetLoaded:
    print(f"Warning: No stylesheet applied for {colorMode}. Check file paths.")

# Load in data dictionary
Logic.buildDataDictionary(winDataDictionary.mainTable) 

# Load quick looks
Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)

# Start the application
app.exec() 