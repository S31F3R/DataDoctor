import os
import sys
import datetime
from datetime import datetime, timedelta
from PyQt6 import QtGui
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject
from PyQt6.QtGui import QColor  # For QAQC cell colors
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QTableWidget, QLabel, QAbstractItemView

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
    if not timestamps:
        return data
    parseTimestamps = timestamps.split(',')
    parseTimestamps = [datetime.fromisoformat(ts).strftime('%m/%d/%y %H:%M:%S') for ts in parseTimestamps]

    for t in range(len(parseTimestamps) - 1):
        expected_ts = datetime.strptime(parseTimestamps[t], '%m/%d/%y %H:%M:%S')
        if t >= len(data):
            data.insert(t, f'{parseTimestamps[t]},')
        else:
            actual_line = data[t].split(',')
            actual_ts = datetime.strptime(actual_line[0], '%m/%d/%y %H:%M:%S')
            if expected_ts != actual_ts:
                data.insert(t, f'{parseTimestamps[t]},')

    return data

def combineParameters(data, newData):
    if len(data) != len(newData):
        return data  # Mismatch—skip
    for d in range(len(newData)):
        parseLine = newData[d].split(',')
        data[d] = f'{data[d]},{parseLine[1]}'
    return data

def buildTable(table, data, buildHeader, dataDictionaryTable):
    table.clear()
    if not data:
        return

    # Assume buildHeader is list; split if str
    if isinstance(buildHeader, str):
        buildHeader = [h.strip() for h in buildHeader.split(',')]

    # Build processed headers with dict lookup (list for efficiency)
    processed_headers = []
    for h in buildHeader:
        header_text = h.strip()  # Strip raw header
        if dataDictionaryTable:
            dict_row = getDataDictionaryItem(dataDictionaryTable, header_text)
            if dict_row != 'null':
                label_item = dataDictionaryTable.item(dict_row, 2)
                if label_item:
                    parse_label = label_item.text().split(':')
                    if len(parse_label) > 1:
                        parse_label[1] = parse_label[1][1:].strip()  # Strip label part
                        header_text = f'{parse_label[0].strip()} \n{parse_label[1]} \n{header_text}'
        processed_headers.append(header_text)

    # Headers: Processed only (no Date prepend)
    headers = processed_headers

    # Conditional skip for main table (skip date col 0)
    skip_date_col = dataDictionaryTable  # True for main, False for dict
    num_cols = len(headers)
    num_rows = len(data)
    table.setRowCount(num_rows)
    table.setColumnCount(num_cols)
    table.setHorizontalHeaderLabels(headers)  # Full list

    # Vertical: Timestamps for main table only (dict table no dates)
    if dataDictionaryTable:
        timestamps = [row.split(',')[0].strip() for row in data]
        table.setVerticalHeaderLabels(timestamps)
        table.verticalHeader().setMinimumWidth(120)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(True)
    else:
        table.verticalHeader().setVisible(False)  # Hide for dict

    # Populate data (conditional skip, center all)
    for row_idx, row_str in enumerate(data):
        row_data = row_str.split(',')[1:] if skip_date_col else row_str.split(',')  # Skip date for main
        for col_idx in range(min(num_cols, len(row_data))):
            cell_text = row_data[col_idx].strip() if col_idx < len(row_data) else ''
            item = QTableWidgetItem(cell_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row_idx, col_idx, item)

    # Freeze first column (dates, manual resize allowed)
    table.setColumnWidth(0, 150)  # Initial width
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Auto + manual drag
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setViewportMargins(150, 0, 0, 0)  # Pin on scroll

    # Resize all columns to fit headers + data
    for col in range(num_cols):
        table.resizeColumnToContents(col)
    
    # Connect custom sort (syncs timestamps)
    table.horizontalHeader().sectionClicked.connect(lambda col: custom_sort_table(table, col, dataDictionaryTable))

def buildDataDictionary(table):
    data = []
    csv_path = resource_path('DataDictionary.csv')
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            readfile = f.readlines()
            if readfile:
                header = readfile[0].strip().split(',')
                data = [line.strip() for line in readfile[1:]]
    except FileNotFoundError:
        print("DataDictionary.csv missing—create empty.")
        header = ['ID', 'Description', 'Label']  # Default header

    buildTable(table, data, header, None)

def buildDTEDateTime(dateTime):
    # Parse out date/time   
    dt_str = str(dateTime.dateTime()).replace("'", '').replace(' ', '')
    parts = dt_str.split(',')
    year = int(parts[0].split('(')[1])
    month = int(parts[1])
    day = int(parts[2])
    hour = int(parts[3])
    minute = int(parts