import requests
import json
from datetime import datetime, timedelta

def API(dataID, startTime, endTime, dataInterval): 
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

    output = []
    buildHeader = []
    header = [None] * 2

    # Get Aquarius settings
    server = ''
    user = ''
    password = ''

    utcOffset = -7

    # Create json string
    data = {f'Username:{user},EncryptedPassword:{password}'}

    # Authenticate session
    url = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=data)

    # Create headers
    headers = {'X-Authentication-Token':url.text}    
    
    # Create 2 digit month and day for isoformatting to work
    if len(startMonth) == 1: startMonth = f'0{startMonth}'
    if len(startDay) == 1: startDay = f'0{startDay}'
    if len(endMonth) == 1: endMonth = f'0{endMonth}'
    if len(endDay) == 1: endDay = f'0{endDay}'

    # Build start date and format it
    startDate = f'{startYear}-{startMonth}-{startDay} {startHour}:{startMinute}'
    startDate = datetime.fromisoformat(startDate) - timedelta(0, 0, 0, 0, 0, utcOffset)

    # Build end date and format it
    endDate = f'{endYear}-{endMonth}-{endDay} {endHour}:{endMinute}'
    endDate = datetime.fromisoformat(endDate) - timedelta(0, 0, 0, 0, 0, utcOffset)

    # Query the data
    url = requests.get(f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectionData?TimeSeriesUniqueId={dataID}&QueryFrom={startDate}&QueryTo={endDate}&GetParts=PointsOnly&UtcOffset={utcOffset}')
    
    # Read the json data
    readfile = json.loads(url.content)

    for r in range(0, len(readfile['Points'])):
        # Pull date timestamp out of json string
        date = readfile['Points'][r]['Timestamp']
        
        # Parse date
        parseDate = date.split('T')
        parseDate[1] = parseDate[1].split('.')[0]

        # Format date from ISO format to desired format
        date = datetime.strftime(datetime.fromisoformat(f'{parseDate[0]} {parseDate[1]}'), '%m/%d/%y %H:%M:%S')

        # Pull queried paramater data out of json string
        value = readfile['Points'][r]['Value']['Numeric']

        print(f'Date: {date} Value: {value}')
        #output.append(f'{date},{value}')      
    
    return output