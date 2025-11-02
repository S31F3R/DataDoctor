# DataDoctor.py

import sys
import os
import csv
import json
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QTabWidget, QWidget, QGridLayout, 
                             QSizePolicy, QMessageBox, QFileDialog, QMenu, QLabel, QVBoxLayout)
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPalette, QFontMetrics, QPixmap
from PyQt6 import uic
from core import Logic, Query, Utils, Config
from ui.uiAbout import uiAbout
from ui.uiDataDictionary import uiDataDictionary
from ui.uiOptions import uiOptions
from ui.uiQuery import uiQuery
from ui.uiQuickLook import uiQuickLook
from ui.uiDetails import uiDetails

class uiMain(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(Logic.resourcePath('ui/winMain.ui'), self)             

        # Define controls
        self.btnPublicQuery = self.findChild(QPushButton, 'btnPublicQuery')
        self.mainTable = self.findChild(QTableWidget, 'mainTable')
        self.btnDataDictionary = self.findChild(QPushButton, 'btnDataDictionary')
        self.btnExportCSV = self.findChild(QPushButton, 'btnExportCSV')
        self.btnOptions = self.findChild(QPushButton, 'btnOptions')
        self.btnInfo = self.findChild(QPushButton, 'btnInfo')
        self.btnInternalQuery = self.findChild(QPushButton, 'btnInternalQuery')
        self.btnRefresh = self.findChild(QPushButton, 'btnRefresh')
        self.btnUndo = self.findChild(QPushButton, 'btnUndo')
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
        self.tabMain = self.findChild(QWidget, 'tabMain')
        self.lastQueryType = None
        self.lastQueryItems = []
        self.lastStartDate = None
        self.lastEndDate = None
        self.columnMetadata = []
        self.seriesResponses = {}  # Dict to store {seriesLabel: response_dict} post-query
        self.currentQueryType = ""  # str: "AQUARIUS", etc., set post-query

        # Set button style
        for btn in [self.btnPublicQuery, self.btnDataDictionary, self.btnExportCSV,
                    self.btnOptions, self.btnInfo, self.btnInternalQuery,
                    self.btnUndo, self.btnRefresh]:
            if btn:
                Utils.buttonStyle(btn)

        # Set up layout
        centralLayout = self.centralWidget().layout()
        if isinstance(centralLayout, QGridLayout):
            centralLayout.setContentsMargins(0, 0, 0, 0)
            centralLayout.setRowStretch(0, 0)
            centralLayout.setRowStretch(1, 1)
            centralLayout.setColumnStretch(0, 1)

        # Create events
        self.btnPublicQuery.clicked.connect(self.btnPublicQueryPressed)
        self.btnDataDictionary.clicked.connect(self.showDataDictionary)
        self.btnExportCSV.clicked.connect(self.btnExportCSVPressed)
        self.btnOptions.clicked.connect(self.btnOptionsPressed)
        self.btnInfo.clicked.connect(self.btnInfoPressed)
        self.btnInternalQuery.clicked.connect(self.btnInternalQueryPressed)
        self.btnRefresh.clicked.connect(self.btnRefreshPressed)
        self.btnUndo.clicked.connect(self.btnUndoPressed)
        self.mainTable.horizontalHeader().sectionClicked.connect(lambda col: Query.customSortTable(self.mainTable, col, self.winDataDictionary.mainTable))
        self.mainTable.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainTable.horizontalHeader().customContextMenuRequested.connect(self.showHeaderContextMenu)
        self.mainTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainTable.customContextMenuRequested.connect(self.showCellContextMenu)
        self.tabWidget.tabCloseRequested.connect(self.onTabCloseRequested)

        # Ensure tab widget expands
        self.tabWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Set up Data Query tab
        if self.tabMain:
            self.tabMain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            if not self.tabMain.layout():
                layout = QGridLayout(self.tabMain)
                layout.addWidget(self.mainTable)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

        if self.mainTable:
            self.mainTable.setGeometry(0, 0, 0, 0)
            self.mainTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Hide tabs on startup
        if self.tabWidget:
            dataQueryIndex = self.tabWidget.indexOf(self.tabMain)

            if dataQueryIndex != -1:
                self.tabWidget.removeTab(dataQueryIndex)

            sqlTab = self.findChild(QWidget, 'tabSQL')
            sqlIndex = self.tabWidget.indexOf(sqlTab)

            if sqlIndex != -1:
                self.tabWidget.removeTab(sqlIndex)

        # Center window
        Utils.centerWindowToParent(self)

        # Initialize globals
        Utils.reloadGlobals()

        if Config.debug:
            Logic.logMessage("DEBUG", "uiMain initialized with header context menu, Config.rawData: {}".format(Config.rawData))  

    def storeQueryData(self, responses, queryType):
        """Store API responses and query type after successful query."""
        normalizedResponses = {}
        for k, v in responses.items():
            key = str(k).strip()
            if isinstance(v, dict) and 'label' in v:
                v['label'] = v['label'].replace('\n', ' ').replace('\u00a0', ' ')
                v['label'] = ' '.join(v['label'].split()).strip()
            normalizedResponses[key] = v
        
        self.seriesResponses = normalizedResponses
        self.currentQueryType = queryType
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"Stored query data: {len(normalizedResponses)} series, type {queryType}, keys={[repr(k) for k in normalizedResponses.keys()]}")


    def btnPublicQueryPressed(self):
        if self.winQuery:
            self.winQuery.queryType = 'public'
            self.winQuery.show()

            if Config.debug:
                Logic.logMessage("DEBUG", "btnPublicQueryPressed: Opened uiQuery as public")                  

    def btnInternalQueryPressed(self):
        if self.winQuery:
            self.winQuery.queryType = 'internal'
            self.winQuery.show()

            if Config.debug:
                Logic.logMessage("DEBUG", "btnInternalQueryPressed: Opened uiQuery as internal")           

    def showDataDictionary(self):
        if self.winDataDictionary:
            self.winDataDictionary.show()

            if Config.debug:
                Logic.logMessage("DEBUG", "showDataDictionary: Opened data dictionary")        

    def btnExportCSVPressed(self):
        if self.mainTable.rowCount() == 0:
            QMessageBox.warning(self, "Export CSV", "No data to export.")

            if Config.debug:
                Logic.logMessage("DEBUG", "btnExportCSVPressed: No data to export")
            return

        config = Utils.loadConfig()
        lastExportPath = config.get('lastExportPath', os.path.expanduser("~/Documents"))
        lastExportPath = os.path.normpath(os.path.abspath(lastExportPath)) if lastExportPath else os.path.expanduser("~/Documents")
        timestamp = datetime.now().strftime('%Y-%m-%d %H%M%S')
        defaultName = f"{timestamp} Export.csv"
        fileName, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV", os.path.join(lastExportPath, defaultName), "CSV Files (*.csv)"
        )

        if not fileName:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnExportCSVPressed: Export canceled by user")
            return
        try:
            with open(fileName, 'w', newline='', encoding='utf-8-sig') as csvFile:
                writer = csv.writer(csvFile)

                # Write headers
                headers = [self.mainTable.horizontalHeaderItem(c).text() for c in range(self.mainTable.columnCount())]
                writer.writerow(['Timestamp'] + headers)

                # Write data
                for row in range(self.mainTable.rowCount()):
                    rowData = [self.mainTable.verticalHeaderItem(row).text()]

                    for col in range(self.mainTable.columnCount()):
                        item = self.mainTable.item(row, col)
                        rowData.append(item.text() if item else '')
                    writer.writerow(rowData)
            config['lastExportPath'] = os.path.dirname(fileName)

            with open(Utils.getConfigPath(), 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)
            if Config.debug:
                Logic.logMessage("DEBUG", f"btnExportCSVPressed: Exported table to {fileName}")
        except Exception as e:
            Logic.logMessage("ERROR", f"btnExportCSVPressed: Failed to export CSV: {e}")                
            QMessageBox.warning(self, "Export Error", f"Failed to export CSV: {e}")

    def btnOptionsPressed(self):
        if self.winOptions:
            self.winOptions.exec()

            if Config.debug:
                Logic.logMessage("DEBUG", "btnOptionsPressed: Opened options dialog")

    def btnInfoPressed(self):
        if self.winAbout:
            self.winAbout.exec()

            if Config.debug:
                Logic.logMessage("DEBUG", "btnInfoPressed: Opened about dialog")

    def btnRefreshPressed(self):
        if self.lastQueryType and self.lastQueryItems:
            # Retrieve last delta and overlay states from globals, default to False if not set
            deltaChecked = getattr(Config, 'lastDeltaChecked', False)
            overlayChecked = getattr(Config, 'lastOverlayChecked', False)

            if Config.debug:
                Logic.logMessage("DEBUG", f"btnRefreshPressed: Refreshing with deltaChecked={deltaChecked}, overlayChecked={overlayChecked}")
            Query.executeQuery(self, self.lastQueryItems, self.lastStartDate, self.lastEndDate,
                            self.lastQueryType == 'internal', self.winDataDictionary.mainTable,
                            deltaChecked=deltaChecked, overlayChecked=overlayChecked)
            if Config.debug:
                Logic.logMessage("DEBUG", "btnRefreshPressed: Refreshed query with last parameters")
        else:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnRefreshPressed: No previous query to refresh")

    def btnUndoPressed(self):
        if self.mainTable.rowCount() == 0:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUndoPressed: No data to sort")
            QMessageBox.information(self, "Undo", "No data to sort.")
            return
        Query.timestampSortTable(self.mainTable, self.winDataDictionary.mainTable)

        if Config.debug:
            Logic.logMessage("DEBUG", "btnUndoPressed: Called timestampSortTable")

    def showHeaderContextMenu(self, pos):
        """Show context menu for header right-click to display full query info using uiDetails."""
        header = self.mainTable.horizontalHeader()
        col = header.logicalIndexAt(pos)
        if col < 0 or col >= len(self.columnMetadata):
            if Config.debug:
                Logic.logMessage("DEBUG", "showHeaderContextMenu: Invalid column {} clicked".format(col))
            return
        meta = self.columnMetadata[col]
        meta['col'] = col  # Add col for stats computation
        menu = QMenu(self)
        
        if meta['type'] == 'normal':
            action = menu.addAction("Show Query Info")
            action.triggered.connect(lambda: self.showHeaderDetails("header_normal", meta))
        elif meta['type'] == 'delta':
            action = menu.addAction("Show details")
            action.triggered.connect(lambda: self.showHeaderDetails("header_delta", meta))
        elif meta['type'] == 'overlay':
            action = menu.addAction("Show details")
            action.triggered.connect(lambda: self.showHeaderDetails("header_overlay", meta))
        
        menu.exec(header.mapToGlobal(pos))
        if Config.debug:
            Logic.logMessage("DEBUG", "showHeaderContextMenu: Displayed menu for column {}, type {}".format(col, meta['type']))

    def showHeaderDetails(self, queryType, meta):
        """Open uiDetails for header metadata."""
        seriesLabel = self.mainTable.horizontalHeaderItem(meta['col']).text() if self.mainTable.horizontalHeaderItem(meta['col']) else ""
        detailsWin = uiDetails(parent=self)
        detailsWin.populateDetails(queryType, seriesLabel, "", meta)
        detailsWin.show()
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"showHeaderDetails: Opened details for {seriesLabel}")

    def showCellContextMenu(self, pos):
        """Show context menu for cell right-click: Metadata details (internal only, non-overlay) + overlay if applicable."""
        index = self.mainTable.indexAt(pos)
        if not index.isValid():
            return
        
        row = index.row()
        col = index.column()
        
        # Get timestamp and series (from headers)
        timestampStr = self.mainTable.verticalHeaderItem(row).text() if self.mainTable.verticalHeaderItem(row) else ""
        seriesLabel = self.mainTable.horizontalHeaderItem(col).text() if self.mainTable.horizontalHeaderItem(col) else ""
        
        if not timestampStr or not seriesLabel:
            Logic.logMessage("WARN", "Invalid cell: No timestamp or series label")
            return
        
        # Get lookupId from columnMetadata (unique dataID)
        lookupId = self.columnMetadata[col].get('lookupId') if col < len(self.columnMetadata) else None
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"showCellContextMenu: columnMetadata={repr(self.columnMetadata)}, col={col}, lookupId={lookupId!r}")
        
        response = self.seriesResponses.get(lookupId) if lookupId else None
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"showCellContextMenu: seriesLabel={seriesLabel!r}, response type={type(response).__name__ if response else 'None'}, response={repr(response) if response else 'None'}, currentQueryType={self.currentQueryType}, seriesResponses keys={[repr(k) for k in self.seriesResponses.keys()]}")
        
        menu = QMenu(self)
        
        # Add metadata details if internal query, non-overlay, and response is dict (for Aquarius metadata)
        isOverlay = col < len(self.columnMetadata) and self.columnMetadata[col].get('type') == 'overlay'
        if Config.debug:
            Logic.logMessage("DEBUG", f"showCellContextMenu: Condition check - internal={self.currentQueryType == 'internal'}, not overlay={not isOverlay}, response dict={isinstance(response, dict)}")
        if self.currentQueryType == 'internal' and not isOverlay and isinstance(response, dict):
            detailsAction = menu.addAction("Show details")
            detailsAction.triggered.connect(lambda: self.showMetadataDetails(row, col, timestampStr, seriesLabel, response))
            if Config.debug:
                Logic.logMessage("DEBUG", "showCellContextMenu: Added 'Show details' action")
        
        # Add overlay if column is overlay (existing logic, with renamed action)
        if isOverlay:
            overlayAction = menu.addAction("Overlay details")
            overlayAction.triggered.connect(lambda: self.showOverlayCellDetails(row, col))
        
        if menu.actions():  # Only show if actions added
            menu.exec(self.mainTable.viewport().mapToGlobal(pos))
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"showCellContextMenu: Displayed menu for cell ({row}, {col})")
        else:
            if Config.debug:
                Logic.logMessage("DEBUG", f"showCellContextMenu: No actions for cell ({row}, {col})")

    def showMetadataDetails(self, row, col, timestampStr, seriesLabel, response):
        """Open uiDetails for Aquarius metadata."""
        detailsWin = uiDetails(parent=self)
        detailsWin.populateDetails('AQUARIUS', seriesLabel, timestampStr, response)
        detailsWin.show()
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"showMetadataDetails: Opened details for {timestampStr} - {seriesLabel}")

    def onTabCloseRequested(self, index):
        self.tabWidget.removeTab(index)

        if Config.debug:
            Logic.logMessage("DEBUG", f"onTabCloseRequested: Closed tab at index {index}")

    def showOverlayCellDetails(self, row, col):
        """Display details for overlay cell using uiDetails window."""
        item = self.mainTable.item(row, col)
        
        if not item:
            return
        
        data = item.data(Qt.ItemDataRole.UserRole)
        
        if not data:
            return
        
        # Get timestamp and series for title
        timestampStr = self.mainTable.verticalHeaderItem(row).text() if self.mainTable.verticalHeaderItem(row) else ""
        seriesLabel = self.mainTable.horizontalHeaderItem(col).text() if self.mainTable.horizontalHeaderItem(col) else ""
        
        # Open uiDetails with overlay mode
        detailsWin = uiDetails(parent=self)
        detailsWin.populateDetails('overlay', seriesLabel, timestampStr, data)
        detailsWin.show()
        
        if Config.debug:
            Logic.logMessage("DEBUG", f"showOverlayCellDetails: Opened details for cell ({row}, {col})")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("Data Doctor")

    # Init logging early to capture all events
    Logic.initLogging()  

    # Grab system font color and save as global
    Config.systemTextColor = app.palette().color(QPalette.ColorRole.Text)

    # Create instances
    winMain = uiMain()
    winQuery = uiQuery(winMain)
    winDataDictionary = uiDataDictionary(winMain)
    winQuickLook = uiQuickLook(winMain)
    winOptions = uiOptions(winMain)
    winAbout = uiAbout(winMain)
    winMain.winQuery = winQuery
    winMain.winDataDictionary = winDataDictionary
    winMain.winQuickLook = winQuickLook
    winMain.winOptions = winOptions
    winMain.winAbout = winAbout

    # Apply styles and fonts
    Utils.applyStylesAndFonts(app, winMain.mainTable, winQuery.listQueryList)

    # Load data dictionary and quick looks
    Utils.loadDataDictionary(winDataDictionary.mainTable)
    Utils.loadQuickLooks(winQuery.cbQuickLook)

    # Show main window
    winMain.show()

    # Convert legacy quickLooks
    Logic.convertLegacyQuickLooks()
    
    # Start application
    sys.exit(app.exec())