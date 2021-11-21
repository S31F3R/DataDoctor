import urllib.request
import json
import sys
import QueryUSBR
import QueryUSGS
import Logic
import datetime
import breeze_resources
from PyQt5 import QtWidgets, uic
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from datetime import datetime, timedelta

class uiMain(QtWidgets.QMainWindow):
    def __init__(self):
        super(uiMain, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi('./winMain.ui', self) # Load the .ui file

        # Attach controls
        self.btnQuery = self.findChild(QtWidgets.QPushButton, 'btnQuery')
        self.table = self.findChild(QtWidgets.QTableWidget, 'mainTable')  
        self.menuDataDictionary = self.findChild(QtWidgets.QAction,'actionDataDictionary')  
        self.menuDarkMode = self.findChild(QtWidgets.QAction,'actionDarkMode')
        self.menuExit = self.findChild(QtWidgets.QAction,'actionExit')  
        
        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed)  
        self.menuDataDictionary.triggered.connect(self.showDataDictionary)     
        self.menuDarkMode.triggered.connect(self.toggleDarkMode)  
        self.menuExit.triggered.connect(self.exitPressed) 
        
        # Show the GUI on application start
        self.show()   

    def btnQueryPressed(self): 
        winQuery.show()  

    def toggleDarkMode(self):   
        # Open config and get color mode  
        f = open(f'./config.ini', 'r', encoding='utf-8-sig') 
        data = f.readlines()
        colorMode = str(data[0])  

        # Check to see if dark mode was turned on or off
        if colorMode == 'light': colorMode = 'dark'  
        else: colorMode = 'light'     

        # Set stylesheet
        file = QFile(f":/{colorMode}/stylesheet.qss")
        file.open(QFile.ReadOnly | QFile.Text)
        stream = QTextStream(file)
        app.setStyleSheet(stream.readAll())   

        # Save color mode to config
        f = open(f'./config.ini', 'w', encoding='utf-8-sig')  
        data[0] = colorMode
        f.writelines(data)     

    def showDataDictionary(self):         
        winDataDictionary.show()     

    def exitPressed(self):
        app.exit()    

class uiQuery(QtWidgets.QMainWindow):
    def __init__(self):
        super(uiQuery, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi('./winQuery.ui', self) # Load the .ui file

        # Define the controls
        self.btnQuery = self.findChild(QtWidgets.QPushButton, 'btnQuery')    
        self.textSDID = self.findChild(QtWidgets.QTextEdit,'textSDID')    
        self.cbDatabase = self.findChild(QtWidgets.QComboBox,'cbDatabase')  
        self.cbInterval = self.findChild(QtWidgets.QComboBox,'cbInterval')
        self.dteStartDate = self.findChild(QtWidgets.QDateTimeEdit, 'dteStartDate')
        self.dteEndDate = self.findChild(QtWidgets.QDateTimeEdit, 'dteEndDate')
        self.listQueryList = self.findChild(QtWidgets.QListWidget, 'listQueryList') 
        self.btnAddQuery = self.findChild(QtWidgets.QPushButton,'btnAddQuery')
        self.btnRemoveQuery = self.findChild(QtWidgets.QPushButton,'btnRemoveQuery')
        self.btnSaveQuickLook = self.findChild(QtWidgets.QPushButton,'btnSaveQuickLook')
        self.cbQuickLook = self.findChild(QtWidgets.QComboBox,'cbQuickLook')
        self.btnLoadQuickLook = self.findChild(QtWidgets.QPushButton, 'btnLoadQuickLook') 

        # Create events        
        self.btnQuery.clicked.connect(self.btnQueryPressed)  
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed) 
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed) 
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)   
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)     

        # Populate database combobox        
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

    def btnQueryPressed(self):   
        if self.listQueryList.count() == 0: dataID = self.textSDID.toPlainText()
        else:         
            for x in range(self.listQueryList.count()):
                if x == 0: dataID = self.listQueryList.item(x).text()
                else: dataID = f'{dataID},{self.listQueryList.item(x).text()}' 

        # USBR public API query
        if self.cbDatabase.currentText().split('-')[0] == 'USBR': data = QueryUSBR.API(self.cbDatabase, dataID, self.dteStartDate, self.dteEndDate, self.cbInterval)            

        # USGS nwis query
        if self.cbDatabase.currentText().split('-')[0] == 'USGS': data = QueryUSGS.API(dataID, self.cbInterval, self.dteStartDate, self.dteEndDate)                                 
                      
        buildHeader = data[0]        
        dataID = data[0]     
        data.pop(0)

        # Build the table
        Logic.buildTable(winMain.table, data, buildHeader, winDataDictionary.table)

        # QAQC the data
        Logic.QAQC(winMain.table, winDataDictionary.table, dataID)

        # Hide the window
        winQuery.hide() 

    def btnAddQueryPressed(self):
        item = QListWidgetItem(self.textSDID.toPlainText())
        self.listQueryList.addItem(item)
        self.textSDID.clear()
        self.textSDID.setFocus()

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()       
        self.listQueryList.takeItem(self.listQueryList.row(item))

    def btnSaveQuickLookPressed(self):         
        winQuickLook.show()  
    
    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)

