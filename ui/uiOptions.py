# uiOptions.py

import os
import sys
import json
import keyring
import zipfile
import shutil
import tempfile
from PyQt6.QtWidgets import (
    QDialog, QComboBox, QLineEdit, QRadioButton, QDialogButtonBox, QCheckBox,
    QPushButton, QTabWidget, QMessageBox, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QStackedWidget, QAbstractItemView,
    QSizePolicy, QFileDialog, QInputDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QColorDialog,
)
from PyQt6.QtCore import QTimer, QEvent, QObject, QRunnable, QThreadPool, pyqtSignal, Qt, QSize
from PyQt6.QtGui import QIcon, QPixmap, QColor, QBrush
from PyQt6 import uic
from core import Logic, Utils, Config, TableColors

PROFILE_MANIFEST = "datadoctor-profile.json"
PROFILE_KIND = "DataDoctorProfile"

# Keyring cold-start is slow (Secret Service / Windows Credential Manager).
# Cache after first read so Options opens fast after warm-up.
_CRED_KEYS = (
    "aqServer", "aqUser", "aqPassword",
    "usgsApiKey", "oracleUser", "oraclePassword",
)
_credCache = None  # dict[str, str] | None


def loadKeyringCredentials(force=False):
    """Return credential dict; first call (or force=True) hits keyring."""
    global _credCache
    if _credCache is not None and not force:
        return dict(_credCache)
    out = {}
    for key in _CRED_KEYS:
        try:
            out[key] = keyring.get_password("DataDoctor", key) or ""
        except Exception as e:
            Logic.logMessage("ERROR", f"keyring get_password({key}) failed: {e}")
            out[key] = ""
    _credCache = dict(out)
    return out


def updateKeyringCache(key, value):
    """Keep cache in sync after a successful keyring set_password."""
    global _credCache
    if _credCache is None:
        _credCache = {k: "" for k in _CRED_KEYS}
    _credCache[key] = value if value is not None else ""


def warmKeyringCache():
    """Background-friendly warm so first Options open is not cold."""
    try:
        loadKeyringCredentials(force=True)
        if Config.debug:
            Logic.logMessage("DEBUG", "warmKeyringCache: credential cache ready")
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"warmKeyringCache failed: {e}")


class hdbPasswordChangeSignals(QObject):
    """Signals for background multi-DB HDB password change."""
    finished = pyqtSignal(object)  # first-pass result dict
    singleFinished = pyqtSignal(str, str, str)  # dbName, status, detail


class hdbPasswordChangeWorker(QRunnable):
    """
    Run changePasswordOnAllHdb off the UI thread (first parallel pass).
    Passwords are held only for this run and never logged.
    """
    def __init__(self, username, oldPassword, newPassword, signals, databases=None):
        super().__init__()
        self.username = username
        self.oldPassword = oldPassword
        self.newPassword = newPassword
        self.signals = signals
        self.databases = list(databases) if databases else None

    def run(self):
        result = {'success': [], 'errors': [], 'authFailed': []}
        try:
            from core.Oracle import changePasswordOnAllHdb
            result = changePasswordOnAllHdb(
                username=self.username,
                oldPassword=self.oldPassword,
                newPassword=self.newPassword,
                databases=self.databases,
            )
        except Exception as e:
            Logic.logException("hdbPasswordChangeWorker failed", e)
            result = {
                'success': [],
                'errors': [('(all databases)', str(e))],
                'authFailed': [],
            }
        finally:
            self.oldPassword = None
            self.newPassword = None
        try:
            self.signals.finished.emit(result)
        except Exception:
            pass


class hdbSinglePasswordChangeWorker(QRunnable):
    """Retry password change on one HDB database (after user supplies per-DB old password)."""
    def __init__(self, dbName, username, oldPassword, newPassword, signals):
        super().__init__()
        self.dbName = dbName
        self.username = username
        self.oldPassword = oldPassword
        self.newPassword = newPassword
        self.signals = signals

    def run(self):
        status, detail = 'error', 'Unknown error'
        try:
            from core.Oracle import changePasswordOnDsn, databaseToDsn
            status, detail = changePasswordOnDsn(
                dsn=databaseToDsn(self.dbName),
                username=self.username,
                oldPassword=self.oldPassword,
                newPassword=self.newPassword,
                dbLabel=self.dbName,
            )
        except Exception as e:
            Logic.logException(f"hdbSinglePasswordChangeWorker failed for {self.dbName}", e)
            status, detail = 'error', str(e)
        finally:
            self.oldPassword = None
            self.newPassword = None
        try:
            self.signals.singleFinished.emit(self.dbName, status, detail or '')
        except Exception:
            pass


