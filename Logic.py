import os
import sys
import datetime
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject, QTimer, QByteArray
from PyQt6.QtGui import QGuiApplication, QColor
from PyQt6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog

sort_state = {}  # Global dict for per-col sort state (col: ascending)
sorting_active = False  # Global flag to prevent overlapping sorts

def buildTimestamps(startDateStr, endDateStr, intervalStr):
    print("[DEBUG] buildTimestamps called with start: {}, end: {}, interval: {}".format(startDateStr, endDateStr, intervalStr))

    try:
        start = datetime.strptime(startDateStr, '%Y-%m-%d %H:%M')
        end = datetime.strptime(endDateStr, '%Y-%m-%d %H:%M')
    except ValueError as e:
        print("[ERROR] Invalid date format in buildTimestamps: {}".format(e))
        return []
    
    if intervalStr == 'HOUR':
        delta = timedelta(hours=1)

        # Truncate start down to top of hour
        start = start.replace(minute=0, second=0)
    elif intervalStr == 'INSTANT':
        delta = timedelta(minutes=15)

        # Truncate down to nearest 15min
        minute = (start.minute // 15) * 15
        start = start.replace(minute=minute, second=0)
    elif intervalStr == 'DAY':
        delta = timedelta(days=1)

        # Truncate down to midnight
        start = start.replace(hour=0, minute=0, second=0)
    else:
        print("[ERROR] Unknown intervalStr: {}".format(intervalStr))
        return []
    
    timestamps = []
    current = start
    
    while current < end:
        ts_str = current.strftime('%m/%d/%y %H:%M:00')
        timestamps.append(ts_str)
        current += delta
    
    print("[DEBUG] Generated {} timestamps, sample first 3: {}".format(len(timestamps), timestamps[:3]))
    return timestamps

def gapCheck(timestamps, data, dataID=''):
    print("[DEBUG] gapCheck for dataID '{}': timestamps len={}, data len={}".format(dataID, len(timestamps), len(data)))

    if not timestamps:
        return data
    
    # Parse expected ts
    try:
        expected_dts = [datetime.strptime(ts, '%m/%d/%y %H:%M:00') for ts in timestamps]
    except ValueError as e:
        print("[ERROR] Invalid timestamp format in timestamps: {}".format(e))
        return data
    
    newData = []
    removed = []  # Collect details for warn
    i = 0

    for exp_dt in expected_dts:
        found = False

        while i < len(data):
            line = data[i]
            if not line:
                i += 1
                continue
            parts = line.split(',')
            if len(parts) < 2:
                print("[WARN] Malformed data row skipped: '{}' for '{}'".format(line, dataID))
                i += 1
                continue

            actual_ts_str = parts[0].strip()
            
            try:
                actual_dt = datetime.strptime(actual_ts_str, '%m/%d/%y %H:%M:%S')
            except ValueError:
                print("[WARN] Invalid ts skipped: '{}' in '{}' for '{}'".format(actual_ts_str, line, dataID))
                i += 1
                continue
            
            if actual_dt == exp_dt:
                # Match, add (ensure :00 seconds if not)
                if not actual_ts_str.endswith(':00'):
                    actual_ts_str = actual_dt.strftime('%m/%d/%y %H:%M:00')
                    line = actual_ts_str + ',' + ','.join(parts[1:])

                new_data.append(line)
                found = True
                i += 1
                break
            elif actual_dt < exp_dt:
                # Extra/early, remove
                removed.append(actual_ts_str)
                i += 1
            else:
                # Future/mismatch, insert gap and break to next exp
                break
        if not found:
            # Gap, insert blank
            ts_str = exp_dt.strftime('%m/%d/%y %H:%M:00')
            new_data.append(ts_str + ',')
    
    # Any remaining data are extras
    while i < len(data):
        line = data[i]
        parts = line.split(',')
        
        if len(parts) > 0:
            removed.append(parts[0].strip())
        i += 1
    
    if removed:
        print("[WARN] Removed {} extra/mismatched rows from '{}': ts {}".format(len(removed), dataID, removed))
    
    print("[DEBUG] Post-gapCheck len={}, sample first 3: {}".format(len(new_data), new_data[:3]))
    return new_data

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
    
    # Set up table structure (extra column for timestamp)
    table.setRowCount(len(data))
    table.setColumnCount(len(buildHeader) + 1)

    # Build header with center alignment (col 0 = timestamp)
    timestamp_header = QTableWidgetItem("Timestamp")
    timestamp_header.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
    table.setHorizontalHeaderItem(0, timestamp_header)

    for c in range(len(buildHeader)):
        item = QTableWidgetItem(str(buildHeader[c]))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        table.setHorizontalHeaderItem(c, item)

    # Populate data rows with center alignment
    for r in range(len(data)):
        row_data = data[r].split(',')

        for c in range(len(row_data)):
            item = QTableWidgetItem(row_data[c])
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setHorizontalHeaderItem(c + 1, item)

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

    # Resize all columns to fit headers + data
    for col in range(num_cols):
        table.resizeColumnToContents(col)

    # Warm-up dummy sort to trigger initial reflow (no shift on first real click)
    header = table.horizontalHeader()
    table.setSortingEnabled(False)  # Disable for dummy
    QTimer.singleShot(0, lambda: [
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder),  # Dummy ASC on col 0
        table.sortItems(0, Qt.SortOrder.AscendingOrder),  # Dummy sort (no change)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder),  # Clear with ASC
        table.setSortingEnabled(True)  # Re-enable
    ])  # Queued for next loop cycle (settles layout)

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
    if not dataID:
        return

    # Loop directly over dataID (list of IDs)
    for p, id_val in enumerate(dataID):       
        temp_index = getDataDictionaryItem(dataDictionaryTable, id_val) 
        row_index = int(temp_index) if temp_index is not None and temp_index != 'null' else None            

        if row_index is None: 
            continue # No match, skip entire column
        else:
            # Extract thresholds from dictionary row
            expected_min = float(dataDictionaryTable.item(row_index, 3).text()) if dataDictionaryTable.item(row_index, 3).text() else 0
            expected_max = float(dataDictionaryTable.item(row_index, 4).text()) if dataDictionaryTable.item(row_index, 4).text() else float('inf')
            cutoff_min = float(dataDictionaryTable.item(row_index, 5).text()) if dataDictionaryTable.item(row_index, 5).text() else expected_min
            cutoff_max = float(dataDictionaryTable.item(row_index, 6).text()) if dataDictionaryTable.item(row_index, 6).text() else expected_max
            roc = float(dataDictionaryTable.item(row_index, 7).text()) if dataDictionaryTable.item(row_index, 7).text() else 0

            col_index = p + 1 # Offset by 1 for timestamp col

            # Check each row in mainTable (skip header)
            for row in range(1, mainTable.rowCount()):   
                item = mainTable.item(row, col_index)
                print(f"Processing row {row}, col {col_index}: item = {item}")

                if not item:
                    continue

                cell_text = item.text()
                colored = False # Flag for text color

                if not cell_text:
                    item.setBackground(QColor(100, 195, 247)) # Missing (blue)
                    colored = True
                else:
                    try:
                        val = float(cell_text)

                        # Cutoffs (red/orange)
                        if val > cutoff_max:
                            item.setBackground(QColor(192, 28, 40)) # Red
                            colored = True
                        elif val < cutoff_min:
                            item.setBackground(QColor(255, 163, 72)) # Orange
                            colored = True

                        # Expected (yellow)
                        elif val > expected_max:
                            item.setBackground(QColor(245, 194, 17)) # Yellow
                            colored = True
                        elif val < expected_min:
                            item.setBackground(QColor(249, 240, 107)) # Light Yellow
                            colored = True

                        # ROC (red)
                        prev_val = None
                        prev_item = mainTable.item(row - 1, col_index) if row > 1 else None

                        if prev_item:
                            try:
                                prev_val = float(prev_item.text())

                                if abs(val - prev_val) > roc:
                                    item.setBackground(QColor(246, 97, 81)) # Red
                                    colored = True
                            except ValueError: 
                                pass

                        # Repeat (green)
                        if prev_val is not None and val == prev_val:
                            item.setBackground(QColor(87, 227, 137)) # Green
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

            # Re-center after any mod
            if item: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)                          

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
    config = ['light']  # Default color
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
            
    # Ensure path entry (index 1)
    while len(config) < 2:
        config.append('')  # Empty path default
    return config

