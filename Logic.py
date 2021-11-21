import os
import datetime
from PyQt5 import QtWidgets, QtGui
from PyQt5 import QtCore

def buildTable(table, data, buildHeader, dataDictionaryTable):
    # Make sure the table is clear before adding items to it
    table.clear()    

    # Create headers for table
    for h in range(0, len(buildHeader)): 
        if dataDictionaryTable != None:
            # Find the data ID in the dictionary and return the row number
            dataDictionaryItem = getDataDictionaryItem(dataDictionaryTable, buildHeader[h])
     
            # If data ID wasn't found in data dictionary, it will return a null. Change null to a -9999 for next logic check
            if dataDictionaryItem == 'null': dataDictionaryItem = -9999   
            
            # If data ID is found, change the label to match what is in the dictionary
            else: 
                parseHeader = dataDictionaryTable.item(dataDictionaryItem, 2).text().split(':')
                parseHeader[1] = parseHeader[1][1:]
                buildHeader[h] = f'{parseHeader[0]} \n{parseHeader[1]} \n{buildHeader[h]}'

        # Data dictionary doesn't need a date column so create headers normally for other tables
        if dataDictionaryTable != None:
            if h == 0: header = f'Date,{buildHeader[h]}' 
            else: header = f'{header},{buildHeader[h]}' 
        else:
            if h == 0: header = buildHeader[h]
            else: header = f'{header},{buildHeader[h]}' 

        # Set table properties
        table.setRowCount(len(data) - 1)                
        table.setColumnCount(len(data[0].split(',')))                       
        table.setHorizontalHeaderLabels(header.split(','))  
        
        for d in range(0, len(data) - 1):       
            for c in range(0, len(data[d].split(','))):
                table.setItem(d, c, QtWidgets.QTableWidgetItem(data[d].split(',')[c])) 
                
        # Resize columns to fit the data
        for s in range(0, len(data[0].split(','))): 
            table.resizeColumnToContents(s)  

def buildDataDictionary(table):
    data = []      

    # Open the file     
    f = open('./DataDictionary.csv', 'r', encoding='utf-8-sig')  

    # Read all lines in the file         
    readfile = f.readlines()

    # Close the file
    f.close()

    # Set the headers
    header = readfile[0].split(',')        

    # Parse the data into an array
    for d in range(1, len(readfile)):
        data.append(readfile[d])

    # Build the table
    buildTable(table, data, header, None)

def buildDTEDateTime(dateTime):
    # Parse out date/time   
    dateTime = str(dateTime.dateTime()).replace("'",'')
    dateTime = dateTime.replace(' ','')
    year = dateTime.split(',')[0].split('(')[1]
    month = dateTime.split(',')[1]
    day = dateTime.split(',')[2]
    hour = dateTime.split(',')[3]
    if len(hour) == 1: hour = f'0{hour}'
    minute = dateTime.split(',')[4]   
    if len(minute) == 1: minute = f'0{minute}'

    output = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute))   

    return output

def getDataDictionaryItem(table, dataID):
    output = 'null'    

    # Check every row in the dictionary for data ID
    for r in range(0, table.rowCount()):
        if table.item(r, 0).text() == dataID: output = r

    return output

