import urllib.request
import json
import datetime
from datetime import timedelta

def API(database, dataID, startTime, endTime, dataInterval): 
    # Parse out start time   
    startTime = str(startTime.dateTime()).replace("'",'')
    startTime = startTime.replace(' ','')
    startYear = startTime.split(',')[0].split('(')[1]
    startMonth = startTime.split(',')[1]
    startDay = startTime.split(',')[2]
    startHour = startTime.split(',')[3]
    if len(startHour) == 1: startHour = f'0{startHour}'
    startMinute = startTime.split(',')[4]   
    if len(startMinute) == 1: startMinute = f'0{startMinute}'

    # Parse out end time   
    endTime = str(endTime.dateTime()).replace("'",'')
    endTime = endTime.replace(' ','')
    endYear = endTime.split(',')[0].split('(')[1]
    endMonth = endTime.split(',')[1]
    endDay = endTime.split(',')[2]
    endHour = endTime.split(',')[3]
    if len(endHour) == 1: endHour = f'0{endHour}'
    endMinute = endTime.split(',')[4]   
    if len(endMinute) == 1: endMinute = f'0{endMinute}'

    # Set the inverval   
    if dataInterval.currentText() == 'HOUR': interval = 'HR'
    if dataInterval.currentText() == 'INSTANT': interval = 'IN'
    if dataInterval.currentText() == 'DAY': interval = 'DY'

    # Remove agency from database string, which will leave you just with database name
    database = database.currentText().lower().split('-')[1]
    
    # Query the data
    url = f'https://www.usbr.gov/pn-bin/hdb/hdb.pl?svr={database}&sdi={dataID}&tstp={interval}&t1={startYear}-{startMonth}-{startDay}T{startHour}:{startMinute}&t2={endYear}-{endMonth}-{endDay}T{endHour}:{endMinute}&table=R&mrid=0&format=json'
    webQuery = urllib.request.urlopen(url)
    readfile = webQuery.read().decode("utf-8")
    readfile = json.loads(readfile)
    readfile = readfile['Series']   

    output = []
    buildHeader = []
    
    for s in range(0, len(readfile)):            
            siteInfo = readfile[s]       
            buildHeader.append(siteInfo['SDI'])  
            siteInfo = siteInfo['Data']       

            for d in range(0, len(siteInfo)):
                data = siteInfo[d]                    
                value = data['v']  
                dateTime = data['t']             
                dateTime = dateTime.split(' ')
                year = dateTime[0].split('/')[2]
                month = dateTime[0].split('/')[0]
                day = dateTime[0].split('/')[1]
                hour = dateTime[1].split(':')[0]
                minute = dateTime[1].split(':')[1]
                second = dateTime[1].split(':')[2]
                dateTime = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))   
                if dataInterval.currentText() == 'HOUR': dateTime = dateTime + timedelta(hours = 1) 

                # Change time from 12 hour clock to 24
                if data['t'].split(' ')[2] == 'AM':
                    if int(hour) == 12: dateTime = dateTime - timedelta(hours = 12)
                else:
                    if data['t'].split(' ')[2] == 'PM':
                        if int(hour) < 12: dateTime = dateTime + timedelta(hours = 12)

                dateTime = '{:%m/%d/%y %H:%M:%S}'.format(dateTime)         

                if s == 0: 
                    output.append(f'{dateTime},{value}')  
                else:
                    output[d] = f'{output[d]},{value}'
    
    # Add headers as first item in list
    output.insert(0, buildHeader)

    return output