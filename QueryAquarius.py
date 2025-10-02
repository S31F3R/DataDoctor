import requests
import json
import Logic
from datetime import datetime, timedelta

def api(dataID, startTime, endTime, dataInterval): 
    # Get Aquarius settings
    server = ''
    user = ''
    password = ''
    utcOffset = -7

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

    # Create 2 digit month and day for isoformatting to work
    if len(startMonth) == 1: startMonth = f'0{startMonth}'
    if len(startDay) == 1: startDay = f'0{startDay}'
    if len(endMonth) == 1: endMonth = f'0{endMonth}'
    if len(endDay) == 1: endDay = f'0{endDay}'

    # Build start and end date is ISO format
    startDate = f'{startYear}-{startMonth}-{startDay} {startHour}:{startMinute}'
    endDate = f'{endYear}-{endMonth}-{endDay} {endHour}:{endMinute}'

    # Build timestamps
    timestamps = Logic.buildTimestamps(startDate, endDate, dataInterval)

    # Apply utc offset for Aquarius query    
    startDate = datetime.fromisoformat(startDate) - timedelta(0, 0, 0, 0, 0, utcOffset)
    endDate = datetime.fromisoformat(endDate) - timedelta(0, 0, 0, 0, 0, utcOffset)

    # Create 2 digit month and day for isoformatting to work
    startMonth = startDate.month
    if len(str(startDate.month)) == 1: startMonth = f'0{startDate.month}'   
    startDay = startDate.day
    if len(str(startDate.day)) == 1: startDay = f'0{startDate.day}'
    startHour = startDate.hour
    if len(str(startDate.hour)) == 1: startHour = f'0{startDate.hour}'
    startMinute = startDate.minute
    if len(str(startDate.minute)) == 1: startMinute = f'0{startDate.minute}'
    endMonth = endDate.month
    if len(str(endDate.month)) == 1: endMonth = f'0{endDate.month}'
    endDay = endDate.day
    if len(str(endDate.day)) == 1: endDay = f'0{endDate.day}'
    endHour = endDate.hour
    if len(str(endDate.hour)) == 1: endHour = f'0{endDate.hour}'
    endMinute = endDate.minute
    if len(str(endDate.minute)) == 1: endMinute = f'0{endDate.minute}'

    # Build start and end date is ISO format
    startDate = f'{startDate.year}-{startMonth}-{startDay} {startHour}:{startMinute}' 
    endDate = f'{endDate.year}-{endMonth}-{endDay} {endHour}:{endMinute}'

    output = []

    # Create json string
    data = {'Username':f'{user}','EncryptedPassword':f'{password}'}

    # Authenticate session
    url = requests.post(f'{server}/AQUARIUS/Provisioning/v1/session', data=data, verify=False)

    # Create API headers
    headers = {'X-Authentication-Token':url.text}   

    # Create table header array
    buildHeader = []

    # Parse dataID
    uid = dataID.split(',')    

    for d in range(0, len(uid)):
        # Query the data    
        url = requests.get(f'{server}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData?TimeSeriesUniqueId={uid[d]}&QueryFrom={startDate}&QueryTo={endDate}&UtcOffset={utcOffset}&GetParts=PointsOnly&format=json', headers=headers, verify=False)

        # Read the json data
        readfile = json.loads(url.content)

        # Create arrays
        outputData = []
        header = []        

        # Add label to header
        header.append(readfile['LocationIdentifier'])
        header.append(readfile['Label'])
        buildHeader.append(f'{header[0]} \n{header[1]}')

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

            #print(f'Date: {date} Value: {value}')
            outputData.append(f'{date},{value}')      

        # Check for gaps
        outputData = Logic.gapCheck(timestamps, outputData)   

        # Combine parameters
        if d != 0: output = Logic.combineParameters(output, outputData)  

        # If this is the first parameter, add it to output
        else: output = outputData  

    # Add headers as first item in list
    output.insert(0, buildHeader)

    return output