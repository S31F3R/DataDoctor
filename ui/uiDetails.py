# uiDetails.py - Details window for displaying cell metadata or overlay info

from PyQt6.QtWidgets import (
    QWidget, QTableWidgetItem, QAbstractItemView, QTabWidget, QVBoxLayout,
    QTableWidget, QSizePolicy, QApplication,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6 import uic
from datetime import datetime
from core import Logic, Config

# Cap visible metadata rows; beyond this, show a themed vertical scrollbar
maxVisibleMetaRows = 16
# Qt QWIDGETSIZE_MAX
maxWidgetSize = 16777215


class CurrentPageTabWidget(QTabWidget):
    """
    Default QTabWidget sizeHint is the MAX of every page — that is why switching
    from a wide Aquarius tab to a narrow USBR tab left the window stuck wide.

    sizeHint / minimumSizeHint follow the *current* page (and its table) only.
    """

    def sizeHint(self):
        return self._currentContentHint()

    def minimumSizeHint(self):
        return self._currentContentHint()

    def _currentContentHint(self):
        bar = self.tabBar()
        barH = bar.sizeHint().height() if bar else 24
        barW = bar.sizeHint().width() if bar else 0
        page = self.currentWidget()
        if page is None:
            return QSize(max(280, barW + 16), barH + 80)

        table = page.findChild(QTableWidget)
        if table is not None:
            # Measure without permanently leaving stretch off
            header = table.horizontalHeader()
            prevStretch = header.stretchLastSection()
            header.setStretchLastSection(False)
            header.setMinimumSectionSize(0)
            table.resizeColumnsToContents()
            table.resizeRowsToContents()
            header.setStretchLastSection(prevStretch)

            rowCount = table.rowCount()
            visible = min(rowCount, maxVisibleMetaRows) if rowCount else 0
            needsScroll = rowCount > maxVisibleMetaRows
            colsW = sum(table.columnWidth(i) for i in range(table.columnCount()))
            rowsH = sum(table.rowHeight(i) for i in range(visible)) if visible else 0
            tw = (
                colsW
                + table.frameWidth() * 2
                + 24
                + (table.verticalScrollBar().sizeHint().width() + 4 if needsScroll else 0)
            )
            th = (
                rowsH
                + header.height()
                + table.frameWidth() * 2
                + 8
            )
            return QSize(max(tw, barW + 16, 200), th + barH + 8)

        ph = page.sizeHint()
        return QSize(max(ph.width(), barW + 16, 200), ph.height() + barH + 8)


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
        
        # Title must stay a single compact line — never expand into huge empty band
        if hasattr(self, 'lblTitle') and self.lblTitle is not None:
            self.lblTitle.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
            )
            self.lblTitle.setWordWrap(False)
            self.lblTitle.setMaximumHeight(36)
            self.lblTitle.setMinimumHeight(0)

        # Initialize table with no rows yet (column count set dynamically in populate)
        self.configureMetaTable(self.detailsTable, twoColumn=True)
        
        # Zero main layout margins for single-panel view
        layout = self.layout()

        if layout:
            layout.setContentsMargins(4, 2, 4, 4)
            layout.setSpacing(2)
            layout.setSizeConstraint(layout.SizeConstraint.SetNoConstraint)
            # Stretch only the content row (table / tabs), not the title
            if layout.count() >= 2:
                layout.setStretch(0, 0)
                layout.setStretch(1, 1)
        
        # Connect tab change for resize if tabWidget created later
        # NOTE: empty QTabWidget is falsy in PyQt6 — use is not None
        if getattr(self, 'tabWidget', None) is not None:
            self.tabWidget.currentChanged.connect(self.resizeToCurrentTab)
        
        if Config.debug:
            Logic.logMessage("DEBUG", "uiDetails initialized")

    def configureMetaTable(self, table, twoColumn=True):
        """Apply shared details-table settings and a fixed column layout."""
        table.setSortingEnabled(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        # Expanding + stretch last section fills the client area (no dead right pad)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.clampTableColumns(table, twoColumn=twoColumn)
        table.horizontalHeader().setStretchLastSection(True)

    def clampTableColumns(self, table, twoColumn=True):
        """Force 2- or 4-column layout so ghost columns cannot bleed across tabs."""
        if twoColumn:
            if table.columnCount() != 2:
                table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Type", "Value"])
        else:
            if table.columnCount() != 4:
                table.setColumnCount(4)
            table.setHorizontalHeaderLabels(["Metadata Type", "Details", "Start Time", "End Time"])

    def _measureTable(self, table):
        """
        Content size of a details table (stretch off while measuring).
        Returns (contentWidth, contentHeight, needsScroll).
        """
        header = table.horizontalHeader()
        prevStretch = header.stretchLastSection()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(0)
        for c in range(table.columnCount()):
            # Reset so resizeColumnsToContents is not stuck on a prior wide measure
            table.setColumnWidth(c, 10)
        table.resizeColumnsToContents()
        table.resizeRowsToContents()

        rowCount = table.rowCount()
        visibleRows = min(rowCount, maxVisibleMetaRows) if rowCount else 0
        needsScroll = rowCount > maxVisibleMetaRows

        if needsScroll:
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        contentWidth = (
            sum(table.columnWidth(i) for i in range(table.columnCount()))
            + table.frameWidth() * 2
            + 28
        )
        if needsScroll:
            contentWidth += table.verticalScrollBar().sizeHint().width() + 6

        rowsHeight = sum(table.rowHeight(i) for i in range(visibleRows)) if visibleRows else 0
        contentHeight = (
            rowsHeight
            + header.height()
            + table.frameWidth() * 2
            + 8
        )
        # Restore stretch so columns fill the window (no empty strip on the right)
        header.setStretchLastSection(prevStretch if prevStretch else True)
        return contentWidth, contentHeight, needsScroll

    def sizeWindowToTable(self, table, extraHeight=0, minWidthExtra=0):
        """
        Size the window to content, capped at maxVisibleMetaRows.
        Extra rows get a vertical scrollbar (app stylesheet themes it).

        Shrinks when switching from a wide tab (Aquarius 4-col) to a narrow one
        (USBR 2-col). Does not use setFixedSize (that left a huge empty title band).
        """
        if table is None:
            return

        # Unlock any prior fixed/max constraints from older sizing code
        self.setMinimumSize(0, 0)
        self.setMaximumSize(maxWidgetSize, maxWidgetSize)

        contentWidth, contentHeight, needsScroll = self._measureTable(table)
        contentWidth += minWidthExtra

        if (
            getattr(self, 'tabWidget', None) is not None
            and self.tabWidget.isVisible()
        ):
            tabBar = self.tabWidget.tabBar()
            # Only need enough width for tab *labels* of the bar, not max page size
            tabBarWidth = (tabBar.sizeHint().width() + 16) if tabBar else 0
            contentWidth = max(contentWidth, tabBarWidth)

        titleH = 22
        if hasattr(self, 'lblTitle') and self.lblTitle is not None:
            # Use sizeHint, not current height (current height can be inflated)
            # Width must include the title so long series labels are not clipped
            self.lblTitle.setWordWrap(False)
            titleHint = self.lblTitle.sizeHint()
            titleH = max(titleHint.height(), 18)
            # Font metrics are more reliable than sizeHint width for QLabel
            try:
                from PyQt6.QtGui import QFontMetrics
                fm = QFontMetrics(self.lblTitle.font())
                titleW = fm.horizontalAdvance(self.lblTitle.text() or '') + 24
            except Exception:
                titleW = max(titleHint.width(), 0) + 24
            contentWidth = max(contentWidth, titleW)
            self.lblTitle.setMaximumHeight(titleH + 8)
            self.lblTitle.setMinimumHeight(0)

        # Frame / margins / spacing
        chrome = 16
        targetW = max(int(contentWidth) + 8, 280)
        targetH = max(int(contentHeight + titleH + extraHeight + chrome), 120)

        # Cap max to target so layout min-size from other tabs cannot block shrink,
        # then clear max after the geometry is applied.
        self.setMaximumSize(targetW, targetH)
        self.resize(targetW, targetH)
        QApplication.processEvents()
        # Keep user free to grow; size stays until next tab switch
        self.setMaximumSize(maxWidgetSize, maxWidgetSize)
        # Re-apply size once more after max unlock (some styles re-expand once)
        if self.width() > targetW + 4 or self.height() > targetH + 4:
            self.resize(targetW, targetH)

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"sizeWindowToTable: rows={table.rowCount()}, scroll={needsScroll}, "
                f"size={self.width()}x{self.height()} (target {targetW}x{targetH})"
            )

    def resizeToCurrentTab(self, index):
        """Resize window to fit current tab's content (max 16 rows + scrollbar)."""
        if getattr(self, 'tabWidget', None) is None:
            return
        
        currentTab = self.tabWidget.widget(index)
        if currentTab is None:
            return
        
        tabTable = currentTab.findChild(QTableWidget)
        if tabTable is None:
            return

        # Re-assert column layout for this tab (prevents bleed across tab switches)
        colCount = tabTable.columnCount()
        header0 = tabTable.horizontalHeaderItem(0)
        if colCount > 2 and header0 is not None and header0.text() == "Type":
            tabTable.setColumnCount(2)
            tabTable.setHorizontalHeaderLabels(["Type", "Value"])
        elif colCount == 2:
            tabTable.setHorizontalHeaderLabels(["Type", "Value"])
        elif colCount >= 4:
            tabTable.setHorizontalHeaderLabels(
                ["Metadata Type", "Details", "Start Time", "End Time"]
            )

        extra = 0
        if self.tabWidget.tabBar() is not None:
            extra = self.tabWidget.tabBar().sizeHint().height() + 12
        self.sizeWindowToTable(tabTable, extraHeight=extra)

        # One deferred pass after Qt finishes showing the new page
        QTimer.singleShot(0, lambda idx=index: self._deferredResizeTab(idx))

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Resized to current tab {index}: {self.width()}x{self.height()}",
            )

    def _deferredResizeTab(self, index):
        """Second measure after the tab page is fully shown."""
        if getattr(self, 'tabWidget', None) is None:
            return
        if self.tabWidget.currentIndex() != index:
            return
        currentTab = self.tabWidget.widget(index)
        if currentTab is None:
            return
        tabTable = currentTab.findChild(QTableWidget)
        if tabTable is None:
            return
        extra = 0
        if self.tabWidget.tabBar() is not None:
            extra = self.tabWidget.tabBar().sizeHint().height() + 12
        self.sizeWindowToTable(tabTable, extraHeight=extra)

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
        try:
            if Config.debug:
                Logic.logMessage("DEBUG", f"Populating details for queryType: {queryType}, series: {seriesLabel}, timestamp: {timestampStr}, multiTypes={multiTypes}")

            # Set title using first line of seriesLabel only (no timestamp for headers)
            titleLabel = seriesLabel.split('\n')[0] if '\n' in seriesLabel else seriesLabel
            if timestampStr:
                self.lblTitle.setText(f" Details for {timestampStr} - {titleLabel}")
            else:
                self.lblTitle.setText(f" Details for {titleLabel}")

            # Clear existing rows and set columns dynamically
            self.detailsTable.setRowCount(0)
            twoColTypes = {"overlay", "headerNormal", "headerDelta", "headerOverlay", "USBR", "USGS"}
            self.configureMetaTable(self.detailsTable, twoColumn=(queryType in twoColTypes))

            # Handler dictionary for database-specific metadata (easy to add USGS)
            metadataHandlers = {
                "AQUARIUS": lambda ts, resp, interval=None, table=None: self.populateAquarius(ts, resp, table=table), # Ignore interval
                "USGS": lambda ts, resp, interval=None, table=None: self.populateUSGS(ts, resp, table=table), # Ignore interval
                "USBR": lambda ts, resp, interval=None, table=None: self.populateUSBR(ts, resp, interval, table=table),
            }

            # If multiTypes provided (e.g., for overlay cell), use tabs
            if multiTypes and len(multiTypes) > 1:
                # Create current-page-sized tab widget if not exists (or replace plain QTabWidget)
                # Empty QTabWidget is falsy — never use bare `if self.tabWidget`
                existingTabs = getattr(self, 'tabWidget', None)
                needNewTabs = (
                    existingTabs is None
                    or not isinstance(existingTabs, CurrentPageTabWidget)
                )
                if needNewTabs:
                    layout = self.layout()
                    if existingTabs is not None and layout is not None:
                        layout.removeWidget(existingTabs)
                        existingTabs.deleteLater()
                    self.tabWidget = CurrentPageTabWidget(self)
                    self.tabWidget.setSizePolicy(
                        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                    )
                    if layout:
                        layout.addWidget(self.tabWidget)
                        # Title stretch 0, tabs stretch 1
                        if layout.count() >= 2:
                            layout.setStretch(0, 0)
                            layout.setStretch(layout.count() - 1, 1)
                    self.tabWidget.currentChanged.connect(self.resizeToCurrentTab)

                self.detailsTable.hide()  # Hide original table, use per-tab tables
                self.detailsTable.setMaximumHeight(0)  # prevent hidden table from eating layout space
                self.tabWidget.show()
                self.tabWidget.setMaximumHeight(maxWidgetSize)

                # Clear existing tabs (delete old page widgets so tables don't leak)
                while self.tabWidget.count() > 0:
                    oldPage = self.tabWidget.widget(0)
                    self.tabWidget.removeTab(0)
                    if oldPage is not None:
                        oldPage.deleteLater()

                # Add tabs in order (Overlay first, then DBs)
                for i, t in enumerate(multiTypes):
                    # Normalize t for handlers (e.g., 'USBR-LCHDB' -> 'USBR', 'USGS-NWIS' -> 'USGS')
                    normT = t.split('-')[0] if '-' in t else t
                    tabResp = responsesList[i] if responsesList and i < len(responsesList) else {}
                    tabIntvl = intervalsList[i] if intervalsList and i < len(intervalsList) else 'HOUR'
                    page = QWidget()
                    tabLayout = QVBoxLayout(page)
                    tabLayout.setContentsMargins(0, 0, 0, 0)
                    tabLayout.setSpacing(0)
                    tabTable = QTableWidget(page)
                    # USBR/USGS/overlay = 2 cols; Aquarius (and unknown) = 4 cols
                    twoCol = normT in ("overlay", "USBR", "USGS")
                    self.configureMetaTable(tabTable, twoColumn=twoCol)

                    # Populate per type
                    if normT == 'overlay':
                        self.populateOverlay(timestampStr, tabResp, table=tabTable)
                    elif normT in metadataHandlers:
                        metadataHandlers[normT](
                            timestampStr, tabResp, interval=tabIntvl, table=tabTable
                        )
                    else:
                        Logic.logMessage(
                            "WARN",
                            f"Unknown type {t} (normalized {normT}) in multiTypes - Skipped tab",
                        )
                        continue

                    # Clamp ghost columns after populate (Qt setItem can grow columnCount)
                    self.clampTableColumns(tabTable, twoColumn=twoCol)
                    tabLayout.addWidget(tabTable)

                    # Tab name: Uppercase abbreviations/suffixes, capitalize "Details"
                    if t.upper() in ['USBR', 'USGS'] or '-' in t:
                        tabName = t.upper() + " Details"
                    else:
                        tabName = t.capitalize() + " Details"
                    if i > 0:  # For DB tabs
                        if len(multiTypes) > 2 and multiTypes[1] == multiTypes[2]:
                            tabName = (
                                t.upper()
                                + (" (Primary)" if i == 1 else " (Secondary)")
                                + " Details"
                            )
                    self.tabWidget.addTab(page, tabName)

                if self.tabWidget.count() == 0:
                    if Config.debug:
                        Logic.logMessage("DEBUG", "populateDetails: No tabs created for multiTypes")

                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        f"populateDetails: Created {self.tabWidget.count()} tabs for multiTypes",
                    )

                self.tabWidget.setCurrentIndex(0)
                self.resizeToCurrentTab(0)
            else:
                # Single-type: Use original table (no tabs)
                if getattr(self, 'tabWidget', None) is not None:
                    self.tabWidget.hide()
                    self.tabWidget.setMaximumHeight(0)
                self.detailsTable.setMaximumHeight(maxWidgetSize)
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

                # Clamp ghost columns then size (max 16 rows + scrollbar)
                self.clampTableColumns(self.detailsTable, twoColumn=(queryType in twoColTypes))
                self.detailsTable.setMinimumHeight(0)
                self.sizeWindowToTable(self.detailsTable)
                QTimer.singleShot(0, lambda: self.sizeWindowToTable(self.detailsTable))

            if Config.debug:
                Logic.logMessage("DEBUG", f"Populated {self.detailsTable.rowCount()} rows (or tabs)")

        except Exception as e:
            Logic.logException(f"populateDetails failed for queryType={queryType!r}", e)
            try:
                self.lblTitle.setText(f" Details error: {e}")
            except Exception:
                pass

    def populateOverlay(self, timestampStr, data, table=None):
        """Internal method to populate for overlay cell data."""
        if table is None:
            table = self.detailsTable # Fallback to main table
        
        # Handle missing keys safely
        primaryVal = data.get('primaryVal', 'N/A') if data.get('primaryVal') is not None else 'N/A'
        secondaryVal = data.get('secondaryVal', 'N/A') if data.get('secondaryVal') is not None else 'N/A'
        delta = data.get('delta', 'N/A') if data.get('delta') is not None else 'N/A'
        
        # valuePrecision handles rawData (fixed-point, no scientific notation)
        try:
            if primaryVal != 'N/A':
                primaryVal = Logic.valuePrecision(float(primaryVal))
            if secondaryVal != 'N/A':
                secondaryVal = Logic.valuePrecision(float(secondaryVal))
            if delta != 'N/A':
                delta = Logic.valuePrecision(float(delta))
        except (ValueError, TypeError):
            pass # Keep as string if not numeric
        
        # Add rows for overlay specifics (broken out per user request)
        self.addRow("Primary Database", data.get('db1', 'N/A'), table=table)
        self.addRow("Primary Info", data.get('dataId1', 'N/A'), table=table)
        self.addRow("Primary Value", str(primaryVal), table=table)
        self.addRow("Secondary Database", data.get('db2', 'N/A'), table=table)
        self.addRow("Secondary Info", data.get('dataId2', 'N/A'), table=table)
        self.addRow("Secondary Value", str(secondaryVal), table=table)        
        self.addRow("Delta", str(delta), table=table)
    
    def populateHeaderNormal(self, meta):
        """Internal method to populate for normal header metadata."""
        
        # Add query info
        queryInfos = meta.get('queryInfos', 'N/A')
        queryStr = queryInfos[0] if isinstance(queryInfos, list) else str(queryInfos)
        self.addRow("Query Info", queryStr)
        
        # Add stats (with timestamps for max/min)
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def populateHeaderDelta(self, meta):
        """Internal method to populate for delta header metadata."""
        
        # Add details
        self.addRow("Calculation", f"{meta.get('dataIds', ['N/A', 'N/A'])[0]} - {meta.get('dataIds', ['N/A', 'N/A'])[1]}")
        
        # Add stats (with timestamps for max/min)
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def populateHeaderOverlay(self, meta):
        """Internal method to populate for overlay header metadata."""
        
        # Add primary/secondary
        self.addRow("Primary", meta.get('queryInfos', ['N/A', 'N/A'])[0])
        self.addRow("Secondary", meta.get('queryInfos', ['N/A', 'N/A'])[1])
        
        # Add stats (with timestamps for max/min)
        maxStr, minStr, meanStr = self.computeColumnStats(meta['col'])
        self.addRow("Max", maxStr)
        self.addRow("Min", minStr)
        self.addRow("Mean", meanStr)
    
    def computeColumnStats(self, col):
        """Compute stats for a column; max/min include the row timestamp."""
        values = []  # list of (float, timestampStr)

        for row in range(self.parent().mainTable.rowCount()):
            item = self.parent().mainTable.item(row, col)

            if item and item.text().strip():
                try:
                    val = float(item.text())
                    tsItem = self.parent().mainTable.verticalHeaderItem(row)
                    ts = tsItem.text() if tsItem else ''
                    values.append((val, ts))
                except ValueError:
                    pass
        if not values:
            return "N/A", "N/A", "N/A"
        maxPair = max(values, key=lambda x: x[0])
        minPair = min(values, key=lambda x: x[0])
        meanVal = sum(v for v, _ in values) / len(values)
        
        # Use valuePrecision for formatting, handles rawData internally
        maxStr = Logic.valuePrecision(maxPair[0])
        minStr = Logic.valuePrecision(minPair[0])
        meanStr = Logic.valuePrecision(meanVal)
        if maxPair[1]:
            maxStr = f"{maxStr} @ {maxPair[1]}"
        if minPair[1]:
            minStr = f"{minStr} @ {minPair[1]}"
        
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
        
        # 0. Aquarius Label first — Label only (location is not part of this row)
        aqLabel = (response.get('Label') or '').strip() or 'N/A'
        self.addRow("Aquarius Label", aqLabel, table=table)

        # 1. Parameter/Unit (series-level)
        self.addRow("Parameter", f"{response.get('Parameter', 'N/A')}, {response.get('Unit', 'N/A')}", table=table)
        
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
        
        # Convert display timestamp (hour/day/month/year forms) to Oracle meta key
        from core.Query import parseDisplayTimestamp, periodStart
        try:
            tsDate = parseDisplayTimestamp(timestampStr)
            if tsDate is None:
                raise ValueError(f'unparseable timestamp {timestampStr!r}')
            # Meta rows use full Y-m-d H:M:S; match on period for coarser intervals
            matchKey = tsDate.strftime('%Y-%m-%d %H:%M:%S')

            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted timestampStr {timestampStr} to matchKey {matchKey}")
        except (ValueError, TypeError) as e:
            Logic.logMessage("ERROR", f"Failed to convert timestampStr {timestampStr}: {e}")
            return
        
        # Determine match field based on periodOffset (for HOUR)
        matchField = 'End Date/Time' if interval == 'HOUR' and Config.periodOffset else 'Start Date/Time'
        
        # Filter row by exact match, else same interval period (daily/monthly/yearly headers)
        matchingRow = next((row for row in response if row.get(matchField) == matchKey), None)
        if matchingRow is None and interval and str(interval).upper() in (
            'DAY', 'MONTH', 'YEAR', 'WATER YEAR'
        ):
            targetPeriod = periodStart(tsDate, interval)
            for row in response:
                raw = row.get(matchField) or ''
                try:
                    rowDt = datetime.strptime(str(raw), '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if periodStart(rowDt, interval) == targetPeriod:
                    matchingRow = row
                    break
        
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
        """
        Populate USGS metadata (2-column Type/Value, same style as USBR).

        OGC (new time_series_id method):
          response = {
            'kind': 'ogc',
            'seriesMeta': {friendly tags...},
            'points': [{Timestamp, Value, ...}, ...]
          }

        Legacy (numeric methodID): blanks / note only — no rich metadata stored.
        """
        if table is None:
            table = self.detailsTable

        # Series-level tags (OGC time-series-metadata + monitoring-locations)
        seriesTags = [
            "Time Series ID",
            "Monitoring Location ID",
            "Site Name",
            "Site Type",
            "Site Type Code",
            "Agency",
            "Parameter Name",
            "Parameter Description",
            "Parameter Code",
            "Statistic ID",
            "Unit of Measure",
            "Sublocation",
            "Computation",
            "Computation Period",
            "Series Begin (UTC)",
            "Series End (UTC)",
            "State",
            "County",
            "HUC",
            "Time Zone",
            "Uses Daylight Savings",
            "Altitude",
            "Vertical Datum",
            "Data Gap Interval",
            "Web Description",
            "Thresholds",
            "Series Last Modified",
        ]
        # Point-level tags only (do not repeat series-level IDs — those are already in seriesTags)
        pointTags = [
            "Value",
            "Time (UTC)",
            "Unit of Measure",
            "Approval Status",
            "Qualifier",
            "Last Modified",
        ]

        try:
            if not isinstance(response, dict):
                self.addRow("Note", "No USGS metadata available", table=table)
                return

            kind = (response.get("kind") or "").lower()
            seriesMeta = response.get("seriesMeta") or {}
            points = response.get("points") or []

            # Legacy numeric methodID path: keep menu usable, show blanks
            if kind == "legacy" or (not seriesMeta and not points and kind != "ogc"):
                self.addRow("Note", "Metadata not available for legacy USGS method IDs", table=table)
                for tag in seriesTags + pointTags:
                    self.addRow(tag, "", table=table)
                if Config.debug:
                    Logic.logMessage("DEBUG", "populateUSGS: legacy/blank metadata shown")
                return

            # Match point by table vertical-header timestamp
            matchingPoint = None
            if timestampStr and isinstance(points, list):
                matchingPoint = next(
                    (p for p in points if isinstance(p, dict) and p.get("Timestamp") == timestampStr),
                    None,
                )

            for tag in seriesTags:
                value = seriesMeta.get(tag)
                valStr = str(value) if value is not None else ""
                self.addRow(tag, valStr, table=table)

            if matchingPoint:
                for tag in pointTags:
                    value = matchingPoint.get(tag)
                    # Respect rawData for numeric Value display
                    if tag == "Value" and value not in (None, "") and not Config.rawData:
                        try:
                            valStr = Logic.valuePrecision(float(value))
                        except (ValueError, TypeError):
                            valStr = str(value)
                    else:
                        valStr = str(value) if value is not None else ""
                    self.addRow(tag, valStr, table=table)
            else:
                self.addRow("Note", "No point metadata for this timestamp", table=table)
                for tag in pointTags:
                    self.addRow(tag, "", table=table)

            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"populateUSGS: kind={kind}, series fields={len(seriesMeta)}, "
                    f"points={len(points) if isinstance(points, list) else 0}, "
                    f"matched={matchingPoint is not None}",
                )
        except Exception as e:
            Logic.logException("populateUSGS failed", e)
            try:
                self.addRow("Note", f"Failed to load USGS metadata: {e}", table=table)
            except Exception:
                pass

    def addRow(self, metaType, details, startTime="", endTime="", table=None):
        """Add a single row to the table (defaults for 2-column modes).

        Never writes past the current column count — Qt would otherwise grow the
        table and leave ghost columns when switching overlay/HDB/USGS tabs.
        """
        if table is None:
            table = self.detailsTable
        # Ensure at least Type/Value columns exist
        if table.columnCount() < 2:
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Type", "Value"])
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(metaType) if metaType is not None else ''))
        table.setItem(row, 1, QTableWidgetItem(str(details) if details is not None else ''))

        # Only write Start/End when table is intentionally 4-column (Aquarius)
        if table.columnCount() >= 4:
            table.setItem(row, 2, QTableWidgetItem(str(startTime) if startTime is not None else ''))
            table.setItem(row, 3, QTableWidgetItem(str(endTime) if endTime is not None else ''))


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
        formats = [
            '%m/%d/%y %H:%M:00', '%m/%d/%y %H:%M:%S', '%m/%d/%y', '%m/%y', '%Y',
            '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S',
        ]

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