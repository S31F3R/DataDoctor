# uiDetails.py - Details window for displaying cell metadata or overlay info

from PyQt6.QtWidgets import QWidget, QTableWidgetItem, QAbstractItemView
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from PyQt6 import uic
from datetime import datetime
from core import Logic, Config

class uiDetails(QWidget):
    """Details window: Displays metadata or overlay info for a specific timeseries cell."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Load the UI file
        uic.loadUi(Logic.resourcePath('ui/winDetails.ui'), self)
        
        # Set window flags to stay on top of parent
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)  
        
        # Set icon
        self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/Info.png')))
        
        # Initialize table with no rows yet (column count set dynamically in populate)
        self.detailsTable.setSortingEnabled(True)
        self.detailsTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # Read-only
        self.detailsTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows) # Select whole rows
        self.detailsTable.verticalHeader().setVisible(False) # Hide row numbers to reduce extra space
        
        if Config.debug:
            Logic.logMessage("DEBUG", "uiDetails initialized")
    
    def populateDetails(self, queryType, seriesLabel, timestampStr, response, interval=None):
        """
        Populate the table with metadata or overlay info for the given cell.
        - queryType: str (e.g., "AQUARIUS", "USGS", "USBR", "overlay", "headerNormal", "headerDelta", "headerOverlay") for handling different modes.
        - seriesLabel: str (header label for the series/column).
        - timestampStr: str (timestamp from vertical header, e.g., "2023-01-01T00:00:00Z") or empty for headers.
        - response: dict (full API response for metadata, cell data for overlay, meta dict for headers).
        - interval: str (optional, e.g., 'HOUR' for USBR matchField logic).
        """
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Populating details for queryType: {queryType}, series: {seriesLabel}, timestamp: {timestampStr}")
        
        # Set title using first line of seriesLabel only (no timestamp for headers)
        titleLabel = seriesLabel.split('\n')[0] if '\n' in seriesLabel else seriesLabel
        if timestampStr:
            self.lblTitle.setText(f"Details for {timestampStr} - {titleLabel}")
        else:
            self.lblTitle.setText(f"Details for {titleLabel}")
        
        # Clear existing rows and set columns dynamically
        self.detailsTable.setRowCount(0)
        
        if queryType in ["overlay", "headerNormal", "headerDelta", "headerOverlay", "USBR"]:
            self.detailsTable.setColumnCount(2)
            self.detailsTable.setHorizontalHeaderLabels(["TAG", "VALUE"])
        else:
            self.detailsTable.setColumnCount(4)
            self.detailsTable.setHorizontalHeaderLabels(["Metadata Type", "Details", "Start Time", "End Time"])
        
        self.detailsTable.horizontalHeader().setStretchLastSection(True)
        
        # Handler dictionary for database-specific metadata (easy to add USGS)
        metadataHandlers = {
            "AQUARIUS": self.populateAquarius,
            "USGS": self.populateUSGS, # TODO: Implement for USGS
            "USBR": lambda ts, resp: self.populateUSBR(ts, resp, interval),
        }
        
        if queryType == "overlay":
            self.populateOverlay(timestampStr, response)
        elif queryType == "headerNormal":
            self.populateHeaderNormal(response)
        elif queryType == "headerDelta":
            self.populateHeaderDelta(response)
        elif queryType == "headerOverlay":
            self.populateHeaderOverlay(response)
        elif queryType in metadataHandlers:
            metadataHandlers[queryType](timestampStr, response)
        else:
            Logic.logMessage("WARN", f"Unknown queryType: {queryType} - No details populated")
            return
        
        # Resize table to contents
        self.detailsTable.resizeColumnsToContents()
        self.detailsTable.resizeRowsToContents()
        
        # Manually calculate and set window size to fit content exactly (no scroll bars)
        self.detailsTable.setMinimumHeight(0) # Prevent over-allocation for empty space
        self.detailsTable.verticalScrollBar().setVisible(False) # Suppress any latent scrollbar
        width = sum(self.detailsTable.columnWidth(i) for i in range(self.detailsTable.columnCount())) + self.detailsTable.verticalHeader().width() + self.detailsTable.frameWidth() * 2 + 30  # Tighter padding for borders/margins
        height = sum(self.detailsTable.rowHeight(i) for i in range(self.detailsTable.rowCount())) + self.detailsTable.horizontalHeader().height() + self.lblTitle.height() + self.detailsTable.frameWidth() * 2 + 30  # Tighter padding, account for frames
        self.resize(width, height)
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Populated {self.detailsTable.rowCount()} rows")
    
    def populateOverlay(self, timestampStr, data):
        """Internal method to populate for overlay cell data."""
        
        # Handle missing keys safely
        primaryVal = data.get('primaryVal', 'N/A') if data.get('primaryVal') is not None else 'N/A'
        secondaryVal = data.get('secondaryVal', 'N/A') if data.get('secondaryVal') is not None else 'N/A'
        delta = data.get('delta', 'N/A') if data.get('delta') is not None else 'N/A'
        
        # Respect Config.rawData for value formatting if needed (e.g., if vals are numeric)
        if not Config.rawData:
            try:
                primaryVal = Logic.valuePrecision(float(primaryVal)) if primaryVal != 'N/A' else 'N/A'
                secondaryVal = Logic.valuePrecision(float(secondaryVal)) if secondaryVal != 'N/A' else 'N/A'
                delta = Logic.valuePrecision(float(delta)) if delta != 'N/A' else 'N/A'
            except ValueError:
                pass # Keep as string if not numeric
        
        # Add rows for overlay specifics (broken out per user request)
        self.addRow("Primary Info", data.get('dataId1', 'N/A'))
        self.addRow("Primary Value", str(primaryVal))
        self.addRow("Primary Database", data.get('db1', 'N/A'))
        self.addRow("Secondary Info", data.get('dataId2', 'N/A'))
        self.addRow("Secondary Value", str(secondaryVal))
        self.addRow("Secondary Database", data.get('db2', 'N/A'))
        self.addRow("Delta", str(delta))
    
    def populateHeaderNormal(self, meta):
        """Internal method to populate for normal header metadata."""
        
        # Add query info
        query_infos = meta.get('queryInfos', 'N/A')
        query_str = query_infos[0] if isinstance(query_infos, list) else str(query_infos)
        self.addRow("Query Info", query_str)
        
        # Add stats (computed as in original)
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col']) # Assuming col in meta
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def populateHeaderDelta(self, meta):
        """Internal method to populate for delta header metadata."""
        
        # Add details (changed to "Calculation" per user suggestion)
        self.addRow("Calculation", f"{meta.get('dataIds', ['N/A', 'N/A'])[0]} - {meta.get('dataIds', ['N/A', 'N/A'])[1]}")
        
        # Add stats
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def populateHeaderOverlay(self, meta):
        """Internal method to populate for overlay header metadata."""
        
        # Add primary/secondary (tweaked per user request)
        self.addRow("Primary", meta.get('queryInfos', ['N/A', 'N/A'])[0])
        self.addRow("Secondary", meta.get('queryInfos', ['N/A', 'N/A'])[1])
        
        # Add stats
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def computeColumnStats(self, col):
        """Compute stats for a column (mirrors original logic)."""
        values = []
        for row in range(self.parent().mainTable.rowCount()):
            item = self.parent().mainTable.item(row, col)

            if item and item.text().strip():
                try:
                    values.append(float(item.text()))
                except ValueError:
                    pass
        if not values:
            return "N/A", "N/A", "N/A"
        maxVal = max(values)
        minVal = min(values)
        meanVal = sum(values) / len(values)
        
        # Use valuePrecision for formatting, handles rawData internally
        maxStr = Logic.valuePrecision(maxVal)
        minStr = Logic.valuePrecision(minVal)
        meanStr = Logic.valuePrecision(meanVal)
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Computed stats for column {col}: Max {maxStr}, Min {minStr}, Mean {meanStr}")
        
        return maxStr, minStr, meanStr
    
    def populateAquarius(self, timestampStr, response):
        """Internal method to populate for AQUARIUS response."""
        
        # Parse timestamp to datetime for comparisons
        try:
            timestamp = self.parseDateTime(timestampStr)
            if Config.debug:
                Logic.logMessage("DEBUG", f"populateDetails: Parsed timestamp {timestampStr} to {timestamp}")
        except ValueError as e:
            Logic.logMessage("ERROR", f"Failed to parse timestamp {timestampStr}: {e}")
            return
        
        # Find the matching TimeSeriesPoint (assuming Points is list of dicts)
        point = next((p for p in response.get('Points', []) if self.parseDateTime(p['Timestamp']) == timestamp), None)

        if not point:
            Logic.logMessage("WARN", f"No matching point found for timestamp {timestampStr}")
            return
        
        # Add rows for selected metadata (per list 1-10)
        
        # 1. Parameter/Label/Unit (series-level)
        self.addRow("Parameter", f"{response.get('Parameter', 'N/A')}, {response.get('Unit', 'N/A')}", response.get('Label', 'N/A'))
        
        # 2. Timestamp/Value (point-level, respect Config.rawData for formatting)
        value = point['Value']
        numeric = value.get('Numeric', 'N/A')
        display = Logic.valuePrecision(numeric) if not Config.rawData and numeric != 'N/A' else str(numeric)
        self.addRow("Value", display, point.get('Timestamp', 'N/A'))
        
        # 3-9: Arrays with time-range filtering
        self.addArrayRows("Approval", response.get('Approvals', []), timestamp, 
                           lambda item: f"Level: {item.get('ApprovalLevel', 'N/A')} ({item.get('LevelDescription', 'N/A')}) \nUser: {item.get('User', 'N/A')} \nApplied: {item.get('DateAppliedUtc', 'N/A')} \nComment: {item.get('Comment', 'N/A')}")
        
        self.addArrayRows("Qualifier", response.get('Qualifiers', []), timestamp, 
                           lambda item: f"Identifier: {item.get('Identifier', 'N/A')} | User: {item.get('User', 'N/A')} | Applied: {item.get('DateApplied', 'N/A')}")
        
        self.addArrayRows("Method", response.get('Methods', []), timestamp, 
                           lambda item: f"Code: {item.get('MethodCode', 'N/A')}")
        
        self.addArrayRows("Grade", response.get('Grades', []), timestamp, 
                           lambda item: f"Code: {item.get('GradeCode', 'N/A')}")
        
        self.addArrayRows("Gap Tolerance", response.get('GapTolerances', []), timestamp, 
                           lambda item: f"Tolerance (min): {item.get('ToleranceInMinutes', 'N/A')}")
        
        self.addArrayRows("Interpolation Type", response.get('InterpolationTypes', []), timestamp, 
                           lambda item: f"Type: {item.get('Type', 'N/A')}")
        
        self.addArrayRows("Note", response.get('Notes', []), timestamp, 
                           lambda item: f"Text: {item.get('NoteText', 'N/A')}")
    
    def populateUSGS(self, timestampStr, response):
        """Placeholder for USGS metadata population."""
        # TODO: Implement based on USGS API response structure
        # Example: self.addRow("Parameter Code", response.get('parameterCd', 'N/A'))
        # self.addRow("Value", response.get('value', 'N/A'), response.get('dateTime', 'N/A'), "")
        # Add array rows for qualifiers, etc.
        self.addRow("Note", "USGS metadata not implemented yet")
    
    def populateUSBR(self, timestampStr, response, interval):
        """Internal method to populate for USBR metadata (list of merged dicts)."""
        if not isinstance(response, list):
            Logic.logMessage("WARN", f"Invalid response for USBR: expected list, got {type(response).__name__}")
            return
        
        # Convert timestampStr ('mm/dd/yy HH:MM:00') to match query format ('YYYY-MM-DD HH24:MI:SS')
        try:
            tsDate = datetime.strptime(timestampStr, '%m/%d/%y %H:%M:00')
            matchKey = tsDate.strftime('%Y-%m-%d %H:%M:%S')
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted timestampStr {timestampStr} to matchKey {matchKey}")
        except ValueError as e:
            Logic.logMessage("ERROR", f"Failed to convert timestampStr {timestampStr}: {e}")
            return
        
        # Determine match field based on periodOffset (for HOUR)
        matchField = 'END_DATE_TIME' if interval == 'HOUR' and Config.periodOffset else 'START_DATE_TIME'
        
        # Filter row by exact match on matchField
        matchingRow = next((row for row in response if row.get(matchField) == matchKey), None)
        
        if not matchingRow:
            Logic.logMessage("WARN", f"No matching metadata for {matchKey} in USBR response")
            self.addRow("Note", "No metadata for this timestamp")
            return
        
        # Defined tag order (per user spec)
        tags = [
            'SDID', 'INTERVAL', 'START_DATE_TIME', 'END_DATE_TIME', 'DATE_TIME_LOADED',
            'INTERVAL_VALUE', 'RBASE_VALUE', 'VALIDATION', 'OVERWRITE_FLAG', 'METHOD_ID',
            'AGEN_ID', 'COLLECTION_SYSTEM_ID', 'LOADING_APPLICATION_ID', 'COMPUTATION_ID', 'DATA_FLAGS'
        ]
        
        # Add rows in order, value as str or '' if missing/None
        for tag in tags:
            value = matchingRow.get(tag)
            valStr = str(value) if value is not None else ''
            self.addRow(tag, valStr)
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Populated USBR metadata with {len(tags)} tags for {matchKey}")
    
    def addRow(self, metaType, details, startTime="", endTime=""):
        """Add a single row to the table (defaults for 2-column modes)."""
        row = self.detailsTable.rowCount()
        self.detailsTable.insertRow(row)
        self.detailsTable.setItem(row, 0, QTableWidgetItem(metaType))
        self.detailsTable.setItem(row, 1, QTableWidgetItem(details))

        if self.detailsTable.columnCount() > 2:
            self.detailsTable.setItem(row, 2, QTableWidgetItem(startTime))
            self.detailsTable.setItem(row, 3, QTableWidgetItem(endTime))
    
    def addArrayRows(self, metaType, items, timestamp, detailFormatter):
        """Add rows for array items matching the timestamp range."""
        added = False
        for item in items:
            try:
                start = self.parseDateTime(item.get('StartTime'))
                end = self.parseDateTime(item.get('EndTime'))
                if start <= timestamp <= end:
                    self.addRow(metaType, detailFormatter(item), item.get('StartTime', 'N/A'), item.get('EndTime', 'N/A'))
                    added = True
            except (ValueError, TypeError) as e:
                Logic.logMessage("WARN", f"Skipping invalid array item in {metaType}: {e}")
        if not added:
            self.addRow(metaType, "N/A")
    
    def parseDateTime(self, dtStr):
        """Parse string to datetime, assuming common formats (e.g., ISO)."""
        if not dtStr:
            raise ValueError("Empty datetime string")
        
        # Preprocess: remove microseconds and colon in tz offset
        dtStr = dtStr.split('.')[0] # Remove microseconds
        if dtStr[-3] == ':': # Remove colon in +HH:MM to +HHMM
            dtStr = dtStr[:-3] + dtStr[-2:]

        # Try formats
        formats = ['%m/%d/%y %H:%M:00', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']
        for fmt in formats:
            try:
                dt = datetime.strptime(dtStr, fmt)
                return dt.replace(tzinfo=None) # Return naive datetime for comparison
            except ValueError:
                pass

        # Fallback: remove all ':' in time part
        dtStr = dtStr.replace(':', '')
        formats_no_colon = ['%m/%d/%y %H%M00', '%Y-%m-%dT%H%M%S%z', '%Y-%m-%dT%H%M%S', '%Y-%m-%d %H%M%S']
        for fmt in formats_no_colon:
            try:
                dt = datetime.strptime(dtStr, fmt)
                return dt.replace(tzinfo=None) # Return naive datetime for comparison
            except ValueError:
                pass
        raise ValueError(f"Unsupported datetime format: {dtStr}")