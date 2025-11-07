# uiDetails.py - Details window for displaying cell metadata or overlay info

from PyQt6.QtWidgets import QWidget, QTableWidgetItem, QAbstractItemView, QTabWidget, QVBoxLayout, QTableWidget, QSizePolicy
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
        
        # Zero main layout margins for single-panel view
        layout = self.layout()

        if layout:
            layout.setContentsMargins(0, 0, 0, 0)
        
        # Connect tab change for resize if tabWidget created later
        if hasattr(self, 'tabWidget') and self.tabWidget:
            self.tabWidget.currentChanged.connect(self.resizeToCurrentTab)
        
        if Config.debug:
            Logic.logMessage("DEBUG", "uiDetails initialized")

    def resizeToCurrentTab(self, index):
        """Resize window to fit current tab's content without scrollbars."""
        if not hasattr(self, 'tabWidget') or not self.tabWidget:
            return
        
        currentTab = self.tabWidget.widget(index)
        if not currentTab:
            return
        
        tabTable = currentTab.findChild(QTableWidget)
        if not tabTable:
            return
        
        # Calculate size based on tab table
        tabTable.resizeColumnsToContents()
        tabTable.resizeRowsToContents()
        tabTable.verticalScrollBar().setVisible(False) # Suppress scrollbar
        tabTable.horizontalScrollBar().setVisible(False) # Suppress horizontal too
        tabTable.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # Always off to avoid space reservation        
        width = sum(tabTable.columnWidth(i) for i in range(tabTable.columnCount())) + tabTable.verticalHeader().width() + tabTable.frameWidth() * 2 + 50 # +50 buffer for right gap
        height = sum(tabTable.rowHeight(i) for i in range(tabTable.rowCount())) + tabTable.horizontalHeader().height() + self.lblTitle.height() + self.tabWidget.tabBar().height() + tabTable.frameWidth() * 2 + 30 # Reduced buffer to avoid extra row
        self.resize(width, height)
    
        if Config.debug:
            Logic.logMessage("DEBUG", f"Resized to current tab {index}: {width}x{height}")

    def populateDetails(self, queryType, seriesLabel, timestampStr, response, interval=None, multiTypes=None, responsesList=None, intervalsList=None):
        """
        Populate the table with metadata or overlay info for the given cell.
        - queryType: str (e.g., "AQUARIUS", "USGS", "USBR", "overlay", "headerNormal", "headerDelta", "headerOverlay") for handling different modes.
        - seriesLabel: str (header label for the series/column).
        - timestampStr: str (timestamp from vertical header, e.g., "2023-01-01T00:00:00Z") or empty for headers.
        - response: dict (full API response for metadata, cell data for overlay, meta dict for headers).
        - interval: str (optional, e.g., 'HOUR' for USBR matchField logic).
        - multiTypes: list (optional, e.g., ['overlay', 'USBR', 'AQUARIUS']) for tabbed view.
        - responsesList: list (optional, matching multiTypes order) for per-tab data.
        - intervalsList: list (optional, matching multiTypes order) for per-tab intervals.
        """        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Populating details for queryType: {queryType}, series: {seriesLabel}, timestamp: {timestampStr}, multiTypes={multiTypes}")
        
        # Set title using first line of seriesLabel only (no timestamp for headers)
        titleLabel = seriesLabel.split('\n')[0] if '\n' in seriesLabel else seriesLabel
        if timestampStr:
            self.lblTitle.setText(f"Details for {timestampStr} - {titleLabel}")
        else:
            self.lblTitle.setText(f"Details for {titleLabel}")
        
        # Clear existing rows and set columns dynamically
        self.detailsTable.setRowCount(0)
        
        if queryType in ["overlay", "headerNormal", "headerDelta", "headerOverlay", "USBR", "USGS"]:
            self.detailsTable.setColumnCount(2)
            self.detailsTable.setHorizontalHeaderLabels(["Type", "Value"])
        else:
            self.detailsTable.setColumnCount(4)
            self.detailsTable.setHorizontalHeaderLabels(["Metadata Type", "Details", "Start Time", "End Time"])
        
        self.detailsTable.horizontalHeader().setStretchLastSection(True)
        
        # Handler dictionary for database-specific metadata (easy to add USGS)
        metadataHandlers = {
            "AQUARIUS": lambda ts, resp, interval=None, table=None: self.populateAquarius(ts, resp, table=table), # Ignore interval
            "USGS": lambda ts, resp, interval=None, table=None: self.populateUSGS(ts, resp, table=table), # Ignore interval
            "USBR": lambda ts, resp, interval=None, table=None: self.populateUSBR(ts, resp, interval, table=table),
        }
        
        # If multiTypes provided (e.g., for overlay cell), use tabs
        if multiTypes and len(multiTypes) > 1:
            # Create QTabWidget if not exists
            if not hasattr(self, 'tabWidget') or not self.tabWidget:
                self.tabWidget = QTabWidget(self)
                layout = self.layout() # Assuming QVBoxLayout or similar from .ui
                if layout:
                    layout.addWidget(self.tabWidget)
                self.detailsTable.hide() # Hide original table, use per-tab tables
                self.tabWidget.currentChanged.connect(self.resizeToCurrentTab) # Connect here if created
            
            # Clear existing tabs
            while self.tabWidget.count() > 0:
                self.tabWidget.removeTab(0)
            
            # Track max width for min window size
            maxTabWidth = 0
            
            # Add tabs in order (Overlay first, then DBs)
            for i, t in enumerate(multiTypes):
                # Normalize t for handlers (e.g., 'USBR-LCHDB' -> 'USBR')
                normT = t.split('-')[0] if '-' in t else t
                
                tabResp = responsesList[i] if responsesList and i < len(responsesList) else {}
                tabIntvl = intervalsList[i] if intervalsList and i < len(intervalsList) else 'HOUR'
                
                tabWidget = QWidget()
                tabLayout = QVBoxLayout(tabWidget)
                tabLayout.setContentsMargins(0, 0, 0, 0) # Zero margins to remove gaps
                tabTable = QTableWidget(tabWidget) # New table per tab
                tabTable.setSortingEnabled(True)
                tabTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                tabTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                tabTable.verticalHeader().setVisible(False)
                tabTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding) # Expand to fill layout
                tabTable.horizontalScrollBar().setVisible(False) # Hide horizontal scrollbar
                tabTable.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # Always off to avoid space reservation
                
                # Set columns/headers based on type
                if normT in ["overlay", "USBR", "USGS"]:
                    tabTable.setColumnCount(2)
                    tabTable.setHorizontalHeaderLabels(["Type", "Value"])
                else:
                    tabTable.setColumnCount(4)
                    tabTable.setHorizontalHeaderLabels(["Metadata Type", "Details", "Start Time", "End Time"])
                tabTable.horizontalHeader().setStretchLastSection(True)
                
                # Populate per type
                if normT == 'overlay':
                    self.populateOverlay(timestampStr, tabResp, table=tabTable) # Pass custom table
                elif normT in metadataHandlers:
                    metadataHandlers[normT](timestampStr, tabResp, interval=tabIntvl, table=tabTable) # Pass custom table and interval
                else:
                    Logic.logMessage("WARN", f"Unknown type {t} (normalized {normT}) in multiTypes - Skipped tab")
                    continue                
                tabLayout.addWidget(tabTable)
                
                # Tab name: Uppercase abbreviations/suffixes, capitalize "Details"
                if t.upper() in ['USBR', 'USGS'] or '-' in t:
                    tabName = t.upper() + " Details"
                else:
                    tabName = t.capitalize() + " Details"
                if i > 0: # For DB tabs
                    if len(multiTypes) > 2 and multiTypes[1] == multiTypes[2]:
                        tabName = t.upper() + (" (Primary)" if i == 1 else " (Secondary)") + " Details"                
                self.tabWidget.addTab(tabWidget, tabName)
                
                # Initial resize table (final resize on tab change)
                tabTable.resizeColumnsToContents()
                tabTable.resizeRowsToContents()
                
                # Update maxTabWidth
                tempWidth = sum(tabTable.columnWidth(j) for j in range(tabTable.columnCount())) + tabTable.verticalHeader().width() + tabTable.frameWidth() * 2 + 50
                maxTabWidth = max(maxTabWidth, tempWidth)
            
            # Set min width based on widest tab
            self.setMinimumWidth(maxTabWidth)
            
            if self.tabWidget.count() == 0:
                if Config.debug:
                    Logic.logMessage("DEBUG", "populateDetails: No tabs created for multiTypes")
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"populateDetails: Created {self.tabWidget.count()} tabs for multiTypes, min width {maxTabWidth}")
            
            # Initial resize to first tab
            self.resizeToCurrentTab(0)
        else:
            # Single-type: Use original table (no tabs)
            if hasattr(self, 'tabWidget') and self.tabWidget:
                self.tabWidget.hide()
                self.detailsTable.show()
            
            if queryType == "overlay":
                self.populateOverlay(timestampStr, response)
            elif queryType == "headerNormal":
                self.populateHeaderNormal(response)
            elif queryType == "headerDelta":
                self.populateHeaderDelta(response)
            elif queryType == "headerOverlay":
                self.populateHeaderOverlay(response)
            elif queryType in metadataHandlers:
                metadataHandlers[queryType](timestampStr, response, interval=interval)
            else:
                Logic.logMessage("WARN", f"Unknown queryType: {queryType} - No details populated")
                return
        
            # Resize table to contents
            self.detailsTable.resizeColumnsToContents()
            self.detailsTable.resizeRowsToContents()
            
            # Manually calculate and set window size to fit content exactly (no scroll bars)
            self.detailsTable.setMinimumHeight(0) # Prevent over-allocation for empty space
            self.detailsTable.verticalScrollBar().setVisible(False) # Suppress any latent scrollbar
            width = sum(self.detailsTable.columnWidth(i) for i in range(self.detailsTable.columnCount())) + self.detailsTable.verticalHeader().width() + self.detailsTable.frameWidth() * 2 + 30 # Tighter padding for borders/margins
            height = sum(self.detailsTable.rowHeight(i) for i in range(self.detailsTable.rowCount())) + self.detailsTable.horizontalHeader().height() + self.lblTitle.height() + self.detailsTable.frameWidth() * 2 + 30 # Reduced buffer to avoid extra row
            self.resize(width, height)
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Populated {self.detailsTable.rowCount()} rows (or tabs)")
    
    def populateOverlay(self, timestampStr, data, table=None):
        """Internal method to populate for overlay cell data."""
        if table is None:
            table = self.detailsTable # Fallback to main table
        
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
        self.addRow("Primary Info", data.get('dataId1', 'N/A'), table=table)
        self.addRow("Primary Value", str(primaryVal), table=table)
        self.addRow("Primary Database", data.get('db1', 'N/A'), table=table)
        self.addRow("Secondary Info", data.get('dataId2', 'N/A'), table=table)
        self.addRow("Secondary Value", str(secondaryVal), table=table)
        self.addRow("Secondary Database", data.get('db2', 'N/A'), table=table)
        self.addRow("Delta", str(delta), table=table)
    
    def populateHeaderNormal(self, meta):
        """Internal method to populate for normal header metadata."""
        
        # Add query info
        queryInfos = meta.get('queryInfos', 'N/A')
        queryStr = queryInfos[0] if isinstance(queryInfos, list) else str(queryInfos)
        self.addRow("Query Info", queryStr)
        
        # Add stats (computed as in original)
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def populateHeaderDelta(self, meta):
        """Internal method to populate for delta header metadata."""
        
        # Add details
        self.addRow("Calculation", f"{meta.get('dataIds', ['N/A', 'N/A'])[0]} - {meta.get('dataIds', ['N/A', 'N/A'])[1]}")
        
        # Add stats
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def populateHeaderOverlay(self, meta):
        """Internal method to populate for overlay header metadata."""
        
        # Add primary/secondary
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
    
    def populateAquarius(self, timestampStr, response, table=None):
        """Internal method to populate for AQUARIUS response."""
        if table is None:
            table = self.detailsTable
        
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
        self.addRow("Parameter", f"{response.get('Parameter', 'N/A')}, {response.get('Unit', 'N/A')}", response.get('Label', 'N/A'), table=table)
        
        # 2. Timestamp/Value (point-level, respect Config.rawData for formatting)
        value = point['Value']
        numeric = value.get('Numeric', 'N/A')
        display = Logic.valuePrecision(numeric) if not Config.rawData and numeric != 'N/A' else str(numeric)
        self.addRow("Value", display, point.get('Timestamp', 'N/A'), table=table)
        
        # 3-9: Arrays with time-range filtering
        self.addArrayRows("Approval", response.get('Approvals', []), timestamp, 
                        lambda item: f"Level: {item.get('ApprovalLevel', 'N/A')} ({item.get('LevelDescription', 'N/A')}) \nUser: {item.get('User', 'N/A')} \nApplied: {item.get('DateAppliedUtc', 'N/A')} \nComment: {item.get('Comment', 'N/A')}", table=table)
        
        self.addArrayRows("Qualifier", response.get('Qualifiers', []), timestamp, 
                        lambda item: f"Identifier: {item.get('Identifier', 'N/A')} | User: {item.get('User', 'N/A')} | Applied: {item.get('DateApplied', 'N/A')}", table=table)
        
        self.addArrayRows("Method", response.get('Methods', []), timestamp, 
                        lambda item: f"Code: {item.get('MethodCode', 'N/A')}", table=table)
        
        self.addArrayRows("Grade", response.get('Grades', []), timestamp, 
                        lambda item: f"Code: {item.get('GradeCode', 'N/A')}", table=table)
        
        self.addArrayRows("Gap Tolerance", response.get('GapTolerances', []), timestamp, 
                        lambda item: f"Tolerance (min): {item.get('ToleranceInMinutes', 'N/A')}", table=table)
        
        self.addArrayRows("Interpolation Type", response.get('InterpolationTypes', []), timestamp, 
                        lambda item: f"Type: {item.get('Type', 'N/A')}", table=table)
        
        self.addArrayRows("Note", response.get('Notes', []), timestamp, 
                        lambda item: f"Text: {item.get('NoteText', 'N/A')}", table=table)
        
    def populateUSBR(self, timestampStr, response, interval, table=None):
        """Internal method to populate for USBR metadata (list of merged dicts)."""
        if table is None:
            table = self.detailsTable
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
        matchField = 'End Date/Time' if interval == 'HOUR' and Config.periodOffset else 'Start Date/Time'
        
        # Filter row by exact match on matchField
        matchingRow = next((row for row in response if row.get(matchField) == matchKey), None)
        
        if not matchingRow:
            Logic.logMessage("WARN", f"No matching metadata for {matchKey} in USBR response")
            self.addRow("Note", "No metadata for this timestamp", table=table)
            return
        
        # Defined tag order (per user spec)
        tags = [
            'SDID', 'Interval', 'Start Date/Time', 'End Date/Time', 'Date/Time Loaded',
            'Interval Value', 'Base Value', 'Validation', 'Overwrite Flag', 'Method',
            'Agency Name', 'Collection System', 'Loading Application', 'Computation', 
            'Computation ID', 'Data Flags'
        ]
        
        # Add rows in order, value as str or '' if missing/None
        for tag in tags:
            value = matchingRow.get(tag)
            valStr = str(value) if value is not None else ''
            self.addRow(tag, valStr, table=table)
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Populated USBR metadata with {len(tags)} tags for {matchKey}")
    
    def populateUSGS(self, timestampStr, response, table=None):
        """Internal method to populate for USGS response (placeholder based on typical structure)."""
        if table is None:
            table = self.detailsTable
        
        # Assuming response is dict with 'value', 'dateTime', 'qualifiers' (list), etc.
        # Parse timestamp for comparisons if needed
        try:
            timestamp = self.parseDateTime(timestampStr)
        except ValueError as e:
            Logic.logMessage("ERROR", f"Failed to parse timestamp {timestampStr}: {e}")
            return
        
        # Find matching point (assuming 'timeSeries' or similar; simplify to direct fields for placeholder)
        value = response.get('value', 'N/A')
        dateTime = response.get('dateTime', 'N/A')
        
        # Add basic rows
        self.addRow("Parameter Code", response.get('parameterCd', 'N/A'), table=table)
        self.addRow("Value", str(value), dateTime, table=table)
        
        # Array for qualifiers (similar to Aquarius)
        self.addArrayRows("Qualifier", response.get('qualifiers', []), timestamp, 
                        lambda item: f"Code: {item.get('code', 'N/A')} | Description: {item.get('description', 'N/A')}", table=table)
        
        if Config.debug:
            Logic.logMessage("DEBUG", "populateUSGS: Populated basic USGS metadata (placeholder)")

    def addRow(self, metaType, details, startTime="", endTime="", table=None):
        """Add a single row to the table (defaults for 2-column modes)."""
        if table is None:
            table = self.detailsTable
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(metaType))
        table.setItem(row, 1, QTableWidgetItem(details))

        if table.columnCount() > 2:
            table.setItem(row, 2, QTableWidgetItem(startTime))
            table.setItem(row, 3, QTableWidgetItem(endTime))

    def addArrayRows(self, metaType, items, timestamp, detailFormatter, table=None):
        """Add rows for array items matching the timestamp range."""
        if table is None:
            table = self.detailsTable
        added = False

        for item in items:
            try:
                start = self.parseDateTime(item.get('StartTime'))
                end = self.parseDateTime(item.get('EndTime'))

                if start <= timestamp <= end:
                    self.addRow(metaType, detailFormatter(item), item.get('StartTime', 'N/A'), item.get('EndTime', 'N/A'), table=table)
                    added = True
            except (ValueError, TypeError) as e:
                Logic.logMessage("WARN", f"Skipping invalid array item in {metaType}: {e}")
        if not added:
            self.addRow(metaType, "N/A", table=table)
    
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
        formatsNoColon = ['%m/%d/%y %H%M00', '%Y-%m-%dT%H%M%S%z', '%Y-%m-%dT%H%M%S', '%Y-%m-%d %H%M%S']

        for fmt in formatsNoColon:
            try:
                dt = datetime.strptime(dtStr, fmt)
                return dt.replace(tzinfo=None) # Return naive datetime for comparison
            except ValueError:
                pass
        raise ValueError(f"Unsupported datetime format: {dtStr}")