def exportTableToCSV(table, fileLocation, fileName):
    if table.rowCount() == 0:
        print("Empty table—no export.")
        return

    # Get last path from config (default to Documents)
    config = loadConfig()
    last_path = config[1] if len(config) > 1 else os.path.expanduser("~/Documents")

    # Force Documents if last_path empty/invalid
    if not last_path or not os.path.exists(last_path):
        last_path = os.path.expanduser("~/Documents")
    default_dir = last_path

    # Timestamped default name (yyyy-mm-dd HH:mm:ss Export.csv)
    timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
    default_name = f"{timestamp} Export.csv"
    suggested_path = os.path.join(default_dir, default_name)
    file_path, _ = QFileDialog.getSaveFileName(None, "Save CSV As", suggested_path, "CSV files (*.csv)")

    if not file_path:
        return  # User canceled

    # Build CSV (your original logic)
    headers = [table.horizontalHeaderItem(h).text().replace('\n', ' | ') for h in range(table.columnCount())]
    csv_lines = [','.join(headers)]

    for r in range(table.rowCount()):
        row_data = [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())]
        csv_lines.append(','.join(row_data))

    # Write
    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(csv_lines))

    # Save last path to config (dir only)
    export_dir = os.path.dirname(file_path)
    if len(config) < 2:
        config.append(export_dir)  # Extend if short
    else:
        config[1] = export_dir  # Assign
    with open(resource_path('config.ini'), 'w', encoding='utf-8-sig') as f:
        f.write(f"{config[0]}\n{export_dir}\n")  # color\npath

    print(f"Exported to {file_path}")

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):  # Bundled mode
        base_path = sys._MEIPASS
    else:  # Dev mode
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_path, relative_path))

