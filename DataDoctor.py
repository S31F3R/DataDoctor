# DataDoctor.py

import sys
import os
import csv
import json
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, QTabWidget, QWidget, QGridLayout, QTableWidgetItem,
                             QSizePolicy, QMessageBox, QFileDialog, QMenu, QComboBox, QPlainTextEdit, QListWidget, QInputDialog,
                             QVBoxLayout, QHBoxLayout, QSplitter, QLabel)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QIcon
from PyQt6 import uic
from core import Logic, Query, Utils, Config
from ui.uiAbout import uiAbout
from ui.uiDataDictionary import uiDataDictionary
from ui.uiOptions import uiOptions
from ui.uiQuery import uiQuery
from ui.uiDetails import uiDetails
from core.Oracle import oracleConnection

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
        self.tabSQL = self.findChild(QWidget, 'tabSQL')
        self.lastQueryType = None
        self.lastQueryItems = []
        self.lastStartDate = None
        self.lastEndDate = None
        self.columnMetadata = []
        self.seriesResponses = {} # Dict to store {seriesLabel: responseDict} post-query
        self.currentQueryType = "" # str: "AQUARIUS", etc., set post-query
        self.btnRunQuery = self.findChild(QPushButton, 'btnRunQuery')
        self.btnSaveSnippet = self.findChild(QPushButton, 'btnSaveSnippet')
        self.cbDatabase = self.findChild(QComboBox, 'cbDatabase')
        self.pteSQL = self.findChild(QPlainTextEdit, 'pteSQL')
        self.listSnippets = self.findChild(QListWidget, 'listSnippets')
        self.sqlTable = self.findChild(QTableWidget, 'sqlTable')
        self.btnDeleteSnippet = self.findChild(QPushButton, 'btnDeleteSnippet')        

        # Map button style
        buttonIcons = [
                        (self.btnPublicQuery, "PublicQuery", 36),
                        (self.btnDataDictionary, "Book", 36),
                        (self.btnExportCSV, "ExportCSV", 36),
                        (self.btnOptions, "Options", 36),
                        (self.btnInfo, "Info", 36),
                        (self.btnInternalQuery, "InternalQuery", 36),
                        (self.btnUndo, "Reset", 36),
                        (self.btnRefresh, "Refresh", 36),
                        (self.btnRunQuery, "Play", 36),
                        (self.btnSaveSnippet, "StarPlus", 36),
                        (self.btnDeleteSnippet, "StarMinus", 36)
                      ]

        # Set button style        
        for btn, iconName, iconSize in buttonIcons:
            if btn:
                Utils.buttonStyle(btn, iconName, iconSize=iconSize)

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
        self.btnRunQuery.clicked.connect(self.runCustomQuery)
        self.btnSaveSnippet.clicked.connect(self.saveSnippet)
        self.listSnippets.doubleClicked.connect(self.loadSnippet)
        self.btnDeleteSnippet.clicked.connect(self.deleteSnippet)            

        # Ensure tab widget expands
        self.tabWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Set up Data Query tab
        self.tabMain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Stop table from stretching last column
        self.sqlTable.horizontalHeader().setStretchLastSection(False)

        if not self.tabMain.layout():
            layout = QGridLayout(self.tabMain)
            layout.addWidget(self.mainTable)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        self.mainTable.setGeometry(0, 0, 0, 0)
        self.mainTable.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Center window
        Utils.centerWindowToParent(self)

        # Initialize globals
        Utils.reloadGlobals()

        # Hide tabs on startup
        sqlTab = self.tabSQL
        sqlIndex = self.tabWidget.indexOf(sqlTab) if sqlTab else -1

        # Store titles after removal (in case .ui changes)
        self.dataQueryTitle = "Data Query"
        self.sqlTitle = "SQL Query Builder"

        # Set up splitters and layout for tabSQL to enable resizing
        if sqlTab:
            self.lblDatabase = self.findChild(QLabel, 'lblDatabase')

            # Top controls layout (horizontal, packed on left)
            topLayout = QHBoxLayout()
            topLayout.setSpacing(0)
            topLayout.addWidget(self.btnRunQuery)
            topLayout.addSpacing(10)
            topLayout.addWidget(self.btnSaveSnippet)
            topLayout.addSpacing(10)
            topLayout.addWidget(self.btnDeleteSnippet)
            topLayout.addSpacing(20)
            topLayout.addWidget(self.lblDatabase)
            topLayout.addSpacing(0)

            # Wrap cbDatabase with spacing above to push it down
            comboWidget = QWidget(sqlTab)
            comboLayout = QVBoxLayout(comboWidget)
            comboLayout.setContentsMargins(0, 0, 0, 0)
            comboLayout.setSpacing(0)
            comboLayout.addSpacing(4)
            comboLayout.addWidget(self.cbDatabase)
            topLayout.addWidget(comboWidget)
            topLayout.addStretch()

            # Vertical splitter for pteSQL (top) and sqlTable (bottom)
            sqlSplitter = QSplitter(Qt.Orientation.Vertical, sqlTab)
            sqlSplitter.setObjectName('sqlSplitter')
            sqlSplitter.addWidget(self.pteSQL)
            sqlSplitter.addWidget(self.sqlTable)            

            # Set initial sizes based on .ui
            sqlSplitter.setSizes([231, 291])

            # Left widget: top layout + sqlSplitter
            leftWidget = QWidget(sqlTab)
            leftLayout = QVBoxLayout(leftWidget)
            leftLayout.setContentsMargins(0, 0, 0, 0)
            leftLayout.addLayout(topLayout)
            leftLayout.addWidget(sqlSplitter)

            # Horizontal splitter for left (editor/table) and right (snippets)
            mainSplitter = QSplitter(Qt.Orientation.Horizontal, sqlTab)
            mainSplitter.setObjectName('mainSplitter')
            mainSplitter.addWidget(leftWidget)
            mainSplitter.addWidget(self.listSnippets)

            # Set initial sizes based on .ui
            mainSplitter.setSizes([1281, 256])

            # Main layout for tabSQL
            if sqlTab.layout():
                oldLayout = sqlTab.layout()

                while oldLayout.count():
                    item = oldLayout.takeAt(0)
                    
                    if item.widget():
                        item.widget().deleteLater()
            mainLayout = QVBoxLayout(sqlTab)
            mainLayout.addWidget(mainSplitter)
            mainLayout.setContentsMargins(0, 0, 0, 0)

            # Load saved splitter sizes from config
            config = Utils.loadConfig()

            if 'sqlVerticalSizes' in config:
                sqlSplitter.setSizes(config['sqlVerticalSizes'])

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Restored sqlVerticalSizes: {config['sqlVerticalSizes']}")
            if 'sqlHorizontalSizes' in config:
                mainSplitter.setSizes(config['sqlHorizontalSizes'])

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Restored sqlHorizontalSizes: {config['sqlHorizontalSizes']}")

            if Config.debug:
                Logic.logMessage("DEBUG", "Set up splitters and layout for tabSQL to handle resizing")

        if sqlIndex != -1:
            self.tabWidget.removeTab(sqlIndex)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Removed tabSQL at index {sqlIndex} on startup")
        else:
            if Config.debug:
                Logic.logMessage("WARN", "tabSQL not found in tabWidget on startup")
        dataQueryIndex = self.tabWidget.indexOf(self.tabMain)

        if dataQueryIndex != -1:
            self.tabWidget.removeTab(dataQueryIndex)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Removed tabMain at index {dataQueryIndex} on startup")
        else:
            if Config.debug:
                Logic.logMessage("WARN", "tabMain not found in tabWidget on startup")

        # Add dummy items to controls. This fixes issues with Qt6 quirks
        self.cbDatabase.addItem("")    
        self.listSnippets.addItem("")        

        # Add back SQL tab if enabled
        if Config.enableSQL:
            self.tabWidget.addTab(sqlTab, self.sqlTitle)
            self.refreshSqlTab()

            if Config.debug:
                Logic.logMessage("DEBUG", "Added tabSQL on startup since enabled and refreshed")  

        if Config.debug:
            Logic.logMessage("DEBUG", "uiMain initialized with header context menu, Config.rawData: {}".format(Config.rawData))

    def closeEvent(self, event):
        """Override closeEvent to save splitter sizes if SQL tab is enabled and present."""
        try:
            sqlTab = self.findChild(QWidget, 'tabSQL')

            if Config.enableSQL and sqlTab and self.tabWidget.indexOf(sqlTab) != -1:
                sqlSplitter = self.findChild(QSplitter, 'sqlSplitter')
                mainSplitter = self.findChild(QSplitter, 'mainSplitter')
                if sqlSplitter is not None and mainSplitter is not None:
                    config = Utils.loadConfig()
                    config['sqlVerticalSizes'] = sqlSplitter.sizes()
                    config['sqlHorizontalSizes'] = mainSplitter.sizes()

                    try:
                        with open(Utils.getConfigPath(), 'w', encoding='utf-8') as configFile:
                            json.dump(config, configFile, indent=2)
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"Saved splitter sizes to config: vertical={config['sqlVerticalSizes']}, horizontal={config['sqlHorizontalSizes']}")
                    except Exception as e:
                        Logic.logException("Failed to save splitter sizes", e)
        except Exception as e:
            Logic.logException("closeEvent failed", e)
        super().closeEvent(event)

    def loadSnippets(self):
        """Load SQL snippets from quickLook/sql into listSnippets."""
        try:
            sqlDir = Utils.getSqlSnippetDir()

            if self.listSnippets:
                self.listSnippets.clear()
                if os.path.isdir(sqlDir):
                    for file in sorted(os.listdir(sqlDir)):
                        if file.endswith(".sql"):
                            self.listSnippets.addItem(file[:-4]) # Add name without .sql
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Loaded {self.listSnippets.count()} SQL snippets")
            else:
                if Config.debug:
                    Logic.logMessage("WARN", "listSnippets not found, skipping loadSnippets")
        except Exception as e:
            Logic.logException("loadSnippets failed", e)

    def saveSnippet(self):
        """Save current pteSQL content as .sql snippet."""
        if not self.pteSQL:
            if Config.debug:
                Logic.logMessage("WARN", "pteSQL not found, skipping saveSnippet")
            return
        sqlText = self.pteSQL.toPlainText().strip()

        if not sqlText:
            QMessageBox.warning(self, "Save Snippet", "No SQL query to save.")

            if Config.debug:
                Logic.logMessage("DEBUG", "saveSnippet: No SQL text to save")
            return
        name, ok = QInputDialog.getText(self, "Save Snippet", "Snippet name:")

        if ok and name:
            sqlDir = Utils.getSqlSnippetDir()
            filePath = os.path.join(sqlDir, f"{name}.sql")

            with open(filePath, 'w', encoding='utf-8') as f:
                f.write(sqlText)
            self.loadSnippets() # Reload list to show new snippet immediately

            if Config.debug:
                Logic.logMessage("DEBUG", f"saveSnippet: Saved snippet {name} to {filePath} and reloaded list")

    def loadSnippet(self, index):
        """Load selected snippet into pteSQL on double-click."""
        if not self.listSnippets or not self.pteSQL:
            if Config.debug:
                Logic.logMessage("WARN", "listSnippets or pteSQL not found, skipping loadSnippet")
            return
        item = self.listSnippets.itemFromIndex(index)
        if item:
            name = item.text()
            sqlDir = Utils.getSqlSnippetDir()
            filePath = os.path.join(sqlDir, f"{name}.sql")

            if os.path.exists(filePath):
                with open(filePath, 'r', encoding='utf-8') as f:
                    sqlText = f.read()
                self.pteSQL.setPlainText(sqlText)

                if Config.debug:
                    Logic.logMessage("DEBUG", f"loadSnippet: Loaded {name} into pteSQL")
            else:
                if Config.debug:
                    Logic.logMessage("WARN", f"loadSnippet: Snippet file not found: {filePath}")

    def deleteSnippet(self):
        """Delete selected snippet file and remove from listSnippets."""
        if not self.listSnippets:
            if Config.debug:
                Logic.logMessage("WARN", "listSnippets not found, skipping deleteSnippet")
            return
        selected = self.listSnippets.currentItem()

        if not selected:
            QMessageBox.warning(self, "Delete Snippet", "No snippet selected.")
            if Config.debug:
                Logic.logMessage("DEBUG", "deleteSnippet: No item selected")
            return

        name = selected.text()
        reply = QMessageBox.question(self, "Delete Snippet", f"Delete '{name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            sqlDir = Utils.getSqlSnippetDir()
            filePath = os.path.join(sqlDir, f"{name}.sql")

            if os.path.exists(filePath):
                os.remove(filePath)
                self.listSnippets.takeItem(self.listSnippets.row(selected))

                if Config.debug:
                    Logic.logMessage("DEBUG", f"deleteSnippet: Deleted {name} from {filePath} and removed from list")
            else:
                if Config.debug:
                    Logic.logMessage("WARN", f"deleteSnippet: File not found: {filePath}")

    def runCustomQuery(self):
        """Run custom SQL from pteSQL and display in sqlTable."""
        if not self.pteSQL or not self.sqlTable:
            if Config.debug:
                Logic.logMessage("WARN", "pteSQL or sqlTable not found, skipping runCustomQuery")
            return
        sqlText = self.pteSQL.toPlainText().strip()

        if not sqlText:
            QMessageBox.warning(self, "Run Query", "No SQL query to run.")
            if Config.debug:
                Logic.logMessage("DEBUG", "runCustomQuery: No SQL text to run")
            return

        db = self.cbDatabase.currentText()
        dsn = db.split('-')[1].lower() if '-' in db else db.lower() # e.g., 'USBR-LCHDB' -> 'lchdb'

        if Config.debug:
            Logic.logMessage("DEBUG", f"runCustomQuery: Using DSN {dsn} for query")

        try:
            conn = oracleConnection(dsn)
            conn.connect()
            results = conn.executeCustomQuery(sqlText)
            conn.close()

            if not results:
                QMessageBox.information(self, "Query Result", "No results returned.")
                if Config.debug:
                    Logic.logMessage("DEBUG", "runCustomQuery: No results from query")
                return

            # Build sqlTable from results (list of dicts)
            columns = list(results[0].keys()) if results else []
            self.sqlTable.setColumnCount(len(columns))
            self.sqlTable.setHorizontalHeaderLabels(columns)
            self.sqlTable.setRowCount(len(results))
            self.sqlTable.horizontalHeader().setStretchLastSection(False)

            for row, res in enumerate(results):
                for col, key in enumerate(columns):
                    item = QTableWidgetItem(str(res.get(key, '')))
                    self.sqlTable.setItem(row, col, item)
            self.sqlTable.resizeColumnsToContents()

            if Config.debug:
                Logic.logMessage("DEBUG", f"runCustomQuery: Populated sqlTable with {len(results)} rows, {len(columns)} columns")
        except Exception as e:
            Logic.logException("runCustomQuery: Failed to execute", e)
            try:
                from core.Oracle import OracleAuthError
                if isinstance(e, OracleAuthError):
                    QMessageBox.warning(self, "Oracle Login Failed", str(e))
                else:
                    QMessageBox.warning(self, "Query Error", f"Failed to execute query: {e}")
            except Exception:
                QMessageBox.warning(self, "Query Error", f"Failed to execute query: {e}")

    def storeQueryData(self, responses, queryType):
        """Store API responses and query type after successful query."""
        try:
            normalizedResponses = {}

            for k, v in responses.items():
                key = str(k).strip()
                if isinstance(v, dict) and 'label' in v:
                    v['label'] = v['label'].replace('\n', ' ').replace('\u00a0', ' ')
                    v['label'] = ' '.join(v['label'].split()).strip()
                normalizedResponses[key] = v

            # Normalize keys to remove \n for consistency
            normalizedResponses = {k.replace('\n', ' ').strip(): v for k, v in normalizedResponses.items()}

            self.seriesResponses = normalizedResponses
            self.currentQueryType = queryType
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"Stored query data: {len(normalizedResponses)} series, type {queryType}, keys={[repr(k) for k in normalizedResponses.keys()]}")
        except Exception as e:
            Logic.logException("storeQueryData failed", e)

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
        # Export the table on the active tab (Data Query vs SQL Query Builder)
        exportTable = self.mainTable
        useSqlFormat = False

        currentWidget = self.tabWidget.currentWidget() if self.tabWidget else None
        sqlTab = self.tabSQL or self.findChild(QWidget, 'tabSQL')
        # Detect SQL tab by objectName / index — identity (is) is unreliable across findChild wrappers
        isSqlTab = False
        if currentWidget is not None and self.tabWidget is not None:
            sqlIndex = self.tabWidget.indexOf(sqlTab) if sqlTab is not None else -1
            isSqlTab = (
                currentWidget.objectName() == 'tabSQL'
                or (sqlIndex != -1 and self.tabWidget.currentIndex() == sqlIndex)
                or (sqlTab is not None and currentWidget == sqlTab)
            )

        if isSqlTab and self.sqlTable is not None:
            exportTable = self.sqlTable
            useSqlFormat = True

        if Config.debug:
            tabName = currentWidget.objectName() if currentWidget else None
            Logic.logMessage(
                "DEBUG",
                f"btnExportCSVPressed: activeTab={tabName}, isSqlTab={isSqlTab}, "
                f"rows={exportTable.rowCount() if exportTable else 0}"
            )

        if exportTable is None or exportTable.rowCount() == 0:
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

                headers = []
                for c in range(exportTable.columnCount()):
                    headerItem = exportTable.horizontalHeaderItem(c)
                    headers.append(headerItem.text() if headerItem else f"Column {c}")

                # Data Query uses vertical header timestamps; SQL results use table columns only
                if useSqlFormat or not exportTable.verticalHeaderItem(0):
                    writer.writerow(headers)
                    for row in range(exportTable.rowCount()):
                        rowData = []
                        for col in range(exportTable.columnCount()):
                            item = exportTable.item(row, col)
                            rowData.append(item.text() if item else '')
                        writer.writerow(rowData)
                else:
                    writer.writerow(['Timestamp'] + headers)
                    for row in range(exportTable.rowCount()):
                        tsItem = exportTable.verticalHeaderItem(row)
                        rowData = [tsItem.text() if tsItem else '']
                        for col in range(exportTable.columnCount()):
                            item = exportTable.item(row, col)
                            rowData.append(item.text() if item else '')
                        writer.writerow(rowData)
            config['lastExportPath'] = os.path.dirname(fileName)

            with open(Utils.getConfigPath(), 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)
            if Config.debug:
                Logic.logMessage("DEBUG", f"btnExportCSVPressed: Exported table to {fileName}")
            QMessageBox.information(self, "Export Complete", f"CSV exported successfully to:\n{fileName}")
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
        try:
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
        except Exception as e:
            Logic.logException("btnRefreshPressed failed", e)
            QMessageBox.warning(self, "Refresh Error", f"Failed to refresh query:\n{e}")

    def btnUndoPressed(self):
        try:
            if self.mainTable.rowCount() == 0:
                if Config.debug:
                    Logic.logMessage("DEBUG", "btnUndoPressed: No data to sort")
                QMessageBox.information(self, "Undo", "No data to sort.")
                return
            Query.timestampSortTable(self.mainTable, self.winDataDictionary.mainTable)

            if Config.debug:
                Logic.logMessage("DEBUG", "btnUndoPressed: Called timestampSortTable")
        except Exception as e:
            Logic.logException("btnUndoPressed failed", e)

    def showHeaderContextMenu(self, pos):
        """Show context menu for header right-click to display full query info using uiDetails."""
        try:
            header = self.mainTable.horizontalHeader()
            col = header.logicalIndexAt(pos)

            if col < 0 or col >= len(self.columnMetadata):
                if Config.debug:
                    Logic.logMessage("DEBUG", "showHeaderContextMenu: Invalid column {} clicked".format(col))
                return
            meta = self.columnMetadata[col]
            meta['col'] = col # Add col for stats computation
            menu = QMenu(self)
            
            if meta['type'] == 'normal':
                action = menu.addAction("Show Query Info")
                action.triggered.connect(lambda: self.showHeaderDetails("headerNormal", meta))
            elif meta['type'] == 'delta':
                action = menu.addAction("Show details")
                action.triggered.connect(lambda: self.showHeaderDetails("headerDelta", meta))
            elif meta['type'] == 'overlay':
                action = menu.addAction("Show details")
                action.triggered.connect(lambda: self.showHeaderDetails("headerOverlay", meta))
            
            menu.exec(header.mapToGlobal(pos))
            if Config.debug:
                Logic.logMessage("DEBUG", "showHeaderContextMenu: Displayed menu for column {}, type {}".format(col, meta['type']))
        except Exception as e:
            Logic.logException("showHeaderContextMenu failed", e)

    def showHeaderDetails(self, queryType, meta):
        """Open uiDetails for header metadata."""
        try:
            seriesLabel = self.mainTable.horizontalHeaderItem(meta['col']).text() if self.mainTable.horizontalHeaderItem(meta['col']) else ""
            detailsWin = uiDetails(parent=self)
            detailsWin.populateDetails(queryType, seriesLabel, "", meta)
            detailsWin.show()
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"showHeaderDetails: Opened details for {seriesLabel}")
        except Exception as e:
            Logic.logException("showHeaderDetails failed", e)
            QMessageBox.warning(self, "Details Error", f"Failed to show details:\n{e}")

    def showCellContextMenu(self, pos):
        """Show context menu for cell right-click: Metadata details (internal only, non-overlay) + overlay if applicable."""
        try:
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
            
            # Get lookupId and db from columnMetadata
            lookupId = self.columnMetadata[col].get('lookupId') if col < len(self.columnMetadata) else None
            db = self.columnMetadata[col].get('dbs') if col < len(self.columnMetadata) else None
            
            # Normalize db to string if it's a list (for single-db normal columns)
            if isinstance(db, list) and len(db) > 0:
                db = db[0]
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"showCellContextMenu: columnMetadata={repr(self.columnMetadata)}, col={col}, lookupId={lookupId!r}, db={db!r}")
            
            # Resolve seriesResponses with multiple candidate keys (header label != storage key for USGS).
            response, normalizedLabel = self._resolveSeriesResponse(col, seriesLabel, db, lookupId)

            if Config.debug:
                Logic.logMessage("DEBUG", f"showCellContextMenu: seriesLabel={seriesLabel!r}, normalizedLabel={normalizedLabel!r}, response type={type(response).__name__ if response else 'None'}, response={repr(response) if response else 'None'}, currentQueryType={self.currentQueryType}, seriesResponses keys={[repr(k) for k in self.seriesResponses.keys()]}")              
            menu = QMenu(self)
            
            # Add metadata details if internal query, normal type
            colType = self.columnMetadata[col].get('type') if col < len(self.columnMetadata) else None
            if self.currentQueryType == 'internal' and colType == 'normal':

                # Extract interval from queryInfos (e.g., '20179|HOUR|USBR-LCHDB' -> 'HOUR')
                queryInfo = self.columnMetadata[col].get('queryInfos', ['|'])[0]
                interval = queryInfo.split('|')[1] if '|' in queryInfo else 'HOUR' # Default to HOUR if missing
                
                if db == 'AQUARIUS' and isinstance(response, dict):
                    detailsAction = menu.addAction("Show details")
                    detailsAction.triggered.connect(lambda: self.showMetadataDetails(row, col, timestampStr, seriesLabel, response, 'AQUARIUS', interval))

                    if Config.debug:
                        Logic.logMessage("DEBUG", "showCellContextMenu: Added 'Show details' for AQUARIUS")
                elif db and str(db).startswith('USBR') and isinstance(response, list):
                    detailsAction = menu.addAction("Show details")
                    detailsAction.triggered.connect(lambda: self.showMetadataDetails(row, col, timestampStr, seriesLabel, response, 'USBR', interval))
                    
                    if Config.debug:
                        Logic.logMessage("DEBUG", "showCellContextMenu: Added 'Show details' for USBR")
                elif db == 'USGS-NWIS':
                    # Always offer details for internal USGS (OGC full meta, legacy blanks)
                    usgsResponse = response if isinstance(response, dict) else {"kind": "legacy", "seriesMeta": {}, "points": []}
                    detailsAction = menu.addAction("Show details")
                    detailsAction.triggered.connect(lambda r=row, c=col, ts=timestampStr, sl=seriesLabel, resp=usgsResponse, iv=interval: self.showMetadataDetails(r, c, ts, sl, resp, 'USGS', iv))
                    
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"showCellContextMenu: Added 'Show details' for USGS (kind={usgsResponse.get('kind')})")
            
            # Add single action for overlay columns
            isOverlay = colType == 'overlay'
            
            if isOverlay:
                # Get types from columnMetadata (e.g., ['overlay', 'USBR', 'AQUARIUS'])
                meta = self.columnMetadata[col]
                types = ['overlay'] + meta.get('dbs', []) # Overlay first, then DBs in order
                
                if Config.debug:
                    Logic.logMessage("DEBUG", f"showCellContextMenu: Overlay types for col {col}: {types}")
                
                # Add single action
                detailsAction = menu.addAction("Show details")
                detailsAction.triggered.connect(lambda: self.showMetadataDetails(row, col, timestampStr, seriesLabel, response, 'overlay', multiTypes=types))
            
            if menu.actions(): # Only show if actions added
                menu.exec(self.mainTable.viewport().mapToGlobal(pos))
                
                if Config.debug:
                    Logic.logMessage("DEBUG", f"showCellContextMenu: Displayed menu for cell ({row}, {col}) with {len(menu.actions())} actions")
            else:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"showCellContextMenu: No actions for cell ({row}, {col})")
        except Exception as e:
            Logic.logException("showCellContextMenu failed", e)

    def _resolveSeriesResponse(self, col, seriesLabel, db, lookupId):
        """
        Find the stored series response for a column.

        seriesResponses is keyed by query DataID (and Aquarius label variants).
        Header text alone is not reliable for USGS (headers are site-param + interval).
        """
        candidates = []

        def _add(val):
            if val is None:
                return
            if isinstance(val, (list, tuple)):
                for v in val:
                    _add(v)
                return
            key = str(val).replace('\n', ' ').replace('\u00a0', ' ').strip()
            key = ' '.join(key.split())
            if key and key not in candidates:
                candidates.append(key)

        _add(lookupId)

        meta = self.columnMetadata[col] if col < len(self.columnMetadata) else {}
        _add(meta.get('dataIds'))
        for qi in (meta.get('queryInfos') or []):
            if isinstance(qi, list):
                qi = qi[0] if qi else ''
            qiStr = str(qi) if qi is not None else ''
            if '|' in qiStr:
                _add(qiStr.split('|')[0])
            else:
                _add(qiStr)

        if db == 'AQUARIUS':
            _add(seriesLabel.replace('\n', ' ').strip() if seriesLabel else None)
        elif db == 'USGS-NWIS':
            # Prefer DataID candidates already added; header last line is often just interval
            if seriesLabel:
                parts = [p.strip() for p in seriesLabel.split('\n') if p.strip()]
                for p in parts:
                    _add(p)
        else:
            # USBR: second header line is usually SDID or SDID-MRID
            if seriesLabel and '\n' in seriesLabel:
                _add(seriesLabel.split('\n')[-1].strip())
            elif seriesLabel:
                _add(seriesLabel.strip())

        for key in candidates:
            if key in self.seriesResponses:
                return self.seriesResponses[key], key

        # Case-insensitive fallback (hex time_series_id case mismatches)
        lowerMap = {str(k).lower(): (k, v) for k, v in self.seriesResponses.items()}
        for key in candidates:
            hit = lowerMap.get(key.lower())
            if hit:
                return hit[1], hit[0]

        return None, (candidates[0] if candidates else None)

    def showMetadataDetails(self, row, col, timestampStr, seriesLabel, response, dbType, interval=None, multiTypes=None):
        """Open uiDetails for metadata (Aquarius or USBR)."""
        try:
            # For multiTypes, gather responses and intervals for each type
            responsesList = None
            intervalsList = None

            if multiTypes:
                meta = self.columnMetadata[col]
                lookupIds = meta.get('lookupId', [])
                if not isinstance(lookupIds, list):
                    lookupIds = [lookupIds] if lookupIds is not None else []
                dataIds = meta.get('dataIds', [])
                if not isinstance(dataIds, list):
                    dataIds = [dataIds] if dataIds is not None else []
                dbs = meta.get('dbs', [])
                if not isinstance(dbs, list):
                    dbs = [dbs] if dbs is not None else []
                queryInfos = meta.get('queryInfos', [])
                if not isinstance(queryInfos, list):
                    queryInfos = [queryInfos] if queryInfos is not None else []

                responsesList = []
                intervalsList = []
                
                for i, t in enumerate(multiTypes):
                    if t == 'overlay':
                        # Use cell data for overlay tab
                        item = self.mainTable.item(row, col)
                        cellData = item.data(Qt.ItemDataRole.UserRole) if item else {}
                        responsesList.append(cellData)
                        intervalsList.append(None) # No interval for overlay
                    else:
                        # DB tab index in parallel lists (overlay is multiTypes[0])
                        dbIdx = i - 1
                        lid = lookupIds[dbIdx] if dbIdx < len(lookupIds) else None
                        dataId = dataIds[dbIdx] if dbIdx < len(dataIds) else None
                        dbName = dbs[dbIdx] if dbIdx < len(dbs) else t
                        if isinstance(dbName, list):
                            dbName = dbName[0] if dbName else t

                        # Prefer this tab's own DataID/lookupId so primary/secondary don't swap
                        dbResponse = None
                        matchedKey = None
                        for prefer in (lid, dataId):
                            if prefer is None:
                                continue
                            preferKey = str(prefer).replace('\n', ' ').strip()
                            if preferKey in self.seriesResponses:
                                dbResponse = self.seriesResponses[preferKey]
                                matchedKey = preferKey
                                break
                        if dbResponse is None:
                            dbResponse, matchedKey = self._resolveSeriesResponse(
                                col, seriesLabel, dbName, lid if lid is not None else dataId
                            )

                        if dbResponse is None:
                            dbResponse = {}

                        # USGS-NWIS: ensure details never receive a non-dict (overlay crash guard)
                        if isinstance(t, str) and t.upper().startswith('USGS') and not isinstance(dbResponse, dict):
                            dbResponse = {"kind": "legacy", "seriesMeta": {}, "points": []}
                        responsesList.append(dbResponse)

                        # Extract interval from queryInfos
                        qInfo = queryInfos[dbIdx] if dbIdx < len(queryInfos) else '|'
                        if isinstance(qInfo, list):
                            qInfo = qInfo[0] if qInfo else '|'
                        dbInterval = str(qInfo).split('|')[1] if '|' in str(qInfo) else 'HOUR'
                        intervalsList.append(dbInterval)

                        if Config.debug and not dbResponse:
                            Logic.logMessage(
                                "DEBUG",
                                f"showMetadataDetails: No seriesResponse for type {t} idx={dbIdx} "
                                f"lid={lid!r} dataId={dataId!r} matchedKey={matchedKey!r}"
                            )
                
                if Config.debug:
                    Logic.logMessage("DEBUG", f"showMetadataDetails: Gathered {len(responsesList)} responses and intervals for multiTypes {multiTypes}")
            
            detailsWin = uiDetails(parent=self)
            detailsWin.populateDetails(dbType, seriesLabel, timestampStr, response, interval, multiTypes=multiTypes, responsesList=responsesList, intervalsList=intervalsList)
            detailsWin.show()
            
            if Config.debug:
                Logic.logMessage("DEBUG", f"showMetadataDetails: Opened details for {timestampStr} - {seriesLabel} ({dbType}), multiTypes={multiTypes}")
        except Exception as e:
            Logic.logException("showMetadataDetails failed", e)
            QMessageBox.warning(self, "Details Error", f"Failed to show details:\n{e}")


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

    def refreshSqlTab(self):
        # Load saved splitter sizes from config
        config = Utils.loadConfig()

        sqlSplitter = self.findChild(QSplitter, 'sqlSplitter')
        mainSplitter = self.findChild(QSplitter, 'mainSplitter')

        if sqlSplitter and 'sqlVerticalSizes' in config:
            sqlSplitter.setSizes(config['sqlVerticalSizes'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Restored sqlVerticalSizes: {config['sqlVerticalSizes']}")
        if mainSplitter and 'sqlHorizontalSizes' in config:
            mainSplitter.setSizes(config['sqlHorizontalSizes'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Restored sqlHorizontalSizes: {config['sqlHorizontalSizes']}")

        # Populate cbDatabase and load snippets if controls found
        if self.cbDatabase:
            Utils.loadDatabase(self.cbDatabase, 'sql')
            self.cbDatabase.setMinimumWidth(200)
            self.cbDatabase.adjustSize()
            
            if Config.debug:
                Logic.logMessage("DEBUG", "Refreshed cbDatabase with sizing")
        if self.listSnippets:
            self.loadSnippets()

            if Config.debug:
                Logic.logMessage("DEBUG", "Refreshed snippets list")

if __name__ == '__main__':
    app = None
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("Data Doctor")
        # Taskbar / window icon (Windows + Linux desktop shells that honor QApplication icon)
        _appIcon = QIcon(Logic.resourcePath('ui/icons/DataDoctor.ico'))
        if _appIcon.isNull():
            _appIcon = QIcon(Logic.resourcePath('ui/icons/Data Doctor.png'))
        if not _appIcon.isNull():
            app.setWindowIcon(_appIcon)

        # Init logging early, then install hooks so uncaught errors are logged and non-fatal
        Logic.initLogging()
        Logic.installExceptionHooks(showDialog=True)

        if Config.debug:
            Logic.logMessage("DEBUG", "Applied global app stylesheet with default button effects and tab close styles")

        # Grab system font color and save as global
        Config.systemTextColor = app.palette().color(QPalette.ColorRole.Text)

        # Create instances
        winMain = uiMain()
        if not _appIcon.isNull():
            winMain.setWindowIcon(_appIcon)
        winQuery = uiQuery(winMain)
        winDataDictionary = uiDataDictionary(winMain)
        winOptions = uiOptions(winMain)
        winAbout = uiAbout(winMain)  
        winMain.winQuery = winQuery
        winMain.winDataDictionary = winDataDictionary  
        winMain.winOptions = winOptions
        winMain.winAbout = winAbout

        # Apply styles and fonts
        Utils.applyStylesAndFonts(app, winMain.mainTable, winQuery.listQueryList)

        # Load data dictionary and quick looks (best-effort; do not block startup)
        try:
            Utils.loadDataDictionary(winDataDictionary.mainTable)
        except Exception as e:
            Logic.logException("Startup: loadDataDictionary failed", e)
        try:
            Utils.loadQuickLooks(winQuery.cbQuickLook)
        except Exception as e:
            Logic.logException("Startup: loadQuickLooks failed", e)

        # Show main window
        winMain.show()

        # Convert legacy quickLooks
        try:
            Logic.convertLegacyQuickLooks()
        except Exception as e:
            Logic.logException("Startup: convertLegacyQuickLooks failed", e)
        
        # Start application
        sys.exit(app.exec())
    except Exception as e:
        try:
            Logic.logException("Fatal startup error", e)
        except Exception:
            print(f"Fatal startup error: {e}", file=sys.stderr)
        try:
            if app is not None:
                QMessageBox.critical(None, "Startup Error", f"Data Doctor failed to start:\n{e}")
        except Exception:
            pass
        sys.exit(1)