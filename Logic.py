import os
import sys
import datetime
from datetime import datetime, timedelta
from PyQt6 import QtGui
from PyQt6.QtWidgets import QTableWidgetItem

def buildTimestamps(startDate, endDate, dataInterval):
    # Set the inverval   
    if dataInterval.currentText() == 'HOUR': interval = timedelta(hours = 1)
    if dataInterval.currentText() == 'INSTANT': interval = timedelta(minutes = 15)
    if dataInterval.currentText() == 'DAY': interval = timedelta(days = 1) 

    counter = 0
    currentTimestamp = datetime.fromisoformat(startDate)
    endDate = datetime.fromisoformat(endDate)

    while currentTimestamp < endDate:
        # Add interval to current timestamp
        currentTimestamp = currentTimestamp + interval   

        # Parse out date/time
        month = currentTimestamp.month
        day = currentTimestamp.day
        hour = currentTimestamp.hour
        minute = currentTimestamp.minute

        # Zero out minutes if the interval is anything other than instant
        if not(dataInterval.currentText() == 'INSTANT'): minute = '00'

        # Create 2 digit month and day for isoformatting to work
        if len(str(month)) == 1: month = f'0{month}'
        if len(str(day)) == 1: day = f'0{day}'
        if len(str(hour)) == 1: hour = f'0{hour}'
        if len(str(minute)) == 1: minute = f'0{minute}'
        
        # Build the output of timestamps
        if counter == 0: 
            output = f'{currentTimestamp.year}-{month}-{day} {hour}:{minute}'
        else:
            output = f'{output},{currentTimestamp.year}-{month}-{day} {hour}:{minute}'

        counter += 1

    return output

def gapCheck(timestamps, data):
    parseLine = []
    parseTimestamps = []
    parseTimestamps = timestamps.split(',')

    for t in range(0, len(parseTimestamps) - 1):
        # Format date from ISO format to desired format
        parseTimestamps[t] = datetime.strftime(datetime.fromisoformat(parseTimestamps[t]), '%m/%d/%y %H:%M:%S')

        # If there is no data, all data for range is missing
        if len(data) == 0:
            data.insert(t,f'{parseTimestamps[t]},')  
        else:
            # If there is only data in the beginning of the list, this will stop the code from breaking
            if len(data) - 1 < t:
                data.insert(t,f'{parseTimestamps[t]},')  
            else:
                # Split the timestamp out of the data line
                parseLine = data[t].split(',')               
                
                # Check to see if the timestamps match. If they don't, there is missing data
                if datetime.strptime(parseTimestamps[t], '%m/%d/%y %H:%M:%S') != datetime.strptime(parseLine[0], '%m/%d/%y %H:%M:%S'): 
                    # Insert created timestamp and place a blank
                    data.insert(t,f'{parseTimestamps[t]},')  

    return data

def combineParameters(data, newData):
    for d in range(0, len(newData)):
        parseLine = newData[d].split(',')
        data[d] = f'{data[d]},{parseLine[1]}'  
    
    return data

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
        table.setRowCount(len(data))                
        table.setColumnCount(len(data[0].split(',')))                       
        table.setHorizontalHeaderLabels(header.split(','))  
        
        for d in range(0, len(data)):       
            for c in range(0, len(data[d].split(','))):
                table.setItem(d, c, QTableWidgetItem(data[d].split(',')[c])) 
                
        # Resize columns to fit the data
        for s in range(0, len(data[0].split(','))): 
            table.resizeColumnToContents(s)  

def buildDataDictionary(table):
    data = []      

    # Open the file     
    f = open(resource_path('DataDictionary.csv'), 'r', encoding='utf-8-sig')  

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

    output = datetime(int(year), int(month), int(day), int(hour), int(minute))   

    return output

def getDataDictionaryItem(table, dataID):
    output = 'null'    

    # Check every row in the dictionary for data ID
    for r in range(0, table.rowCount()):
        if table.item(r, 0).text() == dataID: output = r

    return output

def qaqc(mainTable, dataDictionaryTable, dataID): 
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
                item = QTableWidgetItem(mainTable.item(d, c).text()) 

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
    for file in os.listdir(resource_path('quickLook')):
        # Open the file
        f = open(resource_path(f'quickLook/{file}'), 'r', encoding='utf-8-sig')  
        
        # Read all lines in the file         
        readfile = f.readlines()  

        # Close the file  
        f.close() 

        # Add all lines as combobox items     
        cbQuickLook.addItem(str(file).split('.txt')[0]) 
                  
def saveQuickLook(textQuickLookName, listQueryList):
    # Create a file or open if it deson't exist
    f = open(resource_path(f'quickLook/{textQuickLookName.toPlainText()}.txt'), 'w', encoding='utf-8-sig')    
    
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
    f = open(resource_path(f'quickLook/{cbQuickLook.currentText()}.txt'), 'r', encoding='utf-8-sig')           
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
        f = open(resource_path('config.ini'), 'r', encoding='utf-8-sig') 
        config = f.readlines()     
    except:   
        # If no file found, create one and set light as first item in config  
        f = open(resource_path('config.ini'), 'w', encoding='utf-8-sig')    
        config.append('light') 
        f.writelines(config)   
    finally:
        # Close the file and output config
        f.close()
        output = config

    return output

def exportTableToCSV(table, fileLocation, fileName):
    data = []    

    # Save all header information into array before looping through the rows
    for h in range(0, table.columnCount()):
        if h == 0: data.append(table.horizontalHeaderItem(h).text())
        else: 
            header = table.horizontalHeaderItem(h).text().replace('\n', ' | ')
            data[0] = f'{data[0]},{header}'

    # Check each column and each row in the table. Place data into array
    for r in range(0, table.rowCount()):            
        for c in range(0, table.columnCount()):            
            if c == 0: data.append('\n' + table.item(r, c).text())
            else: data[r + 1] = f'{data[r + 1]},{table.item(r, c).text()}'

    # Write the data to the file
    f = open(f'{fileLocation}/{fileName}.csv', 'w', encoding='utf-8-sig')     
    f.writelines(data) 

    # Close the file
    f.close()

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False): # Bundeled mode
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    else: # Dev mode
        base_path = os.path.dirname(os.path.abspath(__file__)) # Scripts directory  
    full_path = os.path.join(base_path, relative_path)

    return os.path.normpath(full_path) # Normalize slashes