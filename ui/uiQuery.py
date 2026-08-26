# uiQuery.py

import json
import os
from PyQt6.QtWidgets import (QMainWindow, QLineEdit, QComboBox, QDateTimeEdit, QListWidget, QPushButton, QRadioButton,
                            QButtonGroup, QCheckBox, QMessageBox, QInputDialog, QMenu)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QEvent
from PyQt6 import uic
from core import Logic, Query, Utils, Config, Upload
from ui.uiSearch import uiSearch

# Full interval list for non-USGS databases (matches prior cbInterval population)
ALL_INTERVALS = (
    'HOUR',
    'INSTANT:1',
    'INSTANT:15',
    'INSTANT:60',
    'DAY',
    'MONTH',
    'YEAR',
    'WATER YEAR',
)
# USGS-NWIS: no HOUR product; continuous instants + daily only (no monthly/yearly)
# INSTANT:15 first — default for most USGS series when USGS-NWIS is selected
USGS_INTERVALS = (
    'INSTANT:15',
    'INSTANT:1',
    'INSTANT:60',
    'DAY',
)
USGS_DEFAULT_INTERVAL = 'INSTANT:15'


class uiQuery(QMainWindow):
    """Query window: Builds and executes public/internal API calls."""
    def __init__(self, winMain=None):
        # No Qt parent: child QMainWindows shade-minimize instead of taskbar.
        super().__init__(None)
        uiPath = Logic.resourcePath('ui/winQuery.ui')

        if Config.debug:
            Logic.logMessage("DEBUG", f"Loading UI file: {uiPath}")
            
            if not os.path.exists(uiPath):
                Logic.logMessage("ERROR", f"UI file not found: {uiPath}")
        try:
            uic.loadUi(uiPath, self)
        except Exception as e:
            Logic.logMessage("ERROR", f"Failed to load UI file: {e}")
            raise

        # Define controls
        self.queryType = None
        self.winMain = winMain
        # Row index being edited after double-click (None = Add appends a new row)
        self.editingQueryIndex = None
        self.btnQuery = self.findChild(QPushButton, 'btnQuery')
        self.qleDataID = self.findChild(QLineEdit, 'qleDataID')
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
        self.btnDeleteQuickLook = self.findChild(QPushButton, 'btnDeleteQuickLook')
        self.btnClearQuery = self.findChild(QPushButton, 'btnClearQuery')
        self.btnDataIdInfo = self.findChild(QPushButton, 'btnDataIdInfo')
        self.btnIntervalInfo = self.findChild(QPushButton, 'btnIntervalInfo')
        self.rbCustomDateTime = self.findChild(QRadioButton, 'rbCustomDateTime')
        self.rbPrevDayToCurrent = self.findChild(QRadioButton, 'rbPrevDayToCurrent')
        self.rbPrevWeekToCurrent = self.findChild(QRadioButton, 'rbPrevWeekToCurrent')
        self.chkbDelta = self.findChild(QCheckBox, 'chkbDelta')
        self.chkbOverlay = self.findChild(QCheckBox, 'chkbOverlay')
        self.btnUpMax = self.findChild(QPushButton, 'btnUpMax')
        self.btnUp15 = self.findChild(QPushButton, 'btnUp15')
        self.btnUp5 = self.findChild(QPushButton, 'btnUp5')
        self.btnUp1 = self.findChild(QPushButton, 'btnUp1')
        self.btnDownMax = self.findChild(QPushButton, 'btnDownMax')
        self.btnDown15 = self.findChild(QPushButton, 'btnDown15')
        self.btnDown5 = self.findChild(QPushButton, 'btnDown5')
        self.btnDown1 = self.findChild(QPushButton, 'btnDown1')
        self.btnSearch.clicked.connect(self.showSearch)
        self.btnQueryOptionsInfo = self.findChild(QPushButton, 'btnQueryOptionsInfo')
        self.uiSearch = None

        # Group radio buttons
        self.radioGroup = QButtonGroup(self)
        self.radioGroup.addButton(self.rbCustomDateTime)
        self.radioGroup.addButton(self.rbPrevDayToCurrent)
        self.radioGroup.addButton(self.rbPrevWeekToCurrent)

        # Interval combobox: full list by default; USGS-NWIS trims to daily max
        self.populateIntervalCombo(ALL_INTERVALS)

        # Add blank combobox item
        self.cbDatabase.addItem('')

        # Map button style
        buttonIcons = [
                        (self.btnDataIdInfo, "Info", 24),
                        (self.btnIntervalInfo, "Info", 24),
                        (self.btnUpMax, "Up-MAX", 24),
                        (self.btnUp15, "Up-15", 24),
                        (self.btnUp5, "Up-5", 24),
                        (self.btnUp1, "Up-1", 24),
                        (self.btnDownMax, "Down-MAX", 24),
                        (self.btnDown15, "Down-15", 24),
                        (self.btnRemoveQuery, "Delete", 24),
                        (self.btnDown5, "Down-5", 24),
                        (self.btnDown1, "Down-1", 24),
                        (self.btnSearch, "Search", 24),
                        (self.btnQueryOptionsInfo, "Info", 24)
                      ]

        # Set button style        
        for btn, iconName, iconSize in buttonIcons:
            if btn:
                Utils.buttonStyle(btn, iconName, iconSize=iconSize)

        # Create events
        self.btnQuery.clicked.connect(self.btnQueryPressed)
        self.btnAddQuery.clicked.connect(self.btnAddQueryPressed)
        self.btnRemoveQuery.clicked.connect(self.btnRemoveQueryPressed)
        self.btnSaveQuickLook.clicked.connect(self.btnSaveQuickLookPressed)
        self.btnLoadQuickLook.clicked.connect(self.btnLoadQuickLookPressed) 
        self.btnDeleteQuickLook.clicked.connect(self.btnDeleteQuickLookPressed)
        self.btnClearQuery.clicked.connect(self.btnClearQueryPressed)
        self.btnDataIdInfo.clicked.connect(self.btnDataIdInfoPressed)
        self.btnIntervalInfo.clicked.connect(self.btnIntervalInfoPressed)
        self.radioGroup.buttonClicked.connect(lambda btn: Logic.setQueryDateRange(self, btn, self.dteStartDate, self.dteEndDate))
        self.btnUpMax.clicked.connect(self.btnUpMaxPressed)
        self.btnUp15.clicked.connect(self.btnUp15Pressed)
        self.btnUp5.clicked.connect(self.btnUp5Pressed)
        self.btnUp1.clicked.connect(self.btnUp1Pressed)
        self.btnDownMax.clicked.connect(self.btnDownMaxPressed)
        self.btnDown15.clicked.connect(self.btnDown15Pressed)
        self.btnDown5.clicked.connect(self.btnDown5Pressed)
        self.btnDown1.clicked.connect(self.btnDown1Pressed)
        self.btnQueryOptionsInfo.clicked.connect(self.btnQueryOptionsInfoPressed)
        self.cbDatabase.currentTextChanged.connect(self.onDatabaseChanged)
        # NOTE: empty QListWidget is falsy in PyQt6 (len==0) — always test is not None
        if self.listQueryList is not None:
            self.listQueryList.itemDoubleClicked.connect(self.onQueryListDoubleClicked)
            self.listQueryList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.listQueryList.customContextMenuRequested.connect(self.showQueryListContextMenu)

        # Install event filters
        self.qleDataID.installEventFilter(self)
        self.installEventFilter(self)

        # Set initial state
        Logic.initializeQueryWindow(self, self.rbCustomDateTime, self.dteStartDate, self.dteEndDate)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        Utils.bindIndependentWindow(self, owner=winMain, allowMaximize=False)

        if Config.debug:
            Logic.logMessage("DEBUG", "uiQuery initialized")

    def populateIntervalCombo(self, intervals, preferred=None):
        """
        Replace cbInterval items.
        Keep prior selection if still in the list; otherwise use preferred, else first item.
        """
        # Do not use `if not self.cbInterval` — empty QComboBox is falsy (len==0)
        if self.cbInterval is None:
            return
        prev = self.cbInterval.currentText()
        self.cbInterval.blockSignals(True)
        try:
            self.cbInterval.clear()
            for name in intervals:
                self.cbInterval.addItem(name)
            idx = self.cbInterval.findText(prev)
            if idx >= 0:
                self.cbInterval.setCurrentIndex(idx)
            elif preferred:
                prefIdx = self.cbInterval.findText(preferred)
                self.cbInterval.setCurrentIndex(prefIdx if prefIdx >= 0 else 0)
            elif self.cbInterval.count() > 0:
                self.cbInterval.setCurrentIndex(0)
        finally:
            self.cbInterval.blockSignals(False)

    def updateIntervalForDatabase(self, database=None):
        """
        USGS-NWIS: no HOUR / no coarser-than-DAY; default INSTANT:15.
        Any other DB: full interval list.
        """
        if self.cbDatabase is None:
            return
        db = self.cbDatabase.currentText() if database is None else database
        if db == 'USGS-NWIS':
            # Drop HOUR and monthly+; default INSTANT:15 when prev is invalid (e.g. HOUR)
            self.populateIntervalCombo(USGS_INTERVALS, preferred=USGS_DEFAULT_INTERVAL)
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"cbInterval USGS-NWIS list; current={self.cbInterval.currentText()!r}",
                )
        else:
            self.populateIntervalCombo(ALL_INTERVALS)
            if Config.debug:
                Logic.logMessage("DEBUG", f"cbInterval full list restored for database={db!r}")

    def onDatabaseChanged(self, text):
        self.updateIntervalForDatabase(text)

    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", "uiQuery showEvent: queryType={}".format(self.queryType))
        Utils.centerWindowToParent(self)
        # Re-apply role fonts + mode ABS layouts (info icons) after show
        Utils.applyRoleFonts(root=self)
        Utils.applyModeControlLayouts(root=self)
        Logic.loadLastQuickLook(self.cbQuickLook)
        Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)

        # Populate database combobox
        Utils.loadDatabase(self.cbDatabase, self.queryType)
        # loadDatabase rebuilds cbDatabase — re-apply interval filter for selection
        self.updateIntervalForDatabase()

        # Set window icon and title based on queryType
        if self.queryType == 'public':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/PublicQuery.png')))
            self.setWindowTitle("Public Query")

            if Config.debug:
                Logic.logMessage("DEBUG", "uiQuery showEvent: Set window icon to PublicQuery.png and title to Public Query")
        elif self.queryType == 'internal':
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/InternalQuery.png')))
            self.setWindowTitle("Internal Query")

            if Config.debug:
                Logic.logMessage("DEBUG", "uiQuery showEvent: Set window icon to InternalQuery.png and title to Internal Query")
        else:
            Logic.logMessage("WARN", "uiQuery showEvent: queryType not set, defaulting to public")

            self.queryType = 'public'
            self.setWindowIcon(QIcon(Logic.resourcePath('ui/icons/PublicQuery.png')))
            self.setWindowTitle("Public Query")
        # Prev Day / Prev Week: snap end time to now whenever the window opens
        # (Custom DateTime is left alone so historical ranges stay intact).
        self.refreshRelativeQueryTimes()
        super().showEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.qleDataID and event.type() == QEvent.Type.FocusIn:
            if Config.debug:
                Logic.logMessage("DEBUG", "qleDataID focus in, setting Add Query default")
            Logic.setDefaultButton(self, self.qleDataID, self.btnAddQuery, self.btnQuery)
        elif obj == self.qleDataID and event.type() == QEvent.Type.FocusOut:
            if Config.debug:
                Logic.logMessage("DEBUG", "qleDataID focus out, setting Query Data default")
            Logic.setDefaultButton(self, None, self.btnAddQuery, self.btnQuery)
        elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if Config.debug:
                Logic.logMessage("DEBUG", "Enter key pressed")
            if self.qleDataID.hasFocus():
                if Config.debug:
                    Logic.logMessage("DEBUG", "qleDataID focused, triggering btnAddQueryPressed")
                self.btnAddQueryPressed()
            elif self.btnQuery.isDefault():
                if Config.debug:
                    Logic.logMessage("DEBUG", "btnQuery is default, triggering btnQueryPressed")
                self.btnQueryPressed()
            return True
        return super().eventFilter(obj, event)

    def btnQueryPressed(self):
        try:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnQueryPressed: Starting query process, queryType={}".format(self.queryType))
            # Refresh relative date ranges so end time is "now" at click, not when
            # the window was first opened / radio was last selected.
            self.refreshRelativeQueryTimes()
            startDate = self.dteStartDate.dateTime().toString('yyyy-MM-dd hh:mm')
            endDate = self.dteEndDate.dateTime().toString('yyyy-MM-dd hh:mm')
            queryItems = []

            for i in range(self.listQueryList.count()):
                itemText = self.listQueryList.item(i).text().strip()
                parts = itemText.split('|')

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Item text: '{itemText}', parts: {parts}, len: {len(parts)}")
                if len(parts) != 3:
                    Logic.logMessage("WARN", f"Invalid item skipped: {itemText}")
                    continue

                dataId, interval, database = parts
                if database == 'USGS-NWIS':
                    try:
                        from core import USGS
                        resolved = USGS.resolveUsgsDataId(dataId, parent=self)
                        if resolved is None:
                            QMessageBox.warning(
                                self,
                                "USGS Data ID",
                                f"Could not resolve USGS Data ID '{dataId}' in the query list.\n"
                                "Include time_series_id, or pick a series when prompted.",
                            )
                            return
                        if resolved != dataId:
                            dataId = resolved
                            # Keep list in sync with resolved form
                            self.listQueryList.item(i).setText(f"{dataId}|{interval}|{database}")
                    except Exception as e:
                        Logic.logException("btnQueryPressed: USGS list resolve failed", e)
                mrid = '0'
                sdid = dataId

                if database.startswith('USBR-') and '-' in dataId:
                    sdid, mrid = dataId.rsplit('-', 1)
                queryItems.append((dataId, interval, database, mrid, i))

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Added queryItem: {(dataId, interval, database, mrid, i)}")
            if not queryItems and self.qleDataID.text().strip():
                dataId = self.qleDataID.text().strip()
                interval = self.cbInterval.currentText()
                database = self.cbDatabase.currentText()
                # USGS Site-Parameter may need multi-series pick (same as Add Query)
                if database == 'USGS-NWIS':
                    try:
                        from core import USGS
                        resolved = USGS.resolveUsgsDataId(dataId, parent=self)
                        if resolved is None:
                            QMessageBox.warning(
                                self,
                                "USGS Data ID",
                                f"Could not resolve USGS Data ID '{dataId}'.\n"
                                "Include time_series_id, or pick a series when prompted.",
                            )
                            return
                        dataId = resolved
                    except Exception as e:
                        Logic.logException("btnQueryPressed: USGS resolve failed", e)
                mrid = '0'
                sdid = dataId

                if database.startswith('USBR-') and '-' in dataId:
                    sdid, mrid = dataId.rsplit('-', 1)
                queryItems.append((dataId, interval, database, mrid, 0))

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Added single query: {(dataId, interval, database, mrid, 0)}")
            elif not queryItems:
                Logic.logMessage("WARN", "No valid query items.")
                return
            deltaChecked = self.chkbDelta.isChecked()
            overlayChecked = self.chkbOverlay.isChecked()

            if self.winMain:
                if not Upload.confirmDiscardPendingEdits(self, "run a new query"):
                    if Config.debug:
                        Logic.logMessage("DEBUG", "btnQueryPressed: Canceled due to pending edits")
                    return

                self.winMain.lastQueryType = self.queryType
                self.winMain.lastQueryItems = queryItems
                self.winMain.lastStartDate = startDate
                self.winMain.lastEndDate = endDate
                self.winMain.lastDatabase = self.cbDatabase.currentText() if not queryItems else None
                self.winMain.lastInterval = self.cbInterval.currentText() if not queryItems else None

                if Config.debug:
                    Logic.logMessage("DEBUG", "Stored last query as {}".format(self.queryType))
                Query.executeQuery(self.winMain, queryItems, startDate, endDate,
                                  self.queryType == 'internal', self.winMain.winDataDictionary.mainTable, deltaChecked, overlayChecked)
                self.close()

                if Config.debug:
                    Logic.logMessage("DEBUG", "Query window closed after query.")
        except Exception as e:
            Logic.logException("btnQueryPressed failed", e)
            QMessageBox.warning(self, "Query Error", f"Failed to run query:\n{e}")

    def btnSaveQuickLookPressed(self):
        if Config.debug:
            Logic.logMessage("DEBUG", "btnSaveQuickLookPressed: Attempting to save Quick Look")
        if self.listQueryList.count() == 0:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnSaveQuickLookPressed: Empty query list, showing warning")
            QMessageBox.warning(self, "Empty Query List", "Cannot save Quick Look: No items in the query list.")
            return        
        # Wider than default QInputDialog (~+60px) so longer Quick Look names fit
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Save Quick Look")
        dlg.setLabelText("Quick Look name:")
        dlg.setInputMode(QInputDialog.InputMode.TextInput)
        dlg.setOkButtonText("Save")
        existingName = ""
        if self.cbQuickLook is not None:
            existingName = (self.cbQuickLook.currentText() or "").strip()
        if existingName:
            dlg.setTextValue(existingName)
        hint = dlg.sizeHint()
        dlg.resize(max(hint.width(), 280) + 60, hint.height())
        ok = dlg.exec() == dlg.DialogCode.Accepted
        name = dlg.textValue().strip() if ok else ""

        if ok and name:
            if Logic.quickLookExists(name):
                reply = QMessageBox.question(
                    self,
                    "Overwrite Quick Look",
                    f"A Quick Look named '{name}' already exists.\n\nOverwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    if Config.debug:
                        Logic.logMessage(
                            "DEBUG",
                            f"btnSaveQuickLookPressed: overwrite of '{name}' declined",
                        )
                    return
            deltaChecked = bool(self.chkbDelta.isChecked()) if self.chkbDelta is not None else False
            overlayChecked = bool(self.chkbOverlay.isChecked()) if self.chkbOverlay is not None else False
            Logic.saveQuickLook(
                name,
                self.listQueryList,
                displayDelta=deltaChecked,
                overlayPairs=overlayChecked,
            )
            Utils.loadQuickLooks(self.cbQuickLook)
            if self.cbQuickLook is not None:
                idx = self.cbQuickLook.findText(name)
                if idx >= 0:
                    self.cbQuickLook.setCurrentIndex(idx)

            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"btnSaveQuickLookPressed: Saved '{name}' "
                    f"(displayDelta={deltaChecked}, overlayPairs={overlayChecked})",
                )

    def btnLoadQuickLookPressed(self):
        Logic.loadQuickLook(
            self.cbQuickLook,
            self.listQueryList,
            chkbDelta=self.chkbDelta,
            chkbOverlay=self.chkbOverlay,
        )
        # Relative date ranges should be "now" after loading a quick look too
        self.refreshRelativeQueryTimes()
        configPath = Utils.getConfigPath()
        config = {}
        
        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Loaded config: {config}")
            except Exception as e:
                Logic.logMessage("ERROR", f"Failed to load user.config: {e}")
        config['lastQuickLook'] = self.cbQuickLook.currentText()

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2)
        if Config.debug:
            Logic.logMessage("DEBUG", f"Loaded quick look: {self.cbQuickLook.currentText()}")

    def btnDeleteQuickLookPressed(self):
        quickLookName = self.cbQuickLook.currentText()

        if not quickLookName:
            if Logic.Config.debug:
                Logic.logMessage("DEBUG", "btnDeleteQuickLookPressed: No Quick Look selected to delete")
            return
        
        # Confirm deletion with user
        reply = QMessageBox.question(self, "Delete Quick Look", f"Are you sure you want to delete '{quickLookName}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.No:
            return        
        deleted = Logic.deleteQuickLook(quickLookName)

        if deleted:
            currentIndex = self.cbQuickLook.currentIndex()
            self.cbQuickLook.removeItem(currentIndex)
            self.cbQuickLook.setCurrentIndex(-1)
            
            if Logic.Config.debug:
                Logic.logMessage("DEBUG", f"btnDeleteQuickLookPressed: Removed '{quickLookName}' from combo box and cleared selection")
        else:
            QMessageBox.warning(self, "Cannot Delete", "Example Quick Looks cannot be deleted.")
            if Logic.Config.debug:
                Logic.logMessage("DEBUG", f"btnDeleteQuickLookPressed: Attempted to delete example Quick Look '{quickLookName}'—skipped")

    def onQueryListDoubleClicked(self, item):
        """Load a list row into the form for in-place edit (dataID, interval, database)."""
        if item is None or self.listQueryList is None:
            return
        text = item.text().strip()
        # maxsplit=2 so dataIDs / DB labels that contain '|' still parse
        parts = text.split('|', 2)
        if len(parts) != 3:
            if Config.debug:
                Logic.logMessage("DEBUG", f"onQueryListDoubleClicked: invalid row {text!r}")
            return
        dataId, interval, database = parts
        self.editingQueryIndex = self.listQueryList.row(item)
        if self.qleDataID is not None:
            self.qleDataID.setText(dataId)
            self.qleDataID.setFocus()
            self.qleDataID.selectAll()
        # Align combos with the row so interval/database can be changed before re-add
        # Do not use truthiness on combos — empty QComboBox is falsy
        if self.cbDatabase is not None and database is not None:
            idx = self.cbDatabase.findText(database)
            if idx >= 0:
                self.cbDatabase.setCurrentIndex(idx)
        # Interval after database so USGS interval filter applies first
        if self.cbInterval is not None and interval:
            idx = self.cbInterval.findText(interval)
            if idx >= 0:
                self.cbInterval.setCurrentIndex(idx)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"onQueryListDoubleClicked: editing index={self.editingQueryIndex} "
                f"dataID={dataId!r} interval={interval!r} database={database!r}",
            )

    def btnAddQueryPressed(self):
        # In-place edit uses current form values (dataID, interval, and database)
        editIdx = self.editingQueryIndex
        itemText = self.buildQueryListItemText()
        if not itemText:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnAddQueryPressed: No Data ID entered or resolve cancelled")
            return

        if (
            editIdx is not None
            and self.listQueryList is not None
            and 0 <= editIdx < self.listQueryList.count()
        ):
            self.listQueryList.item(editIdx).setText(itemText)
            self.listQueryList.setCurrentRow(editIdx)
            if Config.debug:
                Logic.logMessage("DEBUG", f"btnAddQueryPressed: Updated index {editIdx}: {itemText}")
        else:
            self.listQueryList.addItem(itemText)
            self.listQueryList.scrollToBottom()
            if Config.debug:
                Logic.logMessage("DEBUG", f"btnAddQueryPressed: Added item: {itemText}")
        self.editingQueryIndex = None
        self.qleDataID.clear()
        self.qleDataID.setFocus()

    def btnRemoveQueryPressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnRemoveQueryPressed: No items selected, skipping")
            return
        # Clear in-place edit index if that row is being removed
        removedRows = {self.listQueryList.row(item) for item in selectedItems}
        if self.editingQueryIndex is not None and self.editingQueryIndex in removedRows:
            self.editingQueryIndex = None
            if self.qleDataID:
                self.qleDataID.clear()
        for item in selectedItems:
            self.listQueryList.takeItem(self.listQueryList.row(item))
        # Adjust edit index if a row above it was removed
        if self.editingQueryIndex is not None:
            below = sum(1 for r in removedRows if r < self.editingQueryIndex)
            self.editingQueryIndex -= below
            if self.editingQueryIndex < 0 or self.editingQueryIndex >= self.listQueryList.count():
                self.editingQueryIndex = None
        if Config.debug:
            Logic.logMessage("DEBUG", f"btnRemoveQueryPressed: Removed {len(selectedItems)} items")

    def btnClearQueryPressed(self):
        self.listQueryList.clear()
        self.editingQueryIndex = None
        if self.qleDataID:
            self.qleDataID.clear()
        # Clear Display Deltas / Overlay Pairs when the list is wiped
        if self.chkbDelta is not None:
            self.chkbDelta.setChecked(False)
        if self.chkbOverlay is not None:
            self.chkbOverlay.setChecked(False)
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                "btnClearQueryPressed: Cleared query list and unchecked delta/overlay",
            )

    def refreshRelativeQueryTimes(self):
        """
        Re-apply Previous day / Previous week ranges so end = now at Query click.
        Custom DateTime is left unchanged.
        """
        try:
            if self.rbPrevDayToCurrent is not None and self.rbPrevDayToCurrent.isChecked():
                Logic.setQueryDateRange(
                    self, self.rbPrevDayToCurrent, self.dteStartDate, self.dteEndDate
                )
                if Config.debug:
                    Logic.logMessage("DEBUG", "refreshRelativeQueryTimes: refreshed Prev Day → Current")
            elif self.rbPrevWeekToCurrent is not None and self.rbPrevWeekToCurrent.isChecked():
                Logic.setQueryDateRange(
                    self, self.rbPrevWeekToCurrent, self.dteStartDate, self.dteEndDate
                )
                if Config.debug:
                    Logic.logMessage("DEBUG", "refreshRelativeQueryTimes: refreshed Prev Week → Current")
        except Exception as e:
            Logic.logException("refreshRelativeQueryTimes failed", e)

    def buildQueryListItemText(self):
        """
        Build 'dataID|interval|database' from the form (same rules as Add Query).
        Returns None if invalid / cancelled (e.g. empty DataID or USGS cancel).
        """
        dataID = self.qleDataID.text().strip() if self.qleDataID is not None else ''
        interval = self.cbInterval.currentText() if self.cbInterval is not None else ''
        database = self.cbDatabase.currentText() if self.cbDatabase is not None else ''

        if not dataID:
            return None

        if database == 'USGS-NWIS':
            try:
                from core import USGS
                resolved = USGS.resolveUsgsDataId(dataID, parent=self)
                if resolved is None:
                    classified = USGS.classifyUid(dataID)
                    if classified and classified[0] == 'ogcLookup':
                        QMessageBox.warning(
                            self,
                            "USGS Data ID",
                            f"No time series found for '{dataID}', or selection was cancelled.\n\n"
                            "Use Site-time_series_id or Site-time_series_id-parameter,\n"
                            "or Site-parameter (e.g. 09428500-00065) when only one series exists.",
                        )
                        return None
                    if classified is None:
                        QMessageBox.warning(
                            self,
                            "USGS Data ID",
                            "Invalid USGS Data ID.\n\n"
                            "Accepted forms:\n"
                            "  Site-time_series_id[-parameter]\n"
                            "  Site-parameter (looks up time_series_id)\n"
                            "  Site-methodID-parameter (legacy)",
                        )
                        return None
                else:
                    dataID = resolved
            except Exception as e:
                Logic.logException("buildQueryListItemText: USGS resolve failed", e)

        return f"{dataID}|{interval}|{database}"

    def showQueryListContextMenu(self, pos):
        """
        Right-click a query list item: Insert Query Above / Below when DataID
        is set, and Delete (clicked row, or all selected if the click is in
        the selection).
        """
        if self.listQueryList is None:
            return
        item = self.listQueryList.itemAt(pos)
        if item is None:
            return
        row = self.listQueryList.row(item)
        selected = self.listQueryList.selectedItems()
        if item not in selected:
            self.listQueryList.clearSelection()
            item.setSelected(True)
            self.listQueryList.setCurrentItem(item)

        dataID = self.qleDataID.text().strip() if self.qleDataID is not None else ''
        menu = QMenu(self)
        actAbove = menu.addAction("Insert Query Above")
        actBelow = menu.addAction("Insert Query Below")
        actAbove.setEnabled(bool(dataID))
        actBelow.setEnabled(bool(dataID))
        if not dataID:
            actAbove.setToolTip("Enter a Data ID first")
            actBelow.setToolTip("Enter a Data ID first")
        menu.addSeparator()
        nSel = len(self.listQueryList.selectedItems())
        actDelete = menu.addAction("Delete" if nSel <= 1 else f"Delete ({nSel})")

        chosen = menu.exec(self.listQueryList.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == actAbove:
            self.insertQueryAt(row, below=False)
        elif chosen == actBelow:
            self.insertQueryAt(row, below=True)
        elif chosen == actDelete:
            self.btnRemoveQueryPressed()

    def insertQueryAt(self, anchorRow, below=False):
        """Insert form values into the list above or below anchorRow (like Add Query)."""
        if self.listQueryList is None:
            return
        itemText = self.buildQueryListItemText()
        if not itemText:
            if Config.debug:
                Logic.logMessage("DEBUG", "insertQueryAt: no item text (empty DataID or cancel)")
            return
        insertAt = anchorRow + 1 if below else anchorRow
        insertAt = max(0, min(insertAt, self.listQueryList.count()))
        self.listQueryList.insertItem(insertAt, itemText)
        self.listQueryList.setCurrentRow(insertAt)
        # Cancel any in-place edit mode so the next Add appends cleanly
        self.editingQueryIndex = None
        if self.qleDataID is not None:
            self.qleDataID.clear()
            self.qleDataID.setFocus()
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"insertQueryAt: inserted at {insertAt} ({'below' if below else 'above'} "
                f"anchor {anchorRow}): {itemText}",
            )

    def btnDataIdInfoPressed(self):
        QMessageBox.information(
            self,
            "DataID Formats",
            "AQUARIUS Format:\nUID\n\n"
            "USBR Format:\nSDID\nSDID-MRID\n\n"
            "USGS Format:\n"
            "  Site-time_series_id[-parameter]  (OGC; parameter optional)\n"
            "  Site-parameter  (looks up time_series_id; picker if multiple)\n"
            "  Site-methodID-parameter  (legacy waterservices)",
        )
        if Config.debug:
            Logic.logMessage("DEBUG", "Data ID info displayed")

    def btnIntervalInfoPressed(self):
        QMessageBox.information(self, "Interval Info", "Interval determines what timestamps are displayed and what table the data is queried from (USBR).\n\nIn a query list, timestamp interval is determined by first dataID in the list.")
        if Config.debug:
            Logic.logMessage("DEBUG", "Interval info displayed")

    def btnUpMaxPressed(self):
        selectedItems = self.listQueryList.selectedItems()
        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUpMaxPressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)

            if currentRow == 0:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUpMaxPressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(0, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUpMaxPressed: Moved selected items to top")

    def btnUp15Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUp15Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 15)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUp15Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUp15Pressed: Moved selected items up by 15")

    def btnUp5Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUp5Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 5)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUp5Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUp5Pressed: Moved selected items up by 5")

    def btnUp1Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnUp1Pressed: No items selected, skipping")
            return
        for item in selectedItems:
            currentRow = self.listQueryList.row(item)
            newRow = max(0, currentRow - 1)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnUp1Pressed: Item at row {currentRow} already at top")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnUp1Pressed: Moved selected items up by 1")

    def btnDownMaxPressed(self):
        selectedItems = self.listQueryList.selectedItems()
        
        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDownMaxPressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)

            if currentRow == bottomRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDownMaxPressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.addItem(item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDownMaxPressed: Moved selected items to bottom")

    def btnDown15Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDown15Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 15)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDown15Pressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDown15Pressed: Moved selected items down by 15")

    def btnDown5Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDown5Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 5)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDown5Pressed: Item at row {currentRow} already at bottom")
                continue

            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDown5Pressed: Moved selected items down by 5")

    def btnDown1Pressed(self):
        selectedItems = self.listQueryList.selectedItems()

        if not selectedItems:
            if Config.debug:
                Logic.logMessage("DEBUG", "btnDown1Pressed: No items selected, skipping")
            return
        bottomRow = self.listQueryList.count() - 1

        for item in reversed(selectedItems):
            currentRow = self.listQueryList.row(item)
            newRow = min(bottomRow, currentRow + 1)

            if currentRow == newRow:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"btnDown1Pressed: Item at row {currentRow} already at bottom")
                continue
            
            self.listQueryList.takeItem(currentRow)
            self.listQueryList.insertItem(newRow, item)
            self.listQueryList.setCurrentItem(item)
        if Config.debug:
            Logic.logMessage("DEBUG", "btnDown1Pressed: Moved selected items down by 1")

    def btnQueryOptionsInfoPressed(self):
        QMessageBox.information(self, "Query Options Info",
                                "Delta: Calculate and display the change between consecutive values.\n\nOverlay: Display multiple datasets in a single view for comparison.")
        if Config.debug:
            Logic.logMessage("DEBUG", "btnQueryOptionsInfoPressed: Showed Query Options info dialog")

    def showSearch(self):
        if self.uiSearch is None:
            self.uiSearch = uiSearch(self)
        self.uiSearch.show()

        if Config.debug:
            Logic.logMessage("DEBUG", "showSearch: Opened uiSearch window")