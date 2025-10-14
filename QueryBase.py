import configparser
from datetime import datetime, timedelta
from collections import defaultdict
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6 import uic
import Logic
import QueryUSBR
import QueryUSGS
import QueryAquarius

class uiQueryBase(QMainWindow):
    """Base class for query windows: Shared UI setup and query logic."""
    def __init__(self, parent=None, uiFile=''):
        super(uiQueryBase, self).__init__(parent)
        uic.loadUi(Logic.resourcePath(f'ui/{uiFile}'), self)

        # Define the controls
        self.btnQuery = self.findChild(QPushButton, 'btnQuery')
        self.textSDID = self.findChild(QTextEdit, 'textSDID')
        self.cbDatabase = self.findChild(QComboBox, 'cbDatabase')
        self.cbInterval = self.findChild(QComboBox, 'cbInterval')
        self.dteStartDate = self.findChild(QDateTimeEdit, 'dteStartDate')
        self.dteEndDate = self.findChild(QDateTimeEdit, 'dteEndDate')
        self.listQueryList = self.findChild(QListWidget, 'listQueryList')
        self.btnAddQuery = self.findChild(QPushButton, 'btnAddQuery')
        self.btnRemoveQuery = self.findChild(QPushButton, 'btnRemoveQuery')
        self.btnSaveQuickLook = self.findChild(QPushButton, 'btnSaveQuickLook')
        self.cbQuickLook = self.findChild(QComboBox, 'cbQuickLook')
        self.btnLoadQuickLook = self.findChild(QPushButton, 'btnLoadQuickLook')
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery')
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo')
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo')

        # Set button style for info buttons
        Logic.buttonStyle(self.btnDataIdInfo)
        Logic.buttonStyle(self.btnIntervalInfo)

        # Create shared events
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed)
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed)
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed)
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed)
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed)

        # Populate interval combobox (shared)
        self.cbInterval.addItem('HOUR')
        self.cbInterval.addItem('INSTANT')
        self.cbInterval.addItem('DAY')

        # Set default query times
        self.dteStartDate.setDateTime(datetime.now() - timedelta(hours=72))
        self.dteEndDate.setDateTime(datetime.now())

        # Load last quickLook from config
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath())

        if 'Settings' in config and 'lastQuickLook' in config['Settings']:
            lastQuickLook = config['Settings']['lastQuickLook']
            index = self.cbQuickLook.findText(lastQuickLook)
            if index != -1:
                self.cbQuickLook.setCurrentIndex(index)
        else:
            self.cbQuickLook.setCurrentIndex(-1)

        # Disable maximize button (shared for both windows)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

    def showEvent(self, event):
        Logic.centerWindowToParent(self)
        self.cbQuickLook.setCurrentIndex(-1)  # Temporary until lastQuickLook fixed
        super().showEvent(event)

    def btnDataIdInfoPressed(self):
        QMessageBox.information(self, "DataID Formats", "AQUARIUS Format: \nUID \n\nUSBR Format: \nSDID \nSDID-MRID \n\nUSGS Format: \nSite-Method-Parameter")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")

    def btnAddQueryPressed(self):
        item = f'{self.textSDID.toPlainText().strip()}|{self.cbInterval.currentText()}|{self.cbDatabase.currentText()}'
        self.listQueryList.addItem(item)
        self.textSDID.clear()
        self.textSDID.setFocus()

    def btnRemoveQueryPressed(self):
        item = self.listQueryList.currentItem()
        self.listQueryList.takeItem(self.listQueryList.row(item))

    def btnSaveQuickLookPressed(self):
        winQuickLook.exec()

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(self.cbQuickLook, self.listQueryList)

        # Save last selected quickLook to config
        config = configparser.ConfigParser()
        config.read(Logic.getConfigPath())

        if 'Settings' not in config:
            config['Settings'] = {}

        config['Settings']['lastQuickLook'] = self.cbQuickLook.currentText()

        with open(Logic.getConfigPath(), 'w') as configFile:
            config.write(configFile)

    def btnClearQueryPressed(self):
        self.listQueryList.clear()

    def collectQueryItems(self):
        """Shared: Collect and parse query items from list or single text."""
        queryItems = []

        for i in range(self.listQueryList.count()):
            itemText = self.listQueryList.item(i).text().strip()
            parts = itemText.split('|')

            if len(parts) != 3:
                continue

            dataID, interval, database = parts
            mrid = '0'
            SDID = dataID

            if database.startswith('USBR-'):
                if '-' in dataID:
                    SDID, mrid = dataID.rsplit('-', 1)

            queryItems.append((dataID, interval, database, mrid, i))

        # Add single if list empty and text not empty
        if not queryItems and self.textSDID.toPlainText().strip():
            dataID = self.textSDID.toPlainText().strip()
            interval = self.cbInterval.currentText()
            database = self.cbDatabase.currentText()
            mrid = '0'
            SDID = dataID

            if database.startswith('USBR-') and '-' in dataID:
                SDID, mrid = dataID.rsplit('-', 1)

            queryItems.append((dataID, interval, database, mrid, 0))

        queryItems.sort(key=lambda x: x[4])
        return queryItems

    def processQuery(self, queryItems, startDate, endDate):
        """Shared: Process query items, group, fetch data, build table."""
        if not queryItems:
            return

        firstInterval = queryItems[0][1]
        firstDb = queryItems[0][2]

        if firstInterval == 'INSTANT' and firstDb.startswith('USBR-'):
            firstInterval = 'HOUR'

        timestamps = Logic.buildTimestamps(startDate, endDate, firstInterval)

        if not timestamps:
            QMessageBox.warning(self, "Date Error", "Invalid dates or interval.")
            return

        defaultBlanks = [''] * len(timestamps)

        groups = defaultdict(list)

        for dataID, interval, db, mrid, origIndex in queryItems:
            groupKey = (db, mrid if db.startswith('USBR-') else None, interval)
            SDID = dataID if not db.startswith('USBR-') or '-' not in dataID else dataID.rsplit('-', 1)[0]
            groups[groupKey].append((origIndex, dataID, SDID))

        valueDict = {}

        for (db, mrid, interval), groupItems in groups.items():
            SDIDs = [item[2] for item in groupItems]  # SDID per item
            result = self.queryGroup(db, mrid, interval, SDIDs, startDate, endDate)

            for idx, (origIndex, dataID, SDID) in enumerate(groupItems):
                if SDID in result:
                    outputData = result[SDID]
                    alignedData = Logic.gapCheck(timestamps, outputData, dataID)
                    values = [line.split(',')[1] if line else '' for line in alignedData]
                    valueDict[dataID] = values
                else:
                    valueDict[dataID] = defaultBlanks

        originalDataIds = [item[0] for item in queryItems]
        originalIntervals = [item[1] for item in queryItems]

        lookupIds = []
        for item in queryItems:
            dataID, interval, db, mrid, origIndex = item
            lookupId = dataID if not db.startswith('USBR-') or '-' not in dataID else dataID.split('-')[0]
            lookupIds.append(lookupId)

        data = []
        
        for r in range(len(timestamps)):
            rowValues = [valueDict.get(dataID, defaultBlanks)[r] for dataID in originalDataIds]
            data.append(f"{timestamps[r]},{','.join(rowValues)}")

        buildHeader = originalDataIds
        intervalsForHeaders = originalIntervals

        winMain.mainTable.clear()
        Logic.buildTable(winMain.mainTable, data, buildHeader, winDataDictionary.mainTable, intervalsForHeaders, lookupIds)

        if winMain.tabWidget.indexOf(winMain.tabMain) == -1:
            winMain.tabWidget.addTab(winMain.tabMain, 'Data Query')

        self.close()

    def queryGroup(self, db, mrid, interval, SDIDs, startDate, endDate):
        """Abstract: Override in subclasses to perform actual query."""
        raise NotImplementedError("Subclasses must implement queryGroup")