class uiDataDictionary(QtWidgets.QMainWindow):
    def __init__(self):
        super(uiDataDictionary, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi('./winDataDictionary.ui', self) # Load the .ui file

        # Attach controls
        self.table = self.findChild(QtWidgets.QTableWidget, 'dataDictionaryTable')  
        self.btnSave = self.findChild(QtWidgets.QPushButton, 'btnSave') 
        self.btnAddRow = self.findChild(QtWidgets.QPushButton, 'btnAddRow') 

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnAddRow.clicked.connect(self.btnAddRowPressed) 

    def btnSavePressed(self):
        data = []    

        # Open the data dictionary file
        f = open(f'./DataDictionary.csv', 'r', encoding='utf-8-sig') 
        data.append(f.readlines()[0]) 
    
        # Close the file
        f.close()

        # Check each column and each row in the table. Place data into array
        for r in range(0, self.table.rowCount()):            
            for c in range(0, self.table.columnCount()):            
                if c == 0: data.append(self.table.item(r, c).text())
                else: data[r + 1] = f'{data[r + 1]},{self.table.item(r, c).text()}'

        # Write the data to the file
        f = open(f'./DataDictionary.csv', 'w', encoding='utf-8-sig')  
        f.writelines(data)  

        # Close the file
        f.close()

    def btnAddRowPressed(self):
        self.table.setRowCount(self.table.rowCount() + 1)   
        
class uiQuickLook(QtWidgets.QDialog):
    def __init__(self):
        super(uiQuickLook, self).__init__() # Call the inherited classes __init__ method
        uic.loadUi('./winQuickLook.ui', self) # Load the .ui file

        # Attach controls
        self.btnSave = self.findChild(QtWidgets.QPushButton, 'btnSave')   
        self.btnCancel = self.findChild(QtWidgets.QPushButton, 'btnCancel')  
        self.textQuickLookName = self.findChild(QtWidgets.QTextEdit,'textQuickLookName')  

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)  
        self.btnCancel.clicked.connect(self.btnCancelPressed)  

    def btnSavePressed(self): 
        # Save quick look
        Logic.saveQuickLook(self.textQuickLookName, winQuery.listQueryList)

        # Clear the controls
        self.clear()

        Logic.loadAllQuickLooks(winQuery.cbQuickLook)

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

# Create an instance of QtWidgets.QApplication     
app = QtWidgets.QApplication([sys.argv]) 

# Create an instance of our class
winMain = uiMain() 
winQuery = uiQuery()
winDataDictionary = uiDataDictionary()
winQuickLook = uiQuickLook()

# Load in configuration files
config = Logic.loadConfig()

if config[0] == 'dark': winMain.menuDarkMode.setChecked(True)         
  
# Set stylesheet
file = QFile(f":/{config[0]}/stylesheet.qss")
file.open(QFile.ReadOnly | QFile.Text)
stream = QTextStream(file)
app.setStyleSheet(stream.readAll())

# Load in data dictionary
Logic.buildDataDictionary(winDataDictionary.table) 

# Load quick looks
Logic.loadAllQuickLooks(winQuery.cbQuickLook)

# Start the application
app.exec() 