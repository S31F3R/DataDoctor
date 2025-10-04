import sys
import QueryUSBR
import QueryUSGS
import Logic
import datetime
import breeze_resources # Registers Qt resources for stylesheets
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtCore import QIODevice, QFile, QTextStream
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, 
                             QTextEdit, QComboBox, QDateTimeEdit, QListWidget, 
                             QListWidgetItem, QMessageBox, QDialog)
from datetime import datetime, timedelta
from PyQt6 import uic

class uiMain(QMainWindow):
    """Main window for DataDoctor: Handles core UI, queries, and exports."""
    def __init__(self):
        super(uiMain, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi(Logic.resource_path('ui/winMain.ui'), self) # Load the .ui file
        
        # Attach controls
        self.btnQuery = self.findChild(QPushButton, 'btnQuery')
        self.table = self.findChild(QTableWidget, 'mainTable')  
        self.btnDataDictionary = self.findChild(QPushButton,'btnDataDictionary')  
        self.btnDarkMode = self.findChild(QPushButton,'btnDarkMode')  
        self.btnExportCSV = self.findChild(QPushButton, 'btnExportCSV')        
        
        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed)  
        self.btnDataDictionary.clicked.connect(self.showDataDictionary)  
        self.btnDarkMode.clicked.connect(self.toggleDarkMode)    
        self.btnExportCSV.clicked.connect(self.btnExportCSVPressed) 

        # Center window when opened
        rect = self.frameGeometry()
        centerPoint = QGuiApplication.primaryScreen().availableGeometry().center()
        rect.moveCenter(centerPoint)
        self.move(rect.topLeft())
        
        # Show the GUI on application start
        self.show()   

    def btnQueryPressed(self): 
        winWebQuery.show()  

    def toggleDarkMode(self):
        try:
            with open(Logic.resource_path('config.ini'), 'r', encoding='utf-8-sig') as f:
                data = f.readlines()
                colorMode = data[0].strip()
        except FileNotFoundError:
            colorMode = 'light'  # Default if no config
            data = [colorMode + '\n']

        # Toggle
        colorMode = 'dark' if colorMode == 'light' else 'light'

        # Load and apply stylesheet (resource first, then fallback to file)
        stylesheet_path = f":/{colorMode}/stylesheet.qss"
        f = QFile(stylesheet_path)
        if not f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
            # Fallback to filesystem
            stylesheet_path = Logic.resource_path(f"{colorMode}/stylesheet.qss")
            f = QFile(stylesheet_path)
            if not f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
                QMessageBox.warning(self, "Style Error", f"Could not load {colorMode} stylesheet from {stylesheet_path}.\nError: {f.errorString()}")
                f.close()
                return
        stream = QTextStream(f)
        app.setStyleSheet(stream.readAll())
        f.close()

        # Save
        data[0] = colorMode + '\n'
        with open(Logic.resource_path('config.ini'), 'w', encoding='utf-8-sig') as f:
            f.writelines(data)

    def showDataDictionary(self):         
        winDataDictionary.show()    

    def btnExportCSVPressed(self):
        Logic.exportTableToCSV(self.table, '', '')  # Pass empty (uses dialog)

    def exitPressed(self):
        app.exit()    

