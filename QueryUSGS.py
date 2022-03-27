import requests
import json
import datetime
import Logic
from datetime import timedelta

def API(dataID, dataInterval, startTime, endTime):
    output = []
    buildHeader = []

    # Split dataID to handle multiple queries
    parseID = dataID.split(',')

    for i in range(0, len(parseID)):
        buildHeader.append(parseID[i])

        # Parse out site, parameter, and method
        site = parseID[i].split('-')[0]
        method = parseID[i].split('-')[1]
        parameter = parseID[i].split('-')[2]

        # Set the inverval   
        if dataInterval.currentText() == 'HOUR': interval = 'iv'
        if dataInterval.currentText() == 'INSTANT': interval = 'iv'
        if dataInterval.currentText() == 'DAY': interval = 'dv'

        # Set period based on time range
        period = Logic.buildDTEDateTime(endTime) - Logic.buildDTEDateTime(startTime)
        period = period.total_seconds() / 3600
        period = str(period).split('.')[0]

        # This is executed when the button is pressed
        url = requests.get(f'https://waterservices.usgs.gov/nwis/{interval}/?format=json&sites={site}&period=PT{period}H&parameterCD=000{parameter}&sitestatus=all')
        readfile = json.loads(url.content)
        readfile = readfile['value']
        readfile = readfile['timeSeries']
        readfile = readfile[0]
        siteName = readfile['sourceInfo']['siteName']
        readfile = readfile['values']        
        
        data = readfile[0]            
                        
        if int(method) == int(data['method'][0]['methodID']):  
            data = data['value']    

            for d in range(0, len(data)):  
                value = data[d]['value']  
                dateTime = data[d]['dateTime']             
                dateTime = dateTime.replace('T', ' ').split('.')[0]
                year = dateTime.split('-')[0]
                month = dateTime.split('-')[1]
                day = dateTime.split('-')[2].split(' ')[0]
                hour = dateTime.split(' ')[1].split(':')[0]
                minute = dateTime.split(' ')[1].split(':')[1]
                second = dateTime.split(' ')[1].split(':')[2]
                dateTime = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))                   
                dateTime = '{:%m/%d/%y %H:%M:%S}'.format(dateTime)

                if i == 0: 
                    output.append(f'{dateTime},{value}')  
                else:
                    output[d] = f'{output[d]},{value}'
                

    # Add headers as first item in list   
    output.insert(0, buildHeader)

    return output 