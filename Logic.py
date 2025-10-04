import os
import sys
import datetime
from datetime import datetime, timedelta
from PyQt6 import QtGui
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QThreadPool, QRunnable, pyqtSignal, QObject
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
    if not data:return

    # Assume buildHeader is list; split if str
    if isinstance(buildHeader, str):buildHeader = [h.strip() for h in buildHeader.split(',')]

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
    minute = int(parts[4])
    return datetime(year, month, day, hour, minute)

def getDataDictionaryItem(table, dataID):
    data_id_clean = dataID.strip()  # Clean input
    # Optional: Strip common prefixes (e.g., 'SDID', 'site') if API adds them
    for prefix in ['', 'SDID', 'site', 'uid']:  # Add more if needed
        if data_id_clean.startswith(prefix):
            data_id_clean = data_id_clean[len(prefix):].strip()
            break

    for r in range(table.rowCount()):
        id_item = table.item(r, 0)
        if id_item:
            csv_id = id_item.text().strip()
            # Same prefix strip for CSV
            csv_id_clean = csv_id
            for prefix in ['', 'SDID', 'site', 'uid']:
                if csv_id_clean.startswith(prefix):
                    csv_id_clean = csv_id_clean[len(prefix):].strip()
                    break
            if csv_id_clean == data_id_clean:
                return r
    return 'null'

def qaqc(mainTable, dataDictionaryTable, dataID):
    if not dataDictionaryTable:
        return

    # Cache dict for fast lookup (col 0=ID, 3=exp_min,4=exp_max,5=cut_min,6=cut_max,7=roc)
    dict_cache = {}
    for r in range(dataDictionaryTable.rowCount()):
        id_item = dataDictionaryTable.item(r, 0)  # Col 0 = dataID
        id_key = id_item.text().strip() if id_item else ''
        if id_key:
            try:
                dict_cache[id_key] = {
                    'exp_min': float(dataDictionaryTable.item(r, 3).text().strip() if dataDictionaryTable.item(r, 3) else '0'),
                    'exp_max': float(dataDictionaryTable.item(r, 4).text().strip() if dataDictionaryTable.item(r, 4) else float('inf')),
                    'cut_min': float(dataDictionaryTable.item(r, 5).text().strip() if dataDictionaryTable.item(r, 5) else float('-inf')),
                    'cut_max': float(dataDictionaryTable.item(r, 6).text().strip() if dataDictionaryTable.item(r, 6) else float('inf')),
                    'roc': float(dataDictionaryTable.item(r, 7).text().strip() if dataDictionaryTable.item(r, 7) else float('inf'))
                }
            except ValueError:
                pass  # Skip bad row

    for c in range(1, mainTable.columnCount()):
        parse_id = str(dataID[c - 1]).split('\n')[-1].strip()  # Last line = raw ID
        params = dict_cache.get(parse_id)
        if not params:
            continue  # Skip if no dict entry

        prev_val = None
        for d in range(mainTable.rowCount()):
            cell_text = mainTable.item(d, c).text() if mainTable.item(d, c) else ''
            item = QTableWidgetItem(cell_text)
            colored = False  # Flag for text color
            if not cell_text:
                item.setBackground(QColor(100, 195, 247))  # Missing (blue)
                colored = True
            else:
                try:
                    val = float(cell_text)
                    # Cutoffs (red/orange)
                    if val > params['cut_max']:
                        item.setBackground(QColor(192, 28, 40))
                        colored = True
                    elif val < params['cut_min']:
                        item.setBackground(QColor(255, 163, 72))
                        colored = True
                    # Expected (yellow)
                    elif val > params['exp_max']:
                        item.setBackground(QColor(245, 194, 17))
                        colored = True
                    elif val < params['exp_min']:
                        item.setBackground(QColor(249, 240, 107))
                        colored = True
                    # ROC (red)
                    if prev_val is not None and (val - prev_val) > params['roc']:
                        item.setBackground(QColor(246, 97, 81))
                        colored = True
                    # Repeat (green)
                    if prev_val is not None and val == prev_val:
                        item.setBackground(QColor(87, 227, 137))
                        colored = True
                    prev_val = val
                except ValueError:
                    pass  # Non-numeric: no color

            if colored:
                # White for all except yellow (black for yellow readability)
                if item.background().color() in [QColor(245, 194, 17), QColor(249, 240, 107)]:  # Yellows
                    item.setForeground(QColor("black"))
                else:
                    item.setForeground(QColor("white"))

            mainTable.setItem(d, c, item)

def loadAllQuickLooks(cbQuickLook):     
    cbQuickLook.clear()
    cbQuickLook.addItem(None)  # Blank first

    quicklook_dir = resource_path('quickLook')
    if os.path.exists(quicklook_dir):
        for file in os.listdir(quicklook_dir):
            if file.endswith('.txt'):
                cbQuickLook.addItem(file.split('.txt')[0])
                  