def QAQC(mainTable, dataDictionaryTable, dataID): 
    for c in range(1, mainTable.columnCount()):  
        # Find the data ID in the dictionary and return the row number
        parseID = str(dataID[c - 1]).split('\n')
        parseID = parseID[len(parseID) - 1]
        dataDictionaryItem = getDataDictionaryItem(dataDictionaryTable, parseID)
 
        # If data ID wasn't found in data dictionary, it will return a null. Change null to a -9999 for next logic check
        if dataDictionaryItem == 'null': dataDictionaryItem = -9999       

        if float(dataDictionaryItem) > -9999: 
            for d in range(0, mainTable.rowCount()):   
                # Add item to variable for formatting             
                item = QtWidgets.QTableWidgetItem(mainTable.item(d, c).text()) 

                # Check to see if data is missing           
                if mainTable.item(d, c).text() == '': item.setBackground(QtGui.QColor(100, 195, 247))
                else:              
                    try:
                        # Check for over cutoff max                   
                        if float(mainTable.item(d, c).text()) > float(dataDictionaryTable.item(dataDictionaryItem, 6).text()): item.setBackground(QtGui.QColor(192, 28, 40))   

                        # Check for under cutoff min
                        if float(mainTable.item(d, c).text()) < float(dataDictionaryTable.item(dataDictionaryItem, 5).text()): item.setBackground(QtGui.QColor(255, 163, 72))   

                        # Check for over expected max                   
                        if float(mainTable.item(d, c).text()) > float(dataDictionaryTable.item(dataDictionaryItem, 4).text()): item.setBackground(QtGui.QColor(245, 194, 17))   

                        # Check for under expected min
                        if float(mainTable.item(d, c).text()) < float(dataDictionaryTable.item(dataDictionaryItem, 3).text()): item.setBackground(QtGui.QColor(249, 240, 107))  

                        # Check for rate of change
                        if d > 0:
                            if mainTable.item(d - 1, c).text() != '':
                                if (float(mainTable.item(d, c).text()) - float(mainTable.item(d - 1, c).text())) > float(dataDictionaryTable.item(dataDictionaryItem, 7).text()): item.setBackground(QtGui.QColor(246, 97, 81)) 
                    except: None

                    # Check for repeating values
                    if d > 0:
                        if mainTable.item(d - 1, c).text() != '':
                            if float(mainTable.item(d, c).text()) == float(mainTable.item(d - 1, c).text()): item.setBackground(QtGui.QColor(87, 227, 137))            

                # Add data to the table
                mainTable.setItem(d, c, item)  

def loadAllQuickLooks(cbQuickLook):     
    # Clear the combobox first
    cbQuickLook.clear()

    # First item should always be a blank
    cbQuickLook.addItem(None)

    # Open the file  
    for file in os.listdir('./QuickLook'):
        # Open the file
        f = open(f'./QuickLook/{file}', 'r', encoding='utf-8-sig')  

        # Read all lines in the file         
        readfile = f.readlines()  

        # Close the file   

        # Add all lines as combobox items     
        cbQuickLook.addItem(str(file).split('.txt')[0]) 
                  
def saveQuickLook(textQuickLookName, listQueryList):
    # Create a file or open if it deson't exist
    f = open(f'./QuickLook/{textQuickLookName.toPlainText()}.txt', 'w', encoding='utf-8-sig')    
    
    for x in range(listQueryList.count()):
        if x == 0: data = (listQueryList.item(x).text())
        else: data = f'{data},{listQueryList.item(x).text()}'       
    
    # Write data to file
    f.write(data)  

    # Close the file
    f.close()

def loadQuickLook(cbQuickLook, listQueryList):     
    # Clear the list first
    listQueryList.clear()

    # Open the file  
    f = open(f'./QuickLook/{cbQuickLook.currentText()}.txt', 'r', encoding='utf-8-sig')           
    readfile = f.readlines()  

    # Close the file
    f.close()  
    
    # Parse the data    
    data = str(readfile).split(',')
    data[0] = data[0].replace("['", '')
    data[len(data)-1] = data[len(data)-1].replace("']", '')
    
    for d in range(0, len(data)):
        listQueryList.addItem(data[d])    

def loadConfig():
    output = []
    config = []

    try: 
        # Try to open the file
        f = open(f'./config.ini', 'r', encoding='utf-8-sig') 
        config = f.readlines()     
    except:   
        # If no file found, create one and set light as first item in config  
        f = open(f'./config.ini', 'w', encoding='utf-8-sig')    
        config.append('light') 
        f.writelines(config)   
    finally:
        # Close the file and output config
        f.close()
        output = config

    return output