class uiOptions(QDialog):
    """Options editor: Stores database connection information and application settings."""

    _NAV = (
        ("General", "Cog"),
        ("Appearance", "Appearance"),
        ("Oracle", "Oracle"),
        ("Aquarius", "Aquarius"),
        ("USBR", "USBR"),
        ("USGS", "USGS"),
    )

    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        self.winMain = winMain
        self._passwordChangeSignals = None  # keep alive while worker runs
        uic.loadUi(Logic.resourcePath("ui/winOptions.ui"), self)
        self._bindLoadedWidgets()
        self._tableColorOverrides = {}
        self._buildTableColorUi()
        self.qleAQPassword = self._replaceWithPasswordEdit("qleAQPassword")
        self.qleOraclePassword = self._replaceWithPasswordEdit(
            "qleOraclePassword",
            maxLength=int(getattr(Config, "oraclePasswordMaxLength", 30) or 30),
        )
        self.qleUSGSAPIKey = self._replaceWithPasswordEdit("qleUSGSAPIKey")
        self._applyNavIcons()
        for i, key in enumerate(("system", "light", "dark")):
            if i < self.cbColorTheme.count():
                self.cbColorTheme.setItemData(i, key)

        Utils.buttonStyle(self.btnShowPassword, None, None)
        Utils.buttonStyle(self.btnShowUSGSKey, None, None)
        Utils.buttonStyle(self.btnShowOraclePassword, None, None)
        for btn in (
            self.btnShowPassword,
            self.btnShowUSGSKey,
            self.btnShowOraclePassword,
        ):
            if btn is not None:
                btn.raise_()

        try:
            self.btnbOptions.accepted.disconnect()
        except TypeError:
            pass
        self.btnbOptions.accepted.connect(self.onSavePressed)
        self.btnShowPassword.clicked.connect(self.togglePasswordVisibility)
        self.btnShowUSGSKey.clicked.connect(self.toggleUSGSKeyVisibility)
        self.btnShowOraclePassword.clicked.connect(self.toggleOraclePasswordVisibility)
        self.btnUpdatePassword.clicked.connect(self.onUpdatePasswordPressed)
        self.listOptionsNav.currentRowChanged.connect(self._onNavChanged)
        if self.btnExportProfile is not None:
            self.btnExportProfile.clicked.connect(self.onExportProfile)
        if self.btnImportProfile is not None:
            self.btnImportProfile.clicked.connect(self.onImportProfile)
        self._dirtyWired = False
        self._savedSnapshot = None

        # Populate UTC offset combobox
        self.cbUTCOffset.addItem("UTC-12:00 | Baker Island")
        self.cbUTCOffset.addItem("UTC-11:00 | American Samoa")
        self.cbUTCOffset.addItem("UTC-10:00 | Hawaii")
        self.cbUTCOffset.addItem("UTC-09:30 | Marquesas Islands")
        self.cbUTCOffset.addItem("UTC-09:00 | Alaska")
        self.cbUTCOffset.addItem("UTC-08:00 | Pacific Time (US & Canada)")
        self.cbUTCOffset.addItem("UTC-07:00 | Mountain Time (US & Canada)/Arizona")
        self.cbUTCOffset.addItem("UTC-06:00 | Central Time (US & Canada)")
        self.cbUTCOffset.addItem("UTC-05:00 | Eastern Time (US & Canada)")
        self.cbUTCOffset.addItem("UTC-04:00 | Atlantic Time (Canada)")
        self.cbUTCOffset.addItem("UTC-03:30 | Newfoundland")
        self.cbUTCOffset.addItem("UTC-03:00 | Brasilia")
        self.cbUTCOffset.addItem("UTC-02:00 | Mid-Atlantic")
        self.cbUTCOffset.addItem("UTC-01:00 | Cape Verde Is.")
        self.cbUTCOffset.addItem("UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London")
        self.cbUTCOffset.addItem("UTC+01:00 | Central European Time : Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna")
        self.cbUTCOffset.addItem("UTC+02:00 | Eastern European Time : Athens, Bucharest, Istanbul")
        self.cbUTCOffset.addItem("UTC+03:00 | Moscow, St. Petersburg, Volgograd")
        self.cbUTCOffset.addItem("UTC+03:30 | Tehran")
        self.cbUTCOffset.addItem("UTC+04:00 | Abu Dhabi, Muscat")
        self.cbUTCOffset.addItem("UTC+04:30 | Kabul")
        self.cbUTCOffset.addItem("UTC+05:00 | Islamabad, Karachi, Tashkent")
        self.cbUTCOffset.addItem("UTC+05:30 | Chennai, Kolkata, Mumbai, New Delhi")
        self.cbUTCOffset.addItem("UTC+05:45 | Kathmandu")
        self.cbUTCOffset.addItem("UTC+06:00 | Astana, Dhaka")
        self.cbUTCOffset.addItem("UTC+06:30 | Yangon (Rangoon)")
        self.cbUTCOffset.addItem("UTC+07:00 | Bangkok, Hanoi, Jakarta")
        self.cbUTCOffset.addItem("UTC+08:00 | Beijing, Chongqing, Hong Kong, Urumqi")
        self.cbUTCOffset.addItem("UTC+08:45 | Eucla")
        self.cbUTCOffset.addItem("UTC+09:00 | Osaka, Sapporo, Tokyo")
        self.cbUTCOffset.addItem("UTC+09:30 | Adelaide, Darwin")
        self.cbUTCOffset.addItem("UTC+10:00 | Brisbane, Canberra, Melbourne, Sydney")
        self.cbUTCOffset.addItem("UTC+10:30 | Lord Howe Island")
        self.cbUTCOffset.addItem("UTC+11:00 | Solomon Is., New Caledonia")
        self.cbUTCOffset.addItem("UTC+12:00 | Auckland, Wellington")
        self.cbUTCOffset.addItem("UTC+12:45 | Chatham Islands")
        self.cbUTCOffset.addItem("UTC+13:00 | Samoa")
        self.cbUTCOffset.addItem("UTC+14:00 | Kiritimati")
        self.cbUTCOffset.setCurrentIndex(14)

        self.setupOptionsTabOrder()
        for tabs in (
            self.tabsGeneral, self.tabsAppearance, self.tabsOracle,
            self.tabsAquarius, self.tabsUSBR, self.tabsUSGS,
        ):
            tabs.currentChanged.connect(lambda _i: self.onOptionsTabChanged())

        if Config.debug:
            Logic.logMessage("DEBUG", "uiOptions initialized")

    def _navIcon(self, iconName):
        path = Logic.resourcePath(f"ui/icons/{iconName}.png")
        pix = QPixmap(path)
        if pix.isNull():
            return QIcon()
        return QIcon(pix)

    def _bindLoadedWidgets(self):
        """Hook Designer object names from winOptions.ui."""
        self.listOptionsNav = self.findChild(QListWidget, "listOptionsNav")
        self.optionsStack = self.findChild(QStackedWidget, "optionsStack")
        self.tabsGeneral = self.findChild(QTabWidget, "tabsGeneral")
        self.tabsAppearance = self.findChild(QTabWidget, "tabsAppearance")
        self.tabsOracle = self.findChild(QTabWidget, "tabsOracle")
        self.tabsAquarius = self.findChild(QTabWidget, "tabsAquarius")
        self.tabsUSBR = self.findChild(QTabWidget, "tabsUSBR")
        self.tabsUSGS = self.findChild(QTabWidget, "tabsUSGS")
        self.cbUTCOffset = self.findChild(QComboBox, "cbUTCOffset")
        self.chkbDebug = self.findChild(QCheckBox, "chkbDebug")
        self.chkbBetaUpdates = self.findChild(QCheckBox, "chkbBetaUpdates")
        self.btnExportProfile = self.findChild(QPushButton, "btnExportProfile")
        self.btnImportProfile = self.findChild(QPushButton, "btnImportProfile")
        self.chkbRetroMode = self.findChild(QCheckBox, "chkbRetroMode")
        self.cbColorTheme = self.findChild(QComboBox, "cbColorTheme")
        self.qleTNSNames = self.findChild(QLineEdit, "qleTNSNames")
        self.qleOracleUser = self.findChild(QLineEdit, "qleOracleUser")
        self.qleOraclePassword = self.findChild(QLineEdit, "qleOraclePassword")
        self.btnShowOraclePassword = self.findChild(QPushButton, "btnShowOraclePassword")
        self.btnUpdatePassword = self.findChild(QPushButton, "btnUpdatePassword")
        self.listHdbAccess = self.findChild(QListWidget, "listHdbAccess")
        self.qleAQServer = self.findChild(QLineEdit, "qleAQServer")
        self.qleAQUser = self.findChild(QLineEdit, "qleAQUser")
        self.qleAQPassword = self.findChild(QLineEdit, "qleAQPassword")
        self.btnShowPassword = self.findChild(QPushButton, "btnShowPassword")
        self.chkbLabelDataTypeAquarius = self.findChild(QCheckBox, "chkbLabelDataTypeAquarius")
        self.rbBOP = self.findChild(QRadioButton, "rbBOP")
        self.rbEOP = self.findChild(QRadioButton, "rbEOP")
        self.chkbOverwriteFlag = self.findChild(QCheckBox, "chkbOverwriteFlag")
        self.chkbLabelDataTypeUSBR = self.findChild(QCheckBox, "chkbLabelDataTypeUSBR")
        self.qleUSGSAPIKey = self.findChild(QLineEdit, "qleUSGSAPIKey")
        self.btnShowUSGSKey = self.findChild(QPushButton, "btnShowUSGSKey")
        self.chkbLabelDataTypeUSGS = self.findChild(QCheckBox, "chkbLabelDataTypeUSGS")
        self.btnbOptions = self.findChild(QDialogButtonBox, "btnbOptions")
        self.tabWidget = self.tabsGeneral

    def _applyNavIcons(self):
        if self.listOptionsNav is None:
            return
        self.listOptionsNav.setIconSize(QSize(28, 28))
        for i, (_label, iconName) in enumerate(self._NAV):
            item = self.listOptionsNav.item(i)
            if item is None:
                item = QListWidgetItem(_label)
                self.listOptionsNav.addItem(item)
            item.setIcon(self._navIcon(iconName))
            item.setSizeHint(QSize(160, 40))

    def _onNavChanged(self, index):
        if index < 0:
            return
        self.optionsStack.setCurrentIndex(index)
        page = self.optionsStack.widget(index)
        tabs = page.findChild(QTabWidget) if page is not None else None
        self.tabWidget = tabs if tabs is not None else self.tabsGeneral
        self.onOptionsTabChanged()

    def _buildTableColorUi(self):
        page = self.findChild(QWidget, "tabsAppearanceGeneral")
        lay = page.layout() if page is not None else None
        if lay is None:
            return
        insertAt = max(0, lay.count() - 1)
        lbl = QLabel("Table colors")
        lbl.setToolTip(
            "Colors used in Data Query (QAQC, overlay, delta, pending upload). "
            "Double-click a color to change it. Save to keep."
        )
        self.tblTableColors = QTableWidget(0, 2)
        self.tblTableColors.setObjectName("tblTableColors")
        self.tblTableColors.setHorizontalHeaderLabels(("Meaning", "Color"))
        self.tblTableColors.verticalHeader().setVisible(False)
        self.tblTableColors.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tblTableColors.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblTableColors.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tblTableColors.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tblTableColors.setColumnWidth(1, 88)
        self.tblTableColors.setShowGrid(True)
        self.tblTableColors.cellDoubleClicked.connect(self._onTableColorDoubleClick)
        self.btnRestoreTableColors = QPushButton("Restore Defaults")
        self.btnRestoreTableColors.setObjectName("btnRestoreTableColors")
        self.btnRestoreTableColors.clicked.connect(self._onRestoreTableColors)
        Utils.buttonStyle(self.btnRestoreTableColors, None, None)
        lay.insertWidget(insertAt, lbl)
        lay.insertWidget(insertAt + 1, self.tblTableColors)
        lay.insertWidget(insertAt + 2, self.btnRestoreTableColors)
        self._fillTableColorTable()

    def _fillTableColorTable(self):
        tbl = getattr(self, "tblTableColors", None)
        if tbl is None:
            return
        TableColors.setOverrides(self._tableColorOverrides)
        tbl.setRowCount(len(TableColors.ROWS))
        for i, (key, label, desc, _part) in enumerate(TableColors.ROWS):
            nameItem = QTableWidgetItem(label)
            nameItem.setToolTip(desc)
            nameItem.setData(Qt.ItemDataRole.UserRole, key)
            spec = TableColors.resolved(key)
            swatch = QTableWidgetItem("Aa")
            swatch.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            swatch.setToolTip(desc + "\nDouble-click to change.")
            bg = QColor(spec["bg"]) if spec.get("bg") else QColor()
            fg = QColor(spec["fg"]) if spec.get("fg") else QColor()
            if bg.isValid():
                swatch.setBackground(bg)
            if fg.isValid():
                swatch.setForeground(fg)
            else:
                swatch.setForeground(QBrush())
            tbl.setItem(i, 0, nameItem)
            tbl.setItem(i, 1, swatch)
        tbl.resizeRowsToContents()
        rowsH = tbl.horizontalHeader().height() + sum(
            tbl.rowHeight(r) for r in range(tbl.rowCount())
        ) + 4
        tbl.setMinimumHeight(min(max(rowsH, 160), 320))

    def _onTableColorDoubleClick(self, row, _col):
        nameItem = self.tblTableColors.item(row, 0)
        if nameItem is None:
            return
        key = nameItem.data(Qt.ItemDataRole.UserRole)
        part = "bg"
        for k, _label, _desc, p in TableColors.ROWS:
            if k == key:
                part = "fg" if p == "fg" else "bg"
                break
        current = TableColors.qcolor(key, part) or QColor("#808080")
        picked = QColorDialog.getColor(current, self, "Table color")
        if not picked.isValid():
            return
        over = dict(self._tableColorOverrides.get(key) or {})
        over[part] = picked.name()
        self._tableColorOverrides[key] = over
        TableColors.setOverrides(self._tableColorOverrides)
        self._fillTableColorTable()

    def _onRestoreTableColors(self):
        self._tableColorOverrides = {}
        TableColors.setOverrides({})
        self._fillTableColorTable()

    def _checkedHdbAccess(self):
        names = []
        for i in range(self.listHdbAccess.count()):
            item = self.listHdbAccess.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                names.append(item.text())
        return names

    def _uncheckedHdbAccess(self):
        names = []
        for i in range(self.listHdbAccess.count()):
            item = self.listHdbAccess.item(i)
            if item is not None and item.checkState() != Qt.CheckState.Checked:
                names.append(item.text())
        return names

    def _fillHdbAccessList(self, uncheckedNames):
        """New Config databases default checked; only saved unchecked names stay off."""
        self.listHdbAccess.clear()
        unchecked = set(uncheckedNames or [])
        for name in Utils.hdbAccessDisplayNames():
            item = QListWidgetItem(name)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setCheckState(
                Qt.CheckState.Unchecked if name in unchecked else Qt.CheckState.Checked
            )
            self.listHdbAccess.addItem(item)

    def _layoutContaining(self, layout, widget):
        """Find the (possibly nested) QLayout that owns widget."""
        if layout is None or widget is None:
            return None
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            if item.widget() is widget:
                return layout
            child = item.layout()
            if child is not None:
                found = self._layoutContaining(child, widget)
                if found is not None:
                    return found
        return None

    def _replaceWithPasswordEdit(self, objectName, maxLength=None):
        """
        Swap a plain QLineEdit from the .ui for customPasswordEdit.

        Options pages nest the field in a label + HBox (field | hide button).
        Parent.layout().indexOf(old) is -1 for nested layouts, which used to
        fall through to absolute geometry and park the edit on top of the
        label and hide/unhide button.
        """
        old = self.findChild(QLineEdit, objectName)
        if old is None:
            if Config.debug:
                Logic.logMessage("ERROR", f"{objectName} not found, cannot replace")
            return None

        parent = old.parent()
        geom = old.geometry()
        newEdit = Utils.customPasswordEdit(parent)
        newEdit.setObjectName(objectName)
        newEdit.setPlaceholderText(old.placeholderText())
        if maxLength is not None:
            newEdit.setMaxLength(int(maxLength))
        else:
            newEdit.setMaxLength(old.maxLength())
        newEdit.setAlignment(old.alignment())
        newEdit.setStyleSheet(old.styleSheet())
        newEdit.setEnabled(old.isEnabled())
        newEdit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        pageLayout = parent.layout() if parent is not None else None
        found = self._layoutContaining(pageLayout, old)
        if found is not None:
            found.replaceWidget(old, newEdit)
            old.deleteLater()
            newEdit.show()
            if Config.debug:
                Logic.logMessage("DEBUG", f"Replaced {objectName} via nested layout")
            return newEdit

        # Fallback for a geometry-only page (no layout chain)
        newEdit.setGeometry(geom)
        old.hide()
        old.deleteLater()
        newEdit.show()
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Replaced {objectName} at geometry "
                f"{geom.x()},{geom.y()},{geom.width()}x{geom.height()}",
            )
        return newEdit

    def setupOptionsTabOrder(self):
        """
        Explicit Tab key order per page (top → bottom).
        Geometry-based UI files often leave z-order wrong for keyboard navigation.
        """
        def chain(widgets):
            items = [w for w in widgets if w is not None]
            for a, b in zip(items, items[1:]):
                self.setTabOrder(a, b)

        chain([
            self.cbUTCOffset,
            self.chkbDebug,
            self.chkbBetaUpdates,
            self.btnExportProfile,
            self.btnImportProfile,
        ])
        chain([self.chkbRetroMode, self.cbColorTheme])
        chain([
            self.qleTNSNames,
            self.qleOracleUser,
            getattr(self, 'qleOraclePassword', None),
            self.btnShowOraclePassword,
            self.btnUpdatePassword,
            self.listHdbAccess,
        ])
        chain([
            self.qleAQServer,
            self.qleAQUser,
            getattr(self, 'qleAQPassword', None),
            self.btnShowPassword,
            self.chkbLabelDataTypeAquarius,
        ])
        chain([
            self.rbBOP,
            self.rbEOP,
            self.chkbOverwriteFlag,
            self.chkbLabelDataTypeUSBR,
        ])
        chain([
            getattr(self, 'qleUSGSAPIKey', None),
            self.btnShowUSGSKey,
            self.chkbLabelDataTypeUSGS,
        ])

    def firstFocusWidgetForTab(self, index=None):
        """First interactive control on the visible Options page."""
        nav = self.listOptionsNav.currentRow() if self.listOptionsNav is not None else 0
        byNav = {
            0: self.cbUTCOffset,
            1: self.chkbRetroMode,
            2: self.qleTNSNames,
            3: self.qleAQServer,
            4: self.rbBOP,
            5: getattr(self, 'qleUSGSAPIKey', None),
        }
        w = byNav.get(nav)
        if w is not None and w.isEnabled() and w.isVisible():
            return w
        tabs = getattr(self, 'tabWidget', None)
        if tabs is None:
            return None
        page = tabs.currentWidget() if index is None else tabs.widget(index)
        if page is None:
            return None
        from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QListWidget
        for child in page.findChildren(QWidget):
            if not child.isEnabled() or not child.isVisible():
                continue
            if isinstance(child, (QLineEdit, QComboBox, QAbstractSpinBox, QAbstractButton, QListWidget)):
                if child.focusPolicy() == Qt.FocusPolicy.NoFocus:
                    continue
                return child
        return None

    def onOptionsTabChanged(self, index=None):
        """When user clicks a category or tab, put the cursor on the first field."""
        def focusFirst():
            w = self.firstFocusWidgetForTab(index)
            if w is not None:
                w.setFocus(Qt.FocusReason.TabFocusReason)
        QTimer.singleShot(0, focusFirst)

    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", f"uiOptions showEvent")
        Utils.centerWindowToParent(self)
        super().showEvent(event)
        # Mode-specific checkbox positions (default Noto vs retro)
        Utils.applyModeControlLayouts(root=self)
        Utils.applyRoleFonts(root=self)
        self.loadSettings()
        self.listOptionsNav.setCurrentRow(0)
        self._onNavChanged(0)
        # Always start with secrets masked when the dialog opens
        self.maskSensitiveFields()
        self.onOptionsTabChanged()
        self._wireDirtyTracking()
        self._captureFormSnapshot()
        self._syncCancelCloseText()

        if Config.debug:
            Logic.logMessage("DEBUG", "uiOptions showEvent")

    def hideEvent(self, event):
        # Re-mask on any close (OK, Cancel, X) so secrets don't stay visible next open
        self.maskSensitiveFields()
        super().hideEvent(event)

    def maskSensitiveFields(self):
        """Mask AQ password, USGS API key, Oracle password; reset eye icons to hidden."""
        fields = (
            (getattr(self, 'qleAQPassword', None), getattr(self, 'btnShowPassword', None)),
            (getattr(self, 'qleUSGSAPIKey', None), getattr(self, 'btnShowUSGSKey', None)),
            (getattr(self, 'qleOraclePassword', None), getattr(self, 'btnShowOraclePassword', None)),
        )
        hiddenIcon = QIcon(Logic.resourcePath('ui/icons/Hidden.png'))
        for field, btn in fields:
            if field is not None and hasattr(field, 'setMasked'):
                field.setMasked(True)
            elif field is not None:
                from PyQt6.QtWidgets import QLineEdit
                field.setEchoMode(QLineEdit.EchoMode.Password)
            if btn is not None:
                btn.setIcon(hiddenIcon)
        if Config.debug:
            Logic.logMessage("DEBUG", "maskSensitiveFields: AQ/USGS/Oracle secrets masked")

    def togglePasswordVisibility(self):
        self.qleAQPassword.toggleReveal()
        
        if self.qleAQPassword.isRevealed():
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

            if Config.debug:
                Logic.logMessage("DEBUG", "AQ password shown via button")
        else:
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))

            if Config.debug:
                Logic.logMessage("DEBUG", "AQ password masked via button")

    def toggleUSGSKeyVisibility(self):
        self.qleUSGSAPIKey.toggleReveal()

        if self.qleUSGSAPIKey.isRevealed():
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

            if Config.debug:
                Logic.logMessage("DEBUG", "USGS API key shown via button")
        else:
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))

            if Config.debug:
                Logic.logMessage("DEBUG", "USGS API key masked via button")

    def toggleOraclePasswordVisibility(self):
        self.qleOraclePassword.toggleReveal()

        if self.qleOraclePassword.isRevealed():
            self.btnShowOraclePassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

            if Config.debug:
                Logic.logMessage("DEBUG", "Oracle password shown via button")
        else:
            self.btnShowOraclePassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))

            if Config.debug:
                Logic.logMessage("DEBUG", "Oracle password masked via button")

    def loadSettings(self):
        configPath = Utils.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    Logic.logMessage("DEBUG", "Loaded config from user.config: {}".format(config))
            except Exception as e:
                Logic.logMessage("ERROR", "Failed to load user.config: {}".format(e))

        utcOffset = config.get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London")
        index = self.cbUTCOffset.findText(utcOffset)

        if index != -1:
            self.cbUTCOffset.setCurrentIndex(index)

            if Config.debug:
                Logic.logMessage("DEBUG", "Set cbUTCOffset to: {}".format(utcOffset))
        else:
            self.cbUTCOffset.setCurrentIndex(14)

            if Config.debug:
                Logic.logMessage("DEBUG", "utcOffset '{}' not found, set to default UTC+00:00".format(utcOffset))
        self.chkbRetroMode.setChecked(bool(config.get('retroMode', True)))

        if Config.debug:
            Logic.logMessage("DEBUG", "Set chkbRetroMode to: {}".format(self.chkbRetroMode.isChecked()))
        self.chkbDebug.setChecked(bool(config.get('debugMode', False)))

        if Config.debug:
            Logic.logMessage("DEBUG", "Set chkbDebug to: {}".format(self.chkbDebug.isChecked()))
        if self.chkbBetaUpdates is not None:
            channel = (config.get('updateChannel') or 'stable').strip().lower()
            self.chkbBetaUpdates.setChecked(channel in ('beta', 'pre', 'prerelease', 'rc'))
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"Set chkbBetaUpdates to: {self.chkbBetaUpdates.isChecked()} (channel={channel})",
                )
        try:
            from core.Oracle import resolveTnsAdmin
            tnsPath = resolveTnsAdmin()
        except Exception:
            tnsPath = config.get('tnsNamesLocation', '') or Logic.resourcePath('oracle/network/admin')
        try:
            from core.Oracle import inheritedTnsAdmin
            envTns = inheritedTnsAdmin()
        except Exception:
            envTns = (os.environ.get('TNS_ADMIN') or '').strip()
        if tnsPath.startswith(Config.appRoot):
            tnsPath = tnsPath.replace(Config.appRoot, '%AppRoot%')
        self.qleTNSNames.setText(tnsPath)
        self.qleTNSNames.setReadOnly(bool(envTns))
        if envTns:
            self.qleTNSNames.setToolTip(
                "TNS_ADMIN environment variable is set — that folder is used for "
                "tnsnames.ora and sqlnet.ora."
            )
        else:
            self.qleTNSNames.setToolTip(
                "Folder for tnsnames.ora and sqlnet.ora. Default is packaged "
                "oracle/network/admin (tnsnames.ora is not shipped — copy yours here). "
                "TNS_ADMIN env, if set, wins."
            )

        if Config.debug:
            Logic.logMessage("DEBUG", "Set qleTNSNames to: {}".format(tnsPath))
        hourMethod = config.get('hourTimestampMethod', 'EOP')

        if hourMethod == 'EOP':
            self.rbEOP.setChecked(True)
        else:
            self.rbBOP.setChecked(True)
        if Config.debug:
            Logic.logMessage("DEBUG", "Set hourTimestampMethod to: {}".format(hourMethod))
        theme = str(config.get('colorTheme') or 'system').strip().lower()
        idx = self.cbColorTheme.findData(theme)
        if idx < 0:
            idx = self.cbColorTheme.findText(theme.capitalize())
        self.cbColorTheme.setCurrentIndex(idx if idx >= 0 else 0)
        self._tableColorOverrides = dict(config.get("tableColors") or {})
        TableColors.setOverrides(self._tableColorOverrides)
        self._fillTableColorTable()
        self.chkbOverwriteFlag.setChecked(bool(config.get('hdbOverwriteFlag')))
        self.chkbLabelDataTypeUSBR.setChecked(bool(config.get('labelDataTypeUSBR', True)))
        self.chkbLabelDataTypeAquarius.setChecked(bool(config.get('labelDataTypeAquarius', True)))
        self.chkbLabelDataTypeUSGS.setChecked(bool(config.get('labelDataTypeUSGS', True)))
        self._fillHdbAccessList(config.get('hdbAccessUnchecked'))
        try:
            creds = loadKeyringCredentials(force=False)
            self.qleAQServer.setText(creds.get("aqServer") or "")
            self.qleAQUser.setText(creds.get("aqUser") or "")
            self.qleAQPassword.setText(creds.get("aqPassword") or "")
            self.qleUSGSAPIKey.setText(creds.get("usgsApiKey") or "")
            self.qleOracleUser.setText(creds.get("oracleUser") or "")
            self.qleOraclePassword.setText(creds.get("oraclePassword") or "")

            if Config.debug:
                Logic.logMessage("DEBUG", "Successfully loaded keyring credentials (cached={})".format(
                    _credCache is not None
                ))
        except Exception as e:
            Logic.logMessage("ERROR", "Failed to load keyring credentials: {}. Using empty strings".format(e))

            self.qleAQServer.setText("")
            self.qleAQUser.setText("")
            self.qleAQPassword.setText("")
            self.qleUSGSAPIKey.setText("")
            self.qleOracleUser.setText("")
            self.qleOraclePassword.setText("")
        if Config.debug:
            Logic.logMessage("DEBUG", "Settings loaded")

    def _formSnapshot(self):
        def txt(w):
            return w.text() if w is not None else ''

        def ck(w):
            return bool(w.isChecked()) if w is not None else False

        hdb = []
        if self.listHdbAccess is not None:
            for i in range(self.listHdbAccess.count()):
                item = self.listHdbAccess.item(i)
                if item is not None:
                    hdb.append((item.text(), item.checkState() == Qt.CheckState.Checked))
        theme = ''
        if self.cbColorTheme is not None:
            theme = self.cbColorTheme.currentData() or self.cbColorTheme.currentText()
        utc = self.cbUTCOffset.currentText() if self.cbUTCOffset is not None else ''
        return {
            'utc': utc,
            'debug': ck(self.chkbDebug),
            'beta': ck(self.chkbBetaUpdates),
            'retro': ck(self.chkbRetroMode),
            'theme': theme,
            'tns': txt(self.qleTNSNames),
            'oracleUser': txt(self.qleOracleUser),
            'oraclePassword': txt(self.qleOraclePassword),
            'aqServer': txt(self.qleAQServer),
            'aqUser': txt(self.qleAQUser),
            'aqPassword': txt(self.qleAQPassword),
            'usgsKey': txt(self.qleUSGSAPIKey),
            'bop': ck(self.rbBOP),
            'eop': ck(self.rbEOP),
            'overwrite': ck(self.chkbOverwriteFlag),
            'labelUSBR': ck(self.chkbLabelDataTypeUSBR),
            'labelAQ': ck(self.chkbLabelDataTypeAquarius),
            'labelUSGS': ck(self.chkbLabelDataTypeUSGS),
            'hdb': tuple(hdb),
        }

    def _captureFormSnapshot(self):
        self._savedSnapshot = self._formSnapshot()

    def _syncCancelCloseText(self):
        if self.btnbOptions is None:
            return
        btn = self.btnbOptions.button(QDialogButtonBox.StandardButton.Cancel)
        if btn is None:
            return
        dirty = self._formSnapshot() != getattr(self, '_savedSnapshot', None)
        btn.setText('Cancel' if dirty else 'Close')

    def _wireDirtyTracking(self):
        if getattr(self, '_dirtyWired', False):
            return
        self._dirtyWired = True

        def mark(*_args):
            self._syncCancelCloseText()

        for w in (
            self.cbUTCOffset, self.cbColorTheme,
            self.chkbDebug, self.chkbBetaUpdates, self.chkbRetroMode,
            self.qleTNSNames, self.qleOracleUser, self.qleOraclePassword,
            self.qleAQServer, self.qleAQUser, self.qleAQPassword,
            self.qleUSGSAPIKey, self.rbBOP, self.rbEOP,
            self.chkbOverwriteFlag, self.chkbLabelDataTypeUSBR,
            self.chkbLabelDataTypeAquarius, self.chkbLabelDataTypeUSGS,
        ):
            if w is None:
                continue
            if isinstance(w, QLineEdit):
                w.textChanged.connect(mark)
            elif isinstance(w, (QCheckBox, QRadioButton)):
                w.toggled.connect(mark)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(mark)
        if self.listHdbAccess is not None:
            self.listHdbAccess.itemChanged.connect(mark)

    def onSavePressed(self):
        # --- Capture prior Oracle credentials before keyring overwrite ---
        try:
            priorOracleUser = keyring.get_password("DataDoctor", "oracleUser") or ""
            priorOraclePassword = keyring.get_password("DataDoctor", "oraclePassword") or ""
        except Exception as e:
            priorOracleUser = ""
            priorOraclePassword = ""
            if Config.debug:
                Logic.logMessage("DEBUG", f"onSavePressed: could not read prior Oracle keyring values: {e}")

        newOracleUser = (self.qleOracleUser.text() or "").strip()
        newOraclePassword = self.qleOraclePassword.text() or ""
        priorUserStripped = (priorOracleUser or "").strip()

        # Validate new/changed Oracle password (chars + min length) before any save
        passwordBeingSetOrChanged = bool(newOraclePassword) and (
            newOraclePassword != priorOraclePassword
        )
        if passwordBeingSetOrChanged:
            try:
                from core.Oracle import validateOraclePassword
                ok, errMsg = validateOraclePassword(newOraclePassword)
            except Exception as e:
                ok, errMsg = False, f"Could not validate Oracle password: {e}"
            if not ok:
                QMessageBox.warning(self, "Invalid Oracle Password", errMsg)
                return  # keep Options open; do not save

        configPath = Utils.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    Logic.logMessage("DEBUG", "Read existing user.config: {}".format(config))
            except Exception as e:
                Logic.logMessage("ERROR", "Failed to load user.config for save: {}".format(e))
        previousRetro = config.get('retroMode', True)
        previousChannel = (config.get('updateChannel') or 'stable').strip().lower()
        if previousChannel in ('beta', 'pre', 'prerelease', 'rc'):
            previousChannel = 'beta'
        else:
            previousChannel = 'stable'
        newRetro = self.chkbRetroMode.isChecked()
        colorTheme = self.cbColorTheme.currentData() or 'system'
        tnsPath = self.qleTNSNames.text()

        if '%AppRoot%' in tnsPath:
            tnsPath = tnsPath.replace('%AppRoot%', Config.appRoot)
        hourMethod = 'EOP' if self.rbEOP.isChecked() else 'BOP'
        # Drop legacy enableSQL — SQL tab is toggled via btnSQL on the main window
        config.pop('enableSQL', None)
        updateChannel = 'stable'
        if self.chkbBetaUpdates is not None and self.chkbBetaUpdates.isChecked():
            updateChannel = 'beta'
        config.update({
            'utcOffset': self.cbUTCOffset.currentText(),
            'retroMode': newRetro,
            'debugMode': self.chkbDebug.isChecked(),
            'updateChannel': updateChannel,
            'tnsNamesLocation': tnsPath,
            'hourTimestampMethod': hourMethod,
            # Keep periodOffset in sync: EOP = True (end-of-period), BOP = False
            'periodOffset': hourMethod == 'EOP',
            'lastExportPath': config.get('lastExportPath', ''),
            'colorTheme': colorTheme,
            'hdbOverwriteFlag': bool(self.chkbOverwriteFlag.isChecked()),
            'labelDataTypeUSBR': bool(self.chkbLabelDataTypeUSBR.isChecked()),
            'labelDataTypeAquarius': bool(self.chkbLabelDataTypeAquarius.isChecked()),
            'labelDataTypeUSGS': bool(self.chkbLabelDataTypeUSGS.isChecked()),
            'hdbAccessUnchecked': self._uncheckedHdbAccess(),
            'tableColors': dict(self._tableColorOverrides or {}),
        })
        TableColors.setOverrides(self._tableColorOverrides)
        self._fillTableColorTable()

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2)
        if Config.debug:
            Logic.logMessage("DEBUG", "Saved user.config with retroMode: {}".format(newRetro))
        # Reload non-visual globals only. Config.retroMode stays at the session
        # value for the whole process — fonts/layouts apply only at next start.
        sessionRetro = bool(Config.retroMode)
        Utils.reloadGlobals()
        Config.retroMode = sessionRetro
        Utils.applyColorTheme(colorTheme)

        if newRetro != previousRetro:
            # Never partially apply retro mid-session (Query showEvent, table
            # metrics, button ABS layouts all read Config.retroMode live).
            # Windows auto-restart has been unreliable — always ask for manual
            # restart. Linux may still offer auto-restart.
            import sys
            if sys.platform == 'win32':
                QMessageBox.information(
                    self,
                    "Restart Required",
                    "Retro mode setting was saved.\n\n"
                    "Please close and reopen DataDoctor for the change to take effect.\n"
                    "Nothing will look different until you restart.",
                )
            else:
                reply = QMessageBox.question(
                    self, "Retro Mode Change",
                    "Restart DataDoctor for the retro mode change to take effect?\n"
                    "OK to restart now, Cancel to keep the previous setting on disk.",
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Ok:
                    restarted = Utils.restartApplication()
                    if not restarted:
                        Config.retroMode = sessionRetro
                        QMessageBox.warning(
                            self,
                            "Restart Failed",
                            "Could not restart DataDoctor automatically.\n\n"
                            "Please close and reopen the program for retro mode to apply.\n"
                            "Your retro mode setting was saved.",
                        )
                else:
                    # Revert file only; session visuals never left sessionRetro
                    self.chkbRetroMode.setChecked(previousRetro)
                    config['retroMode'] = previousRetro
                    with open(configPath, 'w', encoding='utf-8') as configFile:
                        json.dump(config, configFile, indent=2)
                    Utils.reloadGlobals()
                    Config.retroMode = sessionRetro
                    if Config.debug:
                        Logic.logMessage("DEBUG", "Reverted retro mode to {}".format(previousRetro))

        credentials = [
            ("aqServer", self.qleAQServer.text()),
            ("aqUser", self.qleAQUser.text()),
            ("aqPassword", self.qleAQPassword.text()),
            ("usgsApiKey", self.qleUSGSAPIKey.text()),
            ("oracleUser", newOracleUser if newOracleUser else self.qleOracleUser.text()),
            ("oraclePassword", newOraclePassword)
        ]

        oracleCredsUpdated = False
        for key, value in credentials:
            if value and isinstance(value, str) and value.strip():
                try:
                    keyring.set_password("DataDoctor", key, value)
                    updateKeyringCache(key, value)
                    if key in ("oracleUser", "oraclePassword"):
                        oracleCredsUpdated = True

                    if Config.debug:
                        Logic.logMessage("DEBUG", "Saved {} to keyring".format(key))
                except Exception as e:
                    Logic.logMessage("ERROR", "Failed to save {} to keyring: {}".format(key, e))
                    QMessageBox.warning(self, "Credential Save Error", "Failed to save {}: {}".format(key, e))
                    
            elif Config.debug:
                Logic.logMessage("DEBUG", "Skipped saving {} to keyring: empty or invalid".format(key))

        # Allow reconnect after user fixes HDB credentials (clears auth fail-fast block)
        if oracleCredsUpdated:
            try:
                from core.Oracle import clearAuthFailure
                clearAuthFailure()
                if Config.debug:
                    Logic.logMessage("DEBUG", "Cleared Oracle auth failure block after credential save")
            except Exception as e:
                if Config.debug:
                    Logic.logMessage("DEBUG", f"clearAuthFailure skipped: {e}")

        self._refreshDatabaseCombos()

        # Apply TNS_ADMIN now so the next Oracle connect uses the saved folder
        # when the environment variable is not set. Already-initialized Instant
        # Client still needs this env for name lookup.
        try:
            from core.Oracle import applyTnsAdmin, inheritedTnsAdmin
            if not inheritedTnsAdmin() and tnsPath:
                applyTnsAdmin(tnsPath)
        except Exception as e:
            if Config.debug:
                Logic.logMessage("DEBUG", f"applyTnsAdmin after Options save skipped: {e}")

        # Keep Options open after Save. Cancel/Close text goes back to Close.
        self._captureFormSnapshot()
        self._syncCancelCloseText()

        # Beta checkbox: check GitHub after save so a first-time beta user
        # is offered the RC, and unchecking reverts to the last published tag.
        if previousChannel != updateChannel:
            parent = self.winMain if self.winMain is not None else None
            from core import Update

            if updateChannel == 'beta':
                QTimer.singleShot(
                    0,
                    lambda: Update.runUpdateCheckUi(parent, silentIfNone=False),
                )
            else:
                QTimer.singleShot(
                    0,
                    lambda: Update.runRevertToPublishedUi(parent),
                )

    def _zipDir(self, zf, srcDir, arcPrefix, extensions):
        if not os.path.isdir(srcDir):
            return 0
        n = 0
        for name in os.listdir(srcDir):
            path = os.path.join(srcDir, name)
            if not os.path.isfile(path):
                continue
            if extensions and not name.endswith(extensions):
                continue
            zf.write(path, f"{arcPrefix}/{name}")
            n += 1
        return n

    def onExportProfile(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Export")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Include:"))
        ckQuery = QCheckBox("Query Quick Looks")
        ckSql = QCheckBox("SQL Quick Looks")
        ckCfg = QCheckBox("Config")
        ckQuery.setChecked(True)
        ckSql.setChecked(True)
        ckCfg.setChecked(True)
        for c in (ckQuery, ckSql, ckCfg):
            lay.addWidget(c)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        parts = []
        if ckQuery.isChecked():
            parts.append("queryQuickLooks")
        if ckSql.isChecked():
            parts.append("sqlQuickLooks")
        if ckCfg.isChecked():
            parts.append("config")
        if not parts:
            QMessageBox.warning(self, "Export", "Check at least one item to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save profile zip", "DataDoctor-profile.zip", "Zip (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            manifest = {
                "app": "DataDoctor",
                "kind": PROFILE_KIND,
                "version": 1,
                "parts": list(parts),
            }
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(PROFILE_MANIFEST, json.dumps(manifest, indent=2))
                if "queryQuickLooks" in parts:
                    self._zipDir(
                        zf, Utils.getQuickLookDir(), "queryQuickLooks", (".json", ".txt")
                    )
                if "sqlQuickLooks" in parts:
                    self._zipDir(
                        zf, Utils.getSqlSnippetDir(), "sqlQuickLooks", (".sql",)
                    )
                    cfg = Utils.loadConfig()
                    cats = {
                        "sqlCategories": list(cfg.get("sqlCategories") or []),
                        "sqlSnippetCategory": dict(cfg.get("sqlSnippetCategory") or {}),
                        "sqlSnippetOrder": list(cfg.get("sqlSnippetOrder") or []),
                    }
                    zf.writestr(
                        "sqlQuickLooks/categories.json",
                        json.dumps(cats, indent=2),
                    )
                if "config" in parts:
                    cfg = Utils.getConfigPath()
                    if os.path.isfile(cfg):
                        zf.write(cfg, "config/user.config")
        except Exception as e:
            Logic.logException("export profile failed", e)
            QMessageBox.warning(self, "Export", f"Could not export:\n{e}")
            return
        if Config.debug:
            Logic.logMessage("DEBUG", f"Exported profile to {path} parts={parts}")
        QMessageBox.information(self, "Export", f"Saved {path}")

    def onImportProfile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import profile zip", "", "Zip (*.zip);;All files (*)"
        )
        if not path:
            return
        try:
            imported = self._importProfilePath(path)
        except ValueError as e:
            QMessageBox.warning(self, "Import", str(e))
            return
        except Exception as e:
            Logic.logException("import profile failed", e)
            QMessageBox.warning(self, "Import", f"Could not import:\n{e}")
            return
        self._refreshAfterImport()
        QMessageBox.information(self, "Import", "Imported:\n" + "\n".join(imported))

    def _importProfilePath(self, path):
        if os.path.isdir(path):
            return self._importProfileDir(path)
        if not zipfile.is_zipfile(path):
            raise ValueError("That file is not a zip archive.")
        tmp = tempfile.mkdtemp(prefix="dd-profile-")
        try:
            with zipfile.ZipFile(path, "r") as zf:
                rootReal = os.path.realpath(tmp) + os.sep
                for info in zf.infolist():
                    dest = os.path.realpath(os.path.join(tmp, info.filename))
                    if not (dest + os.sep).startswith(rootReal) and dest != os.path.realpath(tmp):
                        raise ValueError("Zip contains invalid paths.")
                zf.extractall(tmp)
            return self._importProfileDir(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _profileRoot(self, folder):
        if os.path.isfile(os.path.join(folder, PROFILE_MANIFEST)):
            return folder
        names = [n for n in os.listdir(folder) if not n.startswith(".")]
        if len(names) == 1:
            inner = os.path.join(folder, names[0])
            if os.path.isdir(inner):
                if os.path.isfile(os.path.join(inner, PROFILE_MANIFEST)):
                    return inner
                return inner
        for name in ("queryQuickLooks", "sqlQuickLooks", "config"):
            if os.path.isdir(os.path.join(folder, name)):
                return folder
        if os.path.isfile(os.path.join(folder, "user.config")):
            return folder
        return None

    def _conflictChoice(self, kind, name, remaining):
        """
        Overwrite / Skip / Rename for one name clash.
        Returns 'overwrite', 'overwrite_all', 'skip', 'skip_all', 'rename', or None (cancel).
        """
        box = QMessageBox(self)
        box.setWindowTitle("Import")
        box.setText(f"A {kind} named '{name}' already exists.")
        box.setInformativeText(
            "Overwrite it, skip it, or save the import under a new name?"
        )
        overwrite = box.addButton("Overwrite", QMessageBox.ButtonRole.YesRole)
        skip = box.addButton("Skip", QMessageBox.ButtonRole.NoRole)
        rename = box.addButton("Rename…", QMessageBox.ButtonRole.ActionRole)
        overwriteAll = skipAll = None
        if remaining > 1:
            overwriteAll = box.addButton(
                "Overwrite all", QMessageBox.ButtonRole.AcceptRole
            )
            skipAll = box.addButton("Skip all", QMessageBox.ButtonRole.RejectRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(overwrite)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel or clicked is None:
            return None
        if clicked is overwriteAll:
            return "overwrite_all"
        if clicked is skipAll:
            return "skip_all"
        if clicked is overwrite:
            return "overwrite"
        if clicked is skip:
            return "skip"
        if clicked is rename:
            return "rename"
        return None

    def _uniqueDestName(self, destDir, stem, ext):
        name = stem
        n = 2
        while os.path.exists(os.path.join(destDir, name + ext)):
            name = f"{stem} ({n})"
            n += 1
        return name

    def _mergeImportedFiles(self, srcDir, destDir, extensions, kind):
        """
        Copy files into destDir. Same-name files prompt overwrite / skip / rename.
        Returns (copiedCount, renameMap) where renameMap is oldStem → newStem.
        """
        os.makedirs(destDir, exist_ok=True)
        files = [
            name for name in sorted(os.listdir(srcDir))
            if os.path.isfile(os.path.join(srcDir, name)) and name.endswith(extensions)
        ]
        copied = 0
        renameMap = {}
        mode = None  # overwrite_all / skip_all after a "all" click
        pending = list(files)
        for name in files:
            src = os.path.join(srcDir, name)
            dest = os.path.join(destDir, name)
            stem, ext = os.path.splitext(name)
            remaining = len(pending)
            pending.pop(0)
            if os.path.exists(dest):
                choice = mode
                if choice is None:
                    choice = self._conflictChoice(kind, stem, remaining)
                if choice is None:
                    raise ValueError("Import cancelled.")
                if choice == "overwrite_all":
                    mode = "overwrite_all"
                    choice = "overwrite"
                elif choice == "skip_all":
                    mode = "skip_all"
                    choice = "skip"
                if choice == "skip":
                    continue
                if choice == "rename":
                    suggested = self._uniqueDestName(destDir, stem, ext)
                    newStem, ok = QInputDialog.getText(
                        self, "Rename", "New name:", text=suggested
                    )
                    newStem = (newStem or "").strip()
                    if not ok or not newStem:
                        continue
                    if os.path.exists(os.path.join(destDir, newStem + ext)):
                        newStem = self._uniqueDestName(destDir, newStem, ext)
                    dest = os.path.join(destDir, newStem + ext)
            shutil.copy2(src, dest)
            copied += 1
            destStem = os.path.splitext(os.path.basename(dest))[0]
            renameMap[stem] = destStem
        return copied, renameMap

    def _loadSqlCategoriesSidecar(self, srcDir):
        path = os.path.join(srcDir, "categories.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            Logic.logException("import profile: SQL categories.json failed", e)
        return None

    def _promptSqlCategories(self):
        box = QMessageBox(self)
        box.setWindowTitle("Import SQL Quick Looks")
        box.setText("Import SQL Quick Looks with their categories?")
        box.setInformativeText(
            "Yes keeps folder/category assignments from the zip.\n"
            "No imports the snippets only (new ones go to Uncategorized)."
        )
        yes = box.addButton("With categories", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("Without categories", QMessageBox.ButtonRole.NoRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(yes)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            return True
        if clicked is no:
            return False
        return None

    def _applyImportedSqlCategories(self, sidecar, renameMap, importedStems=None):
        if not sidecar:
            return
        config = Utils.loadConfig()
        cats = list(config.get("sqlCategories") or [])
        incomingCats = list(sidecar.get("sqlCategories") or [])
        for cat in incomingCats:
            if cat and cat not in cats:
                cats.append(cat)
        if "Uncategorized" not in cats:
            cats = ["Uncategorized"] + [c for c in cats if c != "Uncategorized"]
        mapping = dict(config.get("sqlSnippetCategory") or {})
        incomingMap = dict(sidecar.get("sqlSnippetCategory") or {})
        destNames = set(renameMap.values())
        for origStem, destStem in renameMap.items():
            mapping[destStem] = incomingMap.get(origStem) or "Uncategorized"
        order = list(config.get("sqlSnippetOrder") or [])
        incomingOrder = list(sidecar.get("sqlSnippetOrder") or [])
        for name in incomingOrder:
            destName = renameMap.get(name, name)
            if destName not in destNames:
                continue
            if destName in order:
                order.remove(destName)
            order.append(destName)
        config["sqlCategories"] = cats
        config["sqlSnippetCategory"] = mapping
        config["sqlSnippetOrder"] = order
        with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def _importProfileDir(self, folder):
        root = self._profileRoot(folder)
        if root is None:
            raise ValueError(
                "This is not a Data Doctor profile zip "
                "(no query Quick Looks, SQL Quick Looks, or config)."
            )
        manPath = os.path.join(root, PROFILE_MANIFEST)
        parts = []
        if os.path.isfile(manPath):
            with open(manPath, encoding="utf-8") as f:
                man = json.load(f)
            if not isinstance(man, dict):
                raise ValueError("Profile manifest is not valid.")
            if man.get("kind") != PROFILE_KIND and man.get("app") != "DataDoctor":
                raise ValueError("This zip is not a Data Doctor profile.")
            parts = list(man.get("parts") or [])
        if not parts:
            if os.path.isdir(os.path.join(root, "queryQuickLooks")):
                parts.append("queryQuickLooks")
            if os.path.isdir(os.path.join(root, "sqlQuickLooks")):
                parts.append("sqlQuickLooks")
            if os.path.isdir(os.path.join(root, "config")) or os.path.isfile(
                os.path.join(root, "user.config")
            ):
                parts.append("config")
        if not parts:
            raise ValueError("This zip has nothing to import.")
        imported = []
        sqlCatJob = None
        if "queryQuickLooks" in parts:
            src = os.path.join(root, "queryQuickLooks")
            if os.path.isdir(src):
                dest = Utils.getQuickLookDir()
                n, _renames = self._mergeImportedFiles(
                    src, dest, (".json", ".txt"), "query Quick Look"
                )
                imported.append(f"Query Quick Looks ({n})")
        if "sqlQuickLooks" in parts:
            src = os.path.join(root, "sqlQuickLooks")
            if os.path.isdir(src):
                dest = Utils.getSqlSnippetDir()
                sidecar = self._loadSqlCategoriesSidecar(src)
                withCats = False
                if sidecar:
                    choice = self._promptSqlCategories()
                    if choice is None:
                        raise ValueError("Import cancelled.")
                    withCats = bool(choice)
                n, renameMap = self._mergeImportedFiles(
                    src, dest, (".sql",), "SQL Quick Look"
                )
                if withCats:
                    sqlCatJob = (sidecar, renameMap)
                imported.append(f"SQL Quick Looks ({n})")
        if "config" in parts:
            src = os.path.join(root, "config", "user.config")
            if not os.path.isfile(src):
                src = os.path.join(root, "user.config")
            if os.path.isfile(src):
                with open(src, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("Config in the zip is not valid.")
                shutil.copy2(src, Utils.getConfigPath())
                imported.append("Config")
        if sqlCatJob is not None:
            self._applyImportedSqlCategories(sqlCatJob[0], sqlCatJob[1])
        if not imported:
            raise ValueError("This zip has nothing to import.")
        return imported

    def _refreshDatabaseCombos(self):
        """Reload internal / SQL database lists after Access List save."""
        win = self.winMain
        if win is None:
            return
        try:
            wb = getattr(win, "sqlWorkbench", None)
            cb = getattr(wb, "cbDatabase", None) if wb is not None else None
            if cb is None:
                cb = getattr(win, "cbDatabase", None)
            if cb is not None:
                current = cb.currentText()
                Utils.loadDatabase(cb, "sql")
                i = cb.findText(current)
                if i >= 0:
                    cb.setCurrentIndex(i)
        except Exception as e:
            Logic.logException("refresh SQL database combo failed", e)
        try:
            q = getattr(win, "winQuery", None)
            if q is not None and getattr(q, "cbDatabase", None) is not None:
                if getattr(q, "queryType", None) in ("internal", "sql"):
                    current = q.cbDatabase.currentText()
                    Utils.loadDatabase(q.cbDatabase, q.queryType)
                    i = q.cbDatabase.findText(current)
                    if i >= 0:
                        q.cbDatabase.setCurrentIndex(i)
        except Exception as e:
            Logic.logException("refresh Query database combo failed", e)

    def _refreshAfterImport(self):
        Utils.reloadGlobals()
        Utils.applyColorTheme()
        self.loadSettings()
        self._captureFormSnapshot()
        self._syncCancelCloseText()
        win = self.winMain
        if win is None:
            return
        try:
            q = getattr(win, "winQuery", None)
            cb = getattr(q, "cbQuickLook", None) if q is not None else None
            if cb is not None:
                Utils.loadQuickLooks(cb)
        except Exception as e:
            Logic.logException("import profile: refresh Quick Looks failed", e)
        try:
            if hasattr(win, "loadSnippets"):
                win.loadSnippets()
        except Exception as e:
            Logic.logException("import profile: refresh SQL snippets failed", e)

    def onUpdatePasswordPressed(self):
        """Change the Oracle password on checked Access List databases only."""
        newOracleUser = (self.qleOracleUser.text() or "").strip()
        newOraclePassword = self.qleOraclePassword.text() or ""
        if not newOracleUser:
            QMessageBox.warning(self, "Update Password", "Enter an Oracle user name first.")
            return
        if not newOraclePassword:
            QMessageBox.warning(self, "Update Password", "Enter the new Oracle password first.")
            return
        try:
            from core.Oracle import validateOraclePassword
            ok, errMsg = validateOraclePassword(newOraclePassword)
        except Exception as e:
            ok, errMsg = False, f"Could not validate Oracle password: {e}"
        if not ok:
            QMessageBox.warning(self, "Invalid Oracle Password", errMsg)
            return
        targets = self._checkedHdbAccess()
        if not targets:
            QMessageBox.warning(
                self,
                "Update Password",
                "Check at least one database on the Databases tab (Access List).",
            )
            return
        try:
            priorOraclePassword = keyring.get_password("DataDoctor", "oraclePassword") or ""
        except Exception:
            priorOraclePassword = ""
        if not priorOraclePassword:
            QMessageBox.information(
                self,
                "Update Password",
                "No current password is stored in Options. "
                "You will be asked for the current password on each database that needs it.",
            )
            priorOraclePassword = ""
        listed = ", ".join(targets)
        reply = QMessageBox.question(
            self,
            "Update HDB Password",
            f"Change the password for user {newOracleUser} on:\n\n{listed}\n\n"
            "The new password is saved in Options either way.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            keyring.set_password("DataDoctor", "oracleUser", newOracleUser)
            keyring.set_password("DataDoctor", "oraclePassword", newOraclePassword)
            updateKeyringCache("oracleUser", newOracleUser)
            updateKeyringCache("oraclePassword", newOraclePassword)
            from core.Oracle import clearAuthFailure
            clearAuthFailure()
        except Exception as e:
            QMessageBox.warning(self, "Credential Save Error", f"Failed to save Oracle credentials: {e}")
            return
        self._startHdbPasswordChange(
            username=newOracleUser,
            oldPassword=priorOraclePassword,
            newPassword=newOraclePassword,
            databases=targets,
        )

    def _startHdbPasswordChange(self, username, oldPassword, newPassword, databases=None):
        """
        Kick off HDB password updates:
          1) Parallel pass with Options-stored old password
          2) For each DB with wrong password, sequential masked prompt + retry
          3) Final summary (revert local password only if none succeeded)
        """
        winMain = self.winMain
        optionsDialog = self  # reused dialog instance (hidden after accept)
        parent = winMain if winMain is not None else self
        signals = hdbPasswordChangeSignals(parent)
        if winMain is not None:
            winMain._hdbPasswordChangeSignals = signals
        else:
            self._passwordChangeSignals = signals

        state = {
            'parent': parent,
            'optionsDialog': optionsDialog,
            'winMain': winMain,
            'signals': signals,
            'username': username,
            'newPassword': newPassword,
            'storedOldPassword': oldPassword,
            'success': [],
            'errors': [],
            'skipped': [],  # user Cancel/Skip on per-DB password prompt
            'authQueue': [],
        }

        def onFirstPassFinished(result):
            try:
                state['success'] = list((result or {}).get('success') or [])
                state['errors'] = list((result or {}).get('errors') or [])
                authFailed = list((result or {}).get('authFailed') or [])
                # Config order for stable sequential prompts
                # Order by display name (strip |SCHEMA from config entries)
                rawOrder = list(getattr(Config, 'hdbOracleDatabases', ()) or ())
                order = {}
                for i, entry in enumerate(rawOrder):
                    name = str(entry).split('|', 1)[0].strip() if entry else ''
                    if name:
                        order[name] = i
                authFailed.sort(key=lambda n: order.get(n, 999))
                state['authQueue'] = authFailed
                # success / errors already use display names from Oracle layer
                state['success'] = [str(s).split('|', 1)[0].strip() for s in state['success']]
                state['errors'] = [
                    (str(pair[0]).split('|', 1)[0].strip(), pair[1])
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2
                    else pair
                    for pair in state['errors']
                ]
                Logic.logMessage(
                    "INFO",
                    f"HDB password first pass: {len(state['success'])} ok, "
                    f"{len(state['errors'])} locked/user-facing error(s), "
                    f"{len(state['authQueue'])} need per-DB password",
                )
                uiOptions._processHdbAuthQueue(state)
            except Exception as e:
                Logic.logException("HDB password change first-pass handler failed", e)
                uiOptions._finalizeHdbPasswordChange(state)

        signals.finished.connect(onFirstPassFinished)
        worker = hdbPasswordChangeWorker(
            username, oldPassword, newPassword, signals, databases=databases
        )
        targetNote = (
            ", ".join(databases) if databases else "all USBR databases"
        )
        Logic.logMessage(
            "INFO",
            f"Starting HDB password change for user {username} on {targetNote}",
        )
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _processHdbAuthQueue(state):
        """
        Sequentially prompt for each DB that rejected the stored old password,
        then retry that DB alone. One popup at a time.
        """
        parent = state['parent']
        queue = state.get('authQueue') or []

        if not queue:
            uiOptions._finalizeHdbPasswordChange(state)
            return

        dbName = queue.pop(0)
        state['authQueue'] = queue
        username = state.get('username') or ''

        dbOldPassword = uiOptions._promptDbOldPassword(parent, dbName, username)
        if not dbOldPassword:
            # Cancel / Skip / empty: leave this DB alone and continue the queue
            Logic.logMessage(
                "INFO",
                f"HDB password prompt skipped for {dbName} (user cancel or empty)",
            )
            skipped = state.setdefault('skipped', [])
            if dbName not in skipped:
                skipped.append(dbName)
            uiOptions._processHdbAuthQueue(state)
            return

        signals = state['signals']
        # Disconnect previous single-finished handlers to avoid stacking
        try:
            signals.singleFinished.disconnect()
        except TypeError:
            pass

        def onSingleFinished(doneDb, status, detail):
            try:
                if status == 'success':
                    if doneDb not in state['success']:
                        state['success'].append(doneDb)
                    Logic.logMessage(
                        "INFO",
                        f"HDB password changed on {doneDb} after per-DB password prompt",
                    )
                elif status == 'auth':
                    # Still wrong after user entry — report, do not re-prompt forever
                    state['errors'].append(
                        (doneDb, detail or 'Wrong password for this database')
                    )
                    Logic.logMessage(
                        "INFO",
                        f"HDB password still wrong on {doneDb} after per-DB prompt",
                    )
                elif status == 'missing':
                    # Definitive missing user — silent (do not list)
                    Logic.logMessage(
                        "INFO",
                        f"HDB password change skipped on {doneDb}: user not found",
                    )
                elif status == 'locked':
                    state['errors'].append((doneDb, detail or 'Account locked'))
                else:
                    # Non-auth / non-locked failures: log only (avoid UI spam)
                    Logic.logMessage(
                        "ERROR",
                        f"HDB password change failed on {doneDb} (not shown in UI): "
                        f"{detail or status}",
                    )
            except Exception as e:
                Logic.logException(f"HDB single-retry handler failed for {doneDb}", e)
                state['errors'].append((doneDb, str(e)))
            finally:
                # Next DB in queue (or finalize)
                uiOptions._processHdbAuthQueue(state)

        signals.singleFinished.connect(onSingleFinished)
        worker = hdbSinglePasswordChangeWorker(
            dbName=dbName,
            username=username,
            oldPassword=dbOldPassword,
            newPassword=state['newPassword'],
            signals=signals,
        )
        dbOldPassword = None  # drop local ref; worker holds until run ends
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _promptDbOldPassword(parent, dbName, username):
        """
        Modal masked password prompt for one HDB database.
        Returns the password string, or None if cancelled / Skip / empty.
        Cancel skips this database and continues with any remaining HDBs.
        Never logs the password.
        """
        maxLen = int(getattr(Config, 'oraclePasswordMaxLength', 30) or 30)
        dialog = QDialog(parent)
        dialog.setWindowTitle("HDB Current Password")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        label = QLabel(
            f"Could not change the password on <b>{dbName}</b>.<br><br>"
            f"The password currently saved in Options does not work on this database "
            f"(passwords often differ across HDBs).<br><br>"
            f"Enter the <b>current</b> password for user <b>{username}</b> on "
            f"<b>{dbName}</b>.<br><br>"
            f"Click <b>Skip</b> to leave this database unchanged and continue.",
            dialog,
        )
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label)

        pwdEdit = QLineEdit(dialog)
        pwdEdit.setEchoMode(QLineEdit.EchoMode.Password)
        pwdEdit.setMaxLength(maxLen)
        pwdEdit.setPlaceholderText("Current password for this database")
        layout.addWidget(pwdEdit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        # Cancel = Skip this DB (do not abort remaining prompts)
        cancelBtn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancelBtn is not None:
            cancelBtn.setText("Skip")
            cancelBtn.setToolTip("Skip this database and continue with the rest")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        pwdEdit.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        text = pwdEdit.text() or ''
        pwdEdit.clear()
        if not text:
            return None
        return text

    @staticmethod
    def _finalizeHdbPasswordChange(state):
        """Apply revert if needed, show summary, clear secrets from state."""
        parent = state.get('parent')
        optionsDialog = state.get('optionsDialog')
        winMain = state.get('winMain')
        storedOld = state.get('storedOldPassword')
        success = list(state.get('success') or [])
        errors = list(state.get('errors') or [])
        skipped = list(state.get('skipped') or [])

        # Stable order for display (strip |SCHEMA from config keys)
        order = {}
        for i, entry in enumerate(getattr(Config, 'hdbOracleDatabases', ()) or ()):
            name = str(entry).split('|', 1)[0].strip() if entry else ''
            if name:
                order[name] = i
        success.sort(key=lambda n: order.get(n, 999))
        errors.sort(key=lambda pair: order.get(pair[0] if isinstance(pair, (list, tuple)) else str(pair), 999))
        skipped.sort(key=lambda n: order.get(n, 999))

        result = {'success': success, 'errors': errors, 'skipped': skipped}
        reverted = False
        try:
            if not success and storedOld is not None:
                reverted = uiOptions._revertOraclePassword(optionsDialog, storedOld)
            uiOptions._showHdbPasswordChangeResults(
                parent, result, passwordReverted=reverted
            )
        except Exception as e:
            Logic.logException("HDB password change finalize failed", e)
        finally:
            # Drop secrets
            state['newPassword'] = None
            state['storedOldPassword'] = None
            if winMain is not None:
                winMain._hdbPasswordChangeSignals = None
            try:
                sig = state.get('signals')
                if sig is not None:
                    try:
                        sig.finished.disconnect()
                    except TypeError:
                        pass
                    try:
                        sig.singleFinished.disconnect()
                    except TypeError:
                        pass
            except Exception:
                pass

    @staticmethod
    def _revertOraclePassword(optionsDialog, oldPassword):
        """
        Restore the previous Oracle password in keyring and winOptions field.
        Called when no HDB database accepted the new password.
        Returns True if keyring was restored. Never logs the password.
        """
        restored = False
        try:
            if oldPassword is not None and str(oldPassword) != '':
                keyring.set_password("DataDoctor", "oraclePassword", oldPassword)
                updateKeyringCache("oraclePassword", oldPassword)
                restored = True
                Logic.logMessage(
                    "INFO",
                    "HDB password change failed on all databases; "
                    "restored previous Oracle password in Options/keyring",
                )
        except Exception as e:
            Logic.logMessage(
                "ERROR",
                f"Failed to restore previous Oracle password to keyring: {e}",
            )

        # Put old value back into the Options password field (dialog is reused)
        try:
            field = None
            if optionsDialog is not None:
                field = getattr(optionsDialog, 'qleOraclePassword', None)
            if field is None:
                # Fallback: main window's stored Options instance
                winMain = getattr(optionsDialog, 'winMain', None) if optionsDialog else None
                if winMain is not None:
                    opts = getattr(winMain, 'winOptions', None)
                    if opts is not None:
                        field = getattr(opts, 'qleOraclePassword', None)
            if field is not None and oldPassword is not None:
                field.setText(oldPassword)
                if Config.debug:
                    Logic.logMessage(
                        "DEBUG",
                        "Restored previous Oracle password into qleOraclePassword",
                    )
        except Exception as e:
            Logic.logMessage(
                "ERROR",
                f"Failed to restore Oracle password field in Options: {e}",
            )

        # Allow reconnect with restored credentials
        if restored:
            try:
                from core.Oracle import clearAuthFailure
                clearAuthFailure()
            except Exception:
                pass

        return restored

    @staticmethod
    def _showHdbPasswordChangeResults(parent, result, passwordReverted=False):
        """Popup summarizing which DBs changed, skipped, or errored (not missing users)."""
        success = list((result or {}).get('success') or [])
        errors = list((result or {}).get('errors') or [])
        skipped = list((result or {}).get('skipped') or [])

        if not success and not errors and not skipped:
            # Nothing changed and nothing reported (all silent missing, or no targets)
            Logic.logMessage(
                "INFO",
                "HDB password change: no databases updated",
            )
            revertNote = (
                "\n\nYour previous password was restored in Options."
                if passwordReverted
                else "\n\nCould not restore the previous password automatically; "
                     "re-enter it in Options → Oracle if needed."
            )
            QMessageBox.information(
                parent,
                "HDB Password Update",
                "Password change finished.\n\n"
                "No databases were updated "
                "(account not found on any HDB, or none were reachable)."
                + revertNote,
            )
            return

        lines = ["HDB password update finished.", ""]
        if success:
            lines.append("Password changed on:")
            for db in success:
                lines.append(f"  • {db}")
            lines.append("")
        if skipped:
            lines.append("Skipped (left unchanged):")
            for db in skipped:
                lines.append(f"  • {db}")
            lines.append("")
        if errors:
            lines.append("Not updated:")
            for item in errors:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    db, msg = item[0], item[1]
                else:
                    db, msg = str(item), ''
                if msg:
                    lines.append(f"  • {db}: {msg}")
                else:
                    lines.append(f"  • {db}")

        # Zero success after prompts/retries — local password was reverted
        if not success and passwordReverted:
            lines.append("")
            lines.append("No databases accepted the new password.")
            lines.append("Your previous password was restored in Options.")

        # INFO summary without secrets
        Logic.logMessage(
            "INFO",
            "HDB password change results: changed on [{}]; skipped [{}]; errors on [{}]{}".format(
                ', '.join(success) if success else 'none',
                ', '.join(skipped) if skipped else 'none',
                ', '.join(
                    (e[0] if isinstance(e, (list, tuple)) and e else str(e))
                    for e in errors
                ) if errors else 'none',
                '; local password reverted' if (not success and passwordReverted) else '',
            ),
        )

        QMessageBox.information(parent, "HDB Password Update", '\n'.join(lines).rstrip())