def saveQuickLook(textQuickLookName, listQueryList):
    name = textQuickLookName.toPlainText().strip() if hasattr(textQuickLookName, 'toPlainText') else str(textQuickLookName).strip()
    if not name:
        print("Warning: Empty quick look name—skipped.")
        return

    data = [listQueryList.item(x).text() for x in range(listQueryList.count())]
    quicklook_path = resource_path(f'quickLook/{name}.txt')
    os.makedirs(os.path.dirname(quicklook_path), exist_ok=True)  # Ensure dir
    with open(quicklook_path, 'w', encoding='utf-8-sig') as f:
        f.write(','.join(data))

def loadQuickLook(cbQuickLook, listQueryList):
    name = cbQuickLook.currentText()
    if not name:
        return

    quicklook_path = resource_path(f'quickLook/{name}.txt')
    listQueryList.clear()
    try:
        with open(quicklook_path, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()
            if content:
                data = content.split(',')
                for item_text in data:
                    listQueryList.addItem(item_text.strip())
    except FileNotFoundError:
        print(f"Quick look '{name}' not found.")  

def loadConfig():
    config = ['light']  # Default
    config_path = resource_path('config.ini')
    try:
        with open(config_path, 'r', encoding='utf-8-sig') as f:
            config = [line.strip() for line in f.readlines()]
            if not config:  # Empty file
                config = ['light']
    except FileNotFoundError:
        # Create if missing
        with open(config_path, 'w', encoding='utf-8-sig') as f:
            f.write('light\n')
    return config

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
    if getattr(sys, 'frozen', False):  # Bundled mode
        base_path = sys._MEIPASS
    else:  # Dev mode
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_path, relative_path))

def custom_sort_table(table, col, dataDictionaryTable):
    # Get current sort order (toggle asc/dec per col)
    header = table.horizontalHeader()
    sort_indicator = header.sortIndicatorSection()
    ascending = header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
    if sort_indicator == col:
        ascending = not ascending  # Toggle
    else:
        ascending = True  # Default asc for new col

    # Extract rows in main thread (fast, just text)
    num_rows = table.rowCount()
    rows = []
    for row_idx in range(num_rows):
        timestamp = table.verticalHeaderItem(row_idx).text() if table.verticalHeaderItem(row_idx) else ''  # From vertical
        row_data = [table.item(row_idx, c).text() if table.item(row_idx, c) else '' for c in range(table.columnCount())]
        rows.append([timestamp] + row_data)  # Timestamp first

    # Start pooled worker (auto-managed, no destroy warning)
    pool = QThreadPool.globalInstance()
    worker = sortWorker(rows, col, ascending)
    worker.signals.sort_done.connect(lambda sorted_rows, asc: update_table_after_sort(table, sorted_rows, asc, dataDictionaryTable, col))
    pool.start(worker)

    # Set sort indicator immediately (UI feedback)
    header.setSortIndicator(col, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)

def update_table_after_sort(table, sorted_rows, ascending, dataDictionaryTable, col):
    # Re-populate on main thread
    table.setSortingEnabled(False)  # Disable default sort
    num_rows = len(sorted_rows)
    for row_idx, row in enumerate(sorted_rows):
        # Vertical: Timestamp
        table.setVerticalHeaderItem(row_idx, QTableWidgetItem(row[0]))
        # Data cols
        for c in range(table.columnCount()):
            cell_text = row[c + 1]
            item = QTableWidgetItem(cell_text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row_idx, c, item)

    # Re-apply QAQC colors
    header_labels = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    data_id = [label.split('\n')[-1].strip() for label in header_labels]  # Last line = raw ID
    qaqc(table, dataDictionaryTable, data_id)

    # Re-freeze col 0
    table.setColumnWidth(0, 150)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.setViewportMargins(150, 0, 0, 0)

    # Resize others
    for c in range(1, table.columnCount()):
        table.resizeColumnToContents(c)

class sortWorkerSignals(QObject):
    sort_done = pyqtSignal(list, bool)

class sortWorker(QRunnable):
    def __init__(self, rows, col, ascending):
        super().__init__()
        self.signals = sortWorkerSignals()
        self.rows = rows
        self.col = col
        self.ascending = ascending

    def run(self):
        def sort_key(row):
            try:
                return float(row[self.col + 1])
            except ValueError:
                return 0

        self.rows.sort(key=sort_key, reverse=not self.ascending)
        self.signals.sort_done.emit(self.rows, self.ascending)

class sortThread(QThread):
    sort_done = pyqtSignal(list, bool, list)  # Emits sorted_rows, ascending, data_id

    def __init__(self):
        super().__init__()
        self.rows = None
        self.col = None
        self.ascending = None

    def run(self):
        # Sort in background
        def sort_key(row):
            try:
                return float(row[self.col + 1])  # Skip timestamp
            except ValueError:
                return 0  # Fallback

        self.rows.sort(key=sort_key, reverse=not self.ascending)
        self.sort_done.emit(self.rows, self.ascending, [])  # Empty data_id placeholder
        self.quit()  # Stop event loop