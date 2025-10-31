# DataDoctor.py

import sys
import os
import csv
import json
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QTabWidget, QWidget, QGridLayout, 
                             QSizePolicy, QMessageBox, QFileDialog, QMenu, QLabel, QVBoxLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QFontMetrics, QPixmap
from PyQt6 import uic
from core import Logic, Query, Utils, Config
from ui.uiAbout import uiAbout
from ui.uiDataDictionary import uiDataDictionary
from ui.uiOptions import uiOptions
from ui.uiQuery import uiQuery
from ui.uiQuickLook import uiQuickLook

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
            print("[DEBUG] uiMain initialized with header context menu, Config.rawData: {}".format(Config.rawData))

    def btnPublicQueryPressed(self):
        if self.winQuery:
            self.winQuery.queryType = 'public'
            self.winQuery.show()

            if Config.debug:
                print("[DEBUG] btnPublicQueryPressed: Opened uiQuery as public")

    def btnInternalQueryPressed(self):
        if self.winQuery:
            self.winQuery.queryType = 'internal'
            self.winQuery.show()

            if Config.debug:
                print("[DEBUG] btnInternalQueryPressed: Opened uiQuery as internal")

    def showDataDictionary(self):
        if self.winDataDictionary:
            self.winDataDictionary.show()

            if Config.debug:
                print("[DEBUG] showDataDictionary: Opened data dictionary")

    def btnExportCSVPressed(self):
        if self.mainTable.rowCount() == 0:
            QMessageBox.warning(self, "Export CSV", "No data to export.")
            if Config.debug:
                print("[DEBUG] btnExportCSVPressed: No data to export")
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
                print("[DEBUG] btnExportCSVPressed: Export canceled by user")
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
                print(f"[DEBUG] btnExportCSVPressed: Exported table to {fileName}")
        except Exception as e:
            if Config.debug:
                print(f"[ERROR] btnExportCSVPressed: Failed to export CSV: {e}")
            QMessageBox.warning(self, "Export Error", f"Failed to export CSV: {e}")

    def btnOptionsPressed(self):
        if self.winOptions:
            self.winOptions.exec()

            if Config.debug:
                print("[DEBUG] btnOptionsPressed: Opened options dialog")

    def btnInfoPressed(self):
        if self.winAbout:
            self.winAbout.exec()

            if Config.debug:
                print("[DEBUG] btnInfoPressed: Opened about dialog")

    def btnRefreshPressed(self):
        if self.lastQueryType and self.lastQueryItems:
            Query.executeQuery(self, self.lastQueryItems, self.lastStartDate, self.lastEndDate,
                              self.lastQueryType == 'internal', self.winDataDictionary.mainTable)
            if Config.debug:
                print("[DEBUG] btnRefreshPressed: Refreshed query with last parameters")
        else:
            if Config.debug:
                print("[DEBUG] btnRefreshPressed: No previous query to refresh")

    def btnUndoPressed(self):
        if self.mainTable.rowCount() == 0:
            if Config.debug:
                print("[DEBUG] btnUndoPressed: No data to sort")
            QMessageBox.information(self, "Undo", "No data to sort.")
            return
        Query.timestampSortTable(self.mainTable, self.winDataDictionary.mainTable)

        if Config.debug:
            print("[DEBUG] btnUndoPressed: Called timestampSortTable")

    def showHeaderContextMenu(self, pos):
        """Show context menu for header right-click to display full query info."""
        header = self.mainTable.horizontalHeader()
        col = header.logicalIndexAt(pos)

        if col < 0 or col >= len(self.columnMetadata):
            if Config.debug:
                print("[DEBUG] showHeaderContextMenu: Invalid column {} clicked".format(col))
            return

        meta = self.columnMetadata[col]
        menu = QMenu(self)

        if meta['type'] == 'normal':
            content = meta['queryInfos'][0]
            action = menu.addAction("Show Query Info")
            action.triggered.connect(lambda: self.showMessage("Full Query Info", content))
        elif meta['type'] == 'delta':
            content = f"{meta['dataIds'][0]} - {meta['dataIds'][1]}"
            action = menu.addAction("Show details")
            action.triggered.connect(lambda: self.showMessage("Details", content))
        elif meta['type'] == 'overlay':
            content = f"{meta['queryInfos'][0]}\n{meta['queryInfos'][1]}"
            action = menu.addAction("Show details")
            action.triggered.connect(lambda: self.showMessage("Details", content))

        menu.exec(header.mapToGlobal(pos))

        if Config.debug:
            print("[DEBUG] showHeaderContextMenu: Displayed menu for column {}, type {}".format(col, meta['type']))

    def showCellContextMenu(self, pos):
        """Show context menu for cell right-click in overlay columns."""
        row = self.mainTable.rowAt(pos.y())
        col = self.mainTable.columnAt(pos.x())

        if row < 0 or col < 0:
            return

        if col >= len(self.columnMetadata) or self.columnMetadata[col].get('type') != 'overlay':
            return

        menu = QMenu(self)
        action = menu.addAction("Show details")
        action.triggered.connect(lambda: self.showOverlayCellDetails(row, col))
        menu.exec(self.mainTable.viewport().mapToGlobal(pos))

        if Config.debug:
            print("[DEBUG] showCellContextMenu: Displayed menu for cell ({}, {})".format(row, col))

    def onTabCloseRequested(self, index):
        self.tabWidget.removeTab(index)

        if Config.debug:
            print(f"[DEBUG] onTabCloseRequested: Closed tab at index {index}")

    def showMessage(self, title, content):
        """Display QMessageBox with given title and content, auto-sized without word-wrap."""
        msgBox = QMessageBox(self)
        msgBox.setWindowTitle(title)
        pixmap = QPixmap(Logic.resourcePath('ui/icons/Info.png'))
        pixmap = pixmap.scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio)
        msgBox.setIconPixmap(pixmap)
        label = QLabel(content)
        label.setWordWrap(False) # Disable word-wrap
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse) # Allow selection
        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.setContentsMargins(0, 0, 0, 0)
        msgWidget = QWidget()
        msgWidget.setLayout(layout)
        msgBox.layout().addWidget(msgWidget, 1, 0, 1, msgBox.layout().columnCount())
        msgBox.layout().setContentsMargins(10, 5, 10, 5)
        msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)

        # Auto-size width to fit longest line
        fontMetrics = QFontMetrics(label.font())
        lines = content.split('\n')
        maxWidth = max(fontMetrics.horizontalAdvance(line) for line in lines) + 40 # Padding
        msgBox.setFixedWidth(min(maxWidth, QApplication.primaryScreen().availableGeometry().width() - 100)) # Cap to screen
        msgBox.exec()
        if Config.debug:
            print("[DEBUG] showMessage: Showed {}: {}".format(title, content))

    def showOverlayCellDetails(self, row, col):
        """Display details for overlay cell."""
        item = self.mainTable.item(row, col)

        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)

        if not data:
            return
        
        # Set blank logic
        primaryVal = data['primaryVal'] if data['primaryVal'] else "NDA!"
        secondaryVal = data['secondaryVal'] if data['secondaryVal'] else "NDA!"
        delta = data['delta'] if data['delta'] else "N/A"

        # Build message
        msg = f"{data['dataId1']} value: {primaryVal}\n"
        msg += f"{data['dataId2']} value: {secondaryVal}\n"
        msg += f"{data['dataId1']} database: {data['db1']}\n"
        msg += f"{data['dataId2']} database: {data['db2']}\n"
        msg += f"Delta: {delta}"

        self.showMessage("Cell Details", msg)

        if Config.debug:
            print("[DEBUG] showOverlayCellDetails: Showed details for cell ({}, {})".format(row, col))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("Data Doctor")

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
    
    # Start application
    sys.exit(app.exec())