class uiWebQuery(QMainWindow):
    """Query window: Builds and executes USBR/USGS API calls."""
    def __init__(self, parent=None):
        super(uiWebQuery, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resource_path('ui/winWebQuery.ui'), self) # Load the .ui file

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

        # Create events        
        self.btnQuery.clicked.connect(self.btnQueryPressed)  
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed) 
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed) 
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)   
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)     
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)

        # Populate database combobox        
        self.cbDatabase.addItem('USBR-LCHDB')   
        self.cbDatabase.addItem('USBR-AQUARIUS') 
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

        # Center window relative to parent (main window)
        if self.parent():  # Fallback if no parent
            parent_center = self.parent().frameGeometry().center()
        else:
            parent_center = QGuiApplication.primaryScreen().availableGeometry().center()
        rect = self.frameGeometry()
        rect.moveCenter(parent_center)
        self.move(rect.topLeft())

    def btnQueryPressed(self):   
        # Build dataID: List first (comma-joined), fallback to single text if empty
        if self.listQueryList.count() == 0:
            dataID = self.textSDID.toPlainText().strip()  # Trim whitespace
        else:         
            for x in range(self.listQueryList.count()):
                if x == 0: 
                    dataID = self.listQueryList.item(x).text()
                else: 
                    dataID = f'{dataID},{self.listQueryList.item(x).text()}'

        # Validate dataID before API
        if not dataID:
            QMessageBox.warning(self, "Empty Query", "Enter an SDID or add to list.")
            return

        # USBR or USGS API query (separate ifs, as original)
        data = None

        try:
            if self.cbDatabase.currentText().split('-')[0] == 'USBR': 
                data = QueryUSBR.api(self.cbDatabase, dataID, self.dteStartDate, self.dteEndDate, self.cbInterval)
            if self.cbDatabase.currentText().split('-')[0] == 'USGS': 
                data = QueryUSGS.api(dataID, self.cbInterval, self.dteStartDate, self.dteEndDate)
        except Exception as e:  # Catches API errors (e.g., invalid ID, no net)
            QMessageBox.warning(self, "Query Error", f"API fetch failed:\n{e}\nCheck SDID, dates, or connection.")
            return

        # Check for empty results post-API
        if not data or len(data) < 1:
            QMessageBox.warning(self, "No Data", f"Query for '{dataID}' returned nothing.\nTry different dates/IDs.")
            return
                        
        buildHeader = data[0]        
        dataID = data[0]  # Reuse as universal tag for QAQC (your intent)
        data.pop(0)

        # USBR API fix: Pop extra item if not AQUARIUS or USGS
        if self.cbDatabase.currentText() != 'USBR-AQUARIUS' or self.cbDatabase.currentText().split('-')[0] == 'USGS': 
            data.pop(len(data) - 1)

        # Build the table
        Logic.buildTable(winMain.table, data, buildHeader, winDataDictionary.table)

        # QAQC the data
        Logic.qaqc(winMain.table, winDataDictionary.table, dataID) 

        # Hide the window
        winWebQuery.hide() 

    def btnAddQueryPressed(self):
        item = QListWidgetItem(self.textSDID.toPlainText())
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
        uic.loadUi(Logic.resource_path('ui/winDataDictionary.ui'), self) # Load the .ui file

        # Attach controls
        self.table = self.findChild(QTableWidget, 'dataDictionaryTable')  
        self.btnSave = self.findChild(QPushButton, 'btnSave') 
        self.btnAddRow = self.findChild(QPushButton, 'btnAddRow') 

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnAddRow.clicked.connect(self.btnAddRowPressed) 

        # Center window relative to parent (main window)
        if self.parent():  # Fallback if no parent
            parent_center = self.parent().frameGeometry().center()
        else:
            parent_center = QGuiApplication.primaryScreen().availableGeometry().center()
        rect = self.frameGeometry()
        rect.moveCenter(parent_center)
        self.move(rect.topLeft())

    def btnSavePressed(self):
        data = []    

        # Open the data dictionary file
        f = open(Logic.resource_path('DataDictionary.csv'), 'r', encoding='utf-8-sig') 
        data.append(f.readlines()[0]) 
    
        # Close the file
        f.close()

        # Check each column and each row in the table. Place data into array
        for r in range(0, self.table.rowCount()):            
            for c in range(0, self.table.columnCount()):            
                if c == 0: data.append(self.table.item(r, c).text())
                else: data[r + 1] = f'{data[r + 1]},{self.table.item(r, c).text()}'

        # Write the data to the file
        f = open(Logic.resource_path('DataDictionary.csv'), 'w', encoding='utf-8-sig')  
        f.writelines(data)  

        # Close the file
        f.close()

    def btnAddRowPressed(self):
        self.table.setRowCount(self.table.rowCount() + 1)   
        
class uiQuickLook(QDialog):
    """Quick look save dialog: Names and stores query presets."""
    def __init__(self, parent=None):
        super(uiQuickLook, self).__init__(parent) # Pass parent superclass
        uic.loadUi(Logic.resource_path('ui/winQuickLook.ui'), self) # Load the .ui file

        # Attach controls
        self.btnSave = self.findChild(QPushButton, 'btnSave')   
        self.btnCancel = self.findChild(QPushButton, 'btnCancel')  
        self.textQuickLookName = self.findChild(QTextEdit,'textQuickLookName')  

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnCancel.clicked.connect(self.btnCancelPressed)  

        # Center window relative to parent (main window)
        if self.parent():  # Fallback if no parent
            parent_center = self.parent().frameGeometry().center()
        else:
            parent_center = QGuiApplication.primaryScreen().availableGeometry().center()
        rect = self.frameGeometry()
        rect.moveCenter(parent_center)
        self.move(rect.topLeft())

    def btnSavePressed(self): 
        # Save quick look
        Logic.saveQuickLook(self.textQuickLookName, winWebQuery.listQueryList)

        # Clear the controls
        self.clear()

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

# Create an instance of QApplication     
app = QApplication(sys.argv) 

# Create an instance of our class
winMain = uiMain() 
winWebQuery = uiWebQuery(winMain) # Pass parent
winDataDictionary = uiDataDictionary(winMain) # Pass parent
winQuickLook = uiQuickLook(winMain) # Pass parent

# Load in configuration files
try:
    config = Logic.loadConfig()
except (FileNotFoundError, ValueError) as e:
    print(f"Config load failed: {e}. Defaulting to light mode.")
    config = ['light']  # Fallback list

if config[0].strip() == 'dark': winMain.btnDarkMode.setChecked(True)       
  
# Set stylesheet
colorMode = config[0].strip()  # Strip any whitespace
stylesheet_loaded = False

# Try resource path first
stylesheet_path = f":/{colorMode}/stylesheet.qss"
f = QFile(stylesheet_path)
if f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
    stream = QTextStream(f)
    app.setStyleSheet(stream.readAll())
    f.close()
    stylesheet_loaded = True

# Fallback to filesystem if resource failed
if not stylesheet_loaded:
    stylesheet_path = Logic.resource_path(f"{colorMode}/stylesheet.qss")
    f = QFile(stylesheet_path)
    if f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        stream = QTextStream(f)
        app.setStyleSheet(stream.readAll())
        f.close()
        stylesheet_loaded = True
    else:
        print(f"Initial {colorMode} stylesheet load failed (both paths): {f.errorString()}")
        f.close()
        # App continues with default Qt style—no crash

if not stylesheet_loaded:
    print(f"Warning: No stylesheet applied for {colorMode}. Check file paths.")

# Load in data dictionary
Logic.buildDataDictionary(winDataDictionary.table) 

# Load quick looks
Logic.loadAllQuickLooks(winWebQuery.cbQuickLook)

# Start the application
app.exec() 