def custom_sort_table(table, col, dataDictionaryTable):
    # Prevent overlap (ignore if sorting already)
    pool = QThreadPool.globalInstance()
    if pool.activeThreadCount() > 0:
        return  # Skip during sort

    # Disable selection highlight during sort
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    # Clear indicator to stop Qt double-trigger
    header = table.horizontalHeader()
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # Clear (safe enum)

    # Toggle sort order (per-col state)
    if col not in sort_state:
        sort_state[col] = True  # Default ASC for new col
    else:
        sort_state[col] = not sort_state[col]  # Flip on every click
    ascending = sort_state[col]

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

    # Lock widths before QAQC (no reflow/shift)
    for c in range(table.columnCount()):
        table.setColumnWidth(c, table.columnWidth(c))  # Lock current

    # Re-apply QAQC colors
    header_labels = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    data_id = [label.split('\n')[-1].strip() for label in header_labels]  # Last line = raw ID
    qaqc(table, dataDictionaryTable, data_id)

    # Re-freeze col 0 (locked, no resize)
    table.setColumnWidth(0, 150)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.setViewportMargins(150, 0, 0, 0)

    # Re-enable selection (after sort, for normal use)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    # No resize here—locked prevents shift

class sortWorkerSignals(QObject):
    sort_done = pyqtSignal(list, bool)

class sortWorker(QRunnable):
    def __init__(self, rows, col, ascending):
        super(sortWorker, self).__init__()
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

def centerWindowToParent(ui):
    """Center a window relative to its parent (main window), robust for multi-monitor."""
    parent = ui.parent()

    if parent:
        # Get parent's screen for centering (multi-monitor aware)
        parent_center_point = parent.geometry().center()
        parent_screen = QGuiApplication.screenAt(parent_center_point)
        # Use parent's frame center for precise relative positioning
        parent_center = parent.frameGeometry().center()
        # Fallback if null (invalid)
        if parent_center.isNull():
            if parent_screen:
                parent_center = parent_screen.availableGeometry().center()
            else:
                parent_center = QGuiApplication.primaryScreen().availableGeometry().center()
    else:
        # No parent: Center on primary
        parent_center = QGuiApplication.primaryScreen().availableGeometry().center()
    
    # Center child's frame on parent's center
    rect = ui.frameGeometry()
    rect.moveCenter(parent_center)
    ui.move(rect.topLeft())