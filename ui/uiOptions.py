# uiOptions.py

import os
import sys
import json
import keyring
from PyQt6.QtWidgets import (
    QDialog, QComboBox, QLineEdit, QRadioButton, QDialogButtonBox, QCheckBox,
    QPushButton, QTabWidget, QMessageBox, QWidget, QVBoxLayout, QLabel,
)
from PyQt6.QtCore import QTimer, QEvent, QObject, QRunnable, QThreadPool, pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6 import uic
from core import Logic, Utils, Config

class hdbPasswordChangeSignals(QObject):
    """Signals for background multi-DB HDB password change."""
    finished = pyqtSignal(object)  # first-pass result dict
    singleFinished = pyqtSignal(str, str, str)  # dbName, status, detail


class hdbPasswordChangeWorker(QRunnable):
    """
    Run changePasswordOnAllHdb off the UI thread (first parallel pass).
    Passwords are held only for this run and never logged.
    """
    def __init__(self, username, oldPassword, newPassword, signals):
        super().__init__()
        self.username = username
        self.oldPassword = oldPassword
        self.newPassword = newPassword
        self.signals = signals

    def run(self):
        result = {'success': [], 'errors': [], 'authFailed': []}
        try:
            from core.Oracle import changePasswordOnAllHdb
            result = changePasswordOnAllHdb(
                username=self.username,
                oldPassword=self.oldPassword,
                newPassword=self.newPassword,
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
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winOptions.ui'), self)
        self.winMain = winMain
        self._passwordChangeSignals = None  # keep alive while worker runs

        # Define controls
        self.cbUTCOffset = self.findChild(QComboBox, 'cbUTCOffset')
        self.qleAQServer = self.findChild(QLineEdit, 'qleAQServer')
        self.qleAQUser = self.findChild(QLineEdit, 'qleAQUser')

        # Replace qleAQPassword with customPasswordEdit
        oldAQPassword = self.findChild(QLineEdit, 'qleAQPassword')

        if oldAQPassword:
            parent = oldAQPassword.parent()
            layout = parent.layout() if parent else None

            if layout:
                index = layout.indexOf(oldAQPassword)

                if index != -1:
                    self.qleAQPassword = Utils.customPasswordEdit(parent)
                    self.qleAQPassword.setObjectName('qleAQPassword')
                    self.qleAQPassword.setPlaceholderText(oldAQPassword.placeholderText())
                    self.qleAQPassword.setMaxLength(oldAQPassword.maxLength())
                    self.qleAQPassword.setAlignment(oldAQPassword.alignment())
                    self.qleAQPassword.setStyleSheet(oldAQPassword.styleSheet())
                    self.qleAQPassword.setEnabled(oldAQPassword.isEnabled())
                    layout.replaceWidget(oldAQPassword, self.qleAQPassword)
                    oldAQPassword.deleteLater()

                    if Config.debug:
                        Logic.logMessage("DEBUG", "Replaced qleAQPassword with customPasswordEdit using layout")
                else:
                    if Config.debug:
                        Logic.logMessage("WARN", "No index for qleAQPassword in layout, using geometry fallback")
            else:
                if Config.debug:
                    Logic.logMessage("WARN", "No layout for qleAQPassword parent, using geometry fallback")

            if not layout or index == -1:
                geom = oldAQPassword.geometry()
                self.qleAQPassword = Utils.customPasswordEdit(parent)
                self.qleAQPassword.setObjectName('qleAQPassword')
                self.qleAQPassword.setPlaceholderText(oldAQPassword.placeholderText())
                self.qleAQPassword.setMaxLength(oldAQPassword.maxLength())
                self.qleAQPassword.setAlignment(oldAQPassword.alignment())
                self.qleAQPassword.setStyleSheet(oldAQPassword.styleSheet())
                self.qleAQPassword.setEnabled(oldAQPassword.isEnabled())
                self.qleAQPassword.setGeometry(geom)
                oldAQPassword.hide()
                oldAQPassword.deleteLater()
                self.qleAQPassword.show()

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Replaced qleAQPassword with customPasswordEdit at geometry {geom.x()},{geom.y()},{geom.width()},{geom.height()}")
        else:
            if Config.debug:
                Logic.logMessage("ERROR", "qleAQPassword not found, cannot replace")

        self.qleTNSNames = self.findChild(QLineEdit, 'qleTNSNames')
        self.rbBOP = self.findChild(QRadioButton, 'rbBOP')
        self.rbEOP = self.findChild(QRadioButton, 'rbEOP')
        self.btnbOptions = self.findChild(QDialogButtonBox, 'btnbOptions')
        self.chkbRetroMode = self.findChild(QCheckBox, 'chkbRetroMode')
        self.chkbQAQC = self.findChild(QCheckBox, 'chkbQAQC')
        self.chkbRawData = self.findChild(QCheckBox, 'chkbRawData')
        self.chkbDebug = self.findChild(QCheckBox, 'chkbDebug')
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
        self.btnShowPassword = self.findChild(QPushButton, 'btnShowPassword')
        self.btnShowOraclePassword = self.findChild(QPushButton, 'btnShowOraclePassword')
        self.qleOracleUser = self.findChild(QLineEdit, 'qleOracleUser')

        # Replace qleOraclePassword with customPasswordEdit
        oldOraclePassword = self.findChild(QLineEdit, 'qleOraclePassword')

        if oldOraclePassword:
            parent = oldOraclePassword.parent()
            layout = parent.layout() if parent else None

            if layout:
                index = layout.indexOf(oldOraclePassword)

                if index != -1:
                    self.qleOraclePassword = Utils.customPasswordEdit(parent)
                    self.qleOraclePassword.setObjectName('qleOraclePassword')
                    self.qleOraclePassword.setPlaceholderText(oldOraclePassword.placeholderText())
                    self.qleOraclePassword.setMaxLength(
                        int(getattr(Config, 'oraclePasswordMaxLength', 30) or 30)
                    )
                    self.qleOraclePassword.setAlignment(oldOraclePassword.alignment())
                    self.qleOraclePassword.setStyleSheet(oldOraclePassword.styleSheet())
                    self.qleOraclePassword.setEnabled(oldOraclePassword.isEnabled())
                    layout.replaceWidget(oldOraclePassword, self.qleOraclePassword)
                    oldOraclePassword.deleteLater()

                    if Config.debug:
                        Logic.logMessage("DEBUG", "Replaced qleOraclePassword with customPasswordEdit using layout")
                else:
                    if Config.debug:
                        Logic.logMessage("WARN", "No index for qleOraclePassword in layout, using geometry fallback")
            else:
                if Config.debug:
                    Logic.logMessage("WARN", "No layout for qleOraclePassword parent, using geometry fallback")

            if not layout or index == -1:
                geom = oldOraclePassword.geometry()
                self.qleOraclePassword = Utils.customPasswordEdit(parent)
                self.qleOraclePassword.setObjectName('qleOraclePassword')
                self.qleOraclePassword.setPlaceholderText(oldOraclePassword.placeholderText())
                self.qleOraclePassword.setMaxLength(
                    int(getattr(Config, 'oraclePasswordMaxLength', 30) or 30)
                )
                self.qleOraclePassword.setAlignment(oldOraclePassword.alignment())
                self.qleOraclePassword.setStyleSheet(oldOraclePassword.styleSheet())
                self.qleOraclePassword.setEnabled(oldOraclePassword.isEnabled())
                self.qleOraclePassword.setGeometry(geom)
                oldOraclePassword.hide()
                oldOraclePassword.deleteLater()
                self.qleOraclePassword.show()

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Replaced qleOraclePassword with customPasswordEdit at geometry {geom.x()},{geom.y()},{geom.width()},{geom.height()}")
        else:
            if Config.debug:
                Logic.logMessage("ERROR", "qleOraclePassword not found, cannot replace")

        self.chkbEnableSQL = self.findChild(QCheckBox, 'chkbEnableSQL')

        # Replace qleUSGSAPIKey with customPasswordEdit
        oldUSGSAPIKey = self.findChild(QLineEdit, 'qleUSGSAPIKey')

        if oldUSGSAPIKey:
            parent = oldUSGSAPIKey.parent()
            layout = parent.layout() if parent else None

            if layout:
                index = layout.indexOf(oldUSGSAPIKey)

                if index != -1:
                    self.qleUSGSAPIKey = Utils.customPasswordEdit(parent)
                    self.qleUSGSAPIKey.setObjectName('qleUSGSAPIKey')
                    self.qleUSGSAPIKey.setPlaceholderText(oldUSGSAPIKey.placeholderText())
                    self.qleUSGSAPIKey.setMaxLength(oldUSGSAPIKey.maxLength())
                    self.qleUSGSAPIKey.setAlignment(oldUSGSAPIKey.alignment())
                    self.qleUSGSAPIKey.setStyleSheet(oldUSGSAPIKey.styleSheet())
                    self.qleUSGSAPIKey.setEnabled(oldUSGSAPIKey.isEnabled())
                    layout.replaceWidget(oldUSGSAPIKey, self.qleUSGSAPIKey)
                    oldUSGSAPIKey.deleteLater()

                    if Config.debug:
                        Logic.logMessage("DEBUG", "Replaced qleUSGSAPIKey with customPasswordEdit using layout")
                else:
                    if Config.debug:
                        Logic.logMessage("WARN", "No index for qleUSGSAPIKey in layout, using geometry fallback")
            else:
                if Config.debug:
                    Logic.logMessage("WARN", "No layout for qleUSGSAPIKey parent, using geometry fallback")

            if not layout or index == -1:
                geom = oldUSGSAPIKey.geometry()
                self.qleUSGSAPIKey = Utils.customPasswordEdit(parent)
                self.qleUSGSAPIKey.setObjectName('qleUSGSAPIKey')
                self.qleUSGSAPIKey.setPlaceholderText(oldUSGSAPIKey.placeholderText())
                self.qleUSGSAPIKey.setMaxLength(oldUSGSAPIKey.maxLength())
                self.qleUSGSAPIKey.setAlignment(oldUSGSAPIKey.alignment())
                self.qleUSGSAPIKey.setStyleSheet(oldUSGSAPIKey.styleSheet())
                self.qleUSGSAPIKey.setEnabled(oldUSGSAPIKey.isEnabled())
                self.qleUSGSAPIKey.setGeometry(geom)
                oldUSGSAPIKey.hide()
                oldUSGSAPIKey.deleteLater()
                self.qleUSGSAPIKey.show()

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Replaced qleUSGSAPIKey with customPasswordEdit at geometry {geom.x()},{geom.y()},{geom.width()},{geom.height()}")
        else:
            if Config.debug:
                Logic.logMessage("ERROR", "qleUSGSAPIKey not found, cannot replace")

        self.btnShowUSGSKey = self.findChild(QPushButton, 'btnShowUSGSKey')

        # Set button style
        Utils.buttonStyle(self.btnShowPassword, None, None)
        Utils.buttonStyle(self.btnShowUSGSKey, None, None)
        Utils.buttonStyle(self.btnShowOraclePassword, None, None)

        # Create events — own the Save path so validation can cancel close
        # (winOptions.ui also connects accepted → accept; disconnect that first)
        try:
            self.btnbOptions.accepted.disconnect()
        except TypeError:
            pass
        self.btnbOptions.accepted.connect(self.onSavePressed)
        self.btnShowPassword.clicked.connect(self.togglePasswordVisibility)
        self.btnShowUSGSKey.clicked.connect(self.toggleUSGSKeyVisibility)
        self.btnShowOraclePassword.clicked.connect(self.toggleOraclePasswordVisibility)

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

        if Config.debug:
            Logic.logMessage("DEBUG", "uiOptions initialized")

    def showEvent(self, event):
        if Config.debug:
            Logic.logMessage("DEBUG", f"uiOptions showEvent")
        Utils.centerWindowToParent(self)
        super().showEvent(event)
        # Mode-specific checkbox positions (default Noto vs retro)
        Utils.applyModeControlLayouts(root=self)
        Utils.applyRoleFonts(root=self)
        self.loadSettings()
        self.tabWidget.setCurrentIndex(0)
        # Always start with secrets masked when the dialog opens
        self.maskSensitiveFields()

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
        self.chkbQAQC.setChecked(bool(config.get('qaqc', True)))

        if Config.debug:
            Logic.logMessage("DEBUG", "Set chkbQAQC to: {}".format(self.chkbQAQC.isChecked()))
        self.chkbRawData.setChecked(bool(config.get('rawData', False)))

        if Config.debug:
            Logic.logMessage("DEBUG", "Set chkbRawData to: {}".format(self.chkbRawData.isChecked()))
        self.chkbDebug.setChecked(bool(config.get('debugMode', False)))

        if Config.debug:
            Logic.logMessage("DEBUG", "Set chkbDebug to: {}".format(self.chkbDebug.isChecked()))
        self.chkbEnableSQL.setChecked(bool(config.get('enableSQL', False)))

        if Config.debug:
            Logic.logMessage("DEBUG", "Set chkbEnableSQL to: {}".format(self.chkbEnableSQL.isChecked()))
        tnsPath = config.get('tnsNamesLocation', '')

        if tnsPath.startswith(Config.appRoot):
            tnsPath = tnsPath.replace(Config.appRoot, '%AppRoot%')
        self.qleTNSNames.setText(tnsPath)

        if not self.qleTNSNames.text():
            envTns = os.environ.get('TNS_ADMIN', Logic.resourcePath('oracle/network/admin'))

            if envTns.startswith(Config.appRoot):
                envTns = envTns.replace(Config.appRoot, '%AppRoot%')
            self.qleTNSNames.setText(envTns)

        if Config.debug:
            Logic.logMessage("DEBUG", "Set qleTNSNames to: {}".format(tnsPath))
        hourMethod = config.get('hourTimestampMethod', 'EOP')

        if hourMethod == 'EOP':
            self.rbEOP.setChecked(True)
        else:
            self.rbBOP.setChecked(True)
        if Config.debug:
            Logic.logMessage("DEBUG", "Set hourTimestampMethod to: {}".format(hourMethod))
        try:
            self.qleAQServer.setText(keyring.get_password("DataDoctor", "aqServer") or "")
            self.qleAQUser.setText(keyring.get_password("DataDoctor", "aqUser") or "")
            self.qleAQPassword.setText(keyring.get_password("DataDoctor", "aqPassword") or "")
            self.qleUSGSAPIKey.setText(keyring.get_password("DataDoctor", "usgsApiKey") or "")
            self.qleOracleUser.setText(keyring.get_password("DataDoctor", "oracleUser") or "")
            self.qleOraclePassword.setText(keyring.get_password("DataDoctor", "oraclePassword") or "")

            if Config.debug:
                Logic.logMessage("DEBUG", "Successfully loaded keyring credentials")
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

        # Password-only change on existing account → push to all HDB databases.
        # Skip when username changed, or when user/password were previously blank
        # (first-time credential entry is local keyring only, not a multi-DB alter).
        hdbPasswordChangeRequested = (
            bool(priorUserStripped)
            and bool(priorOraclePassword)
            and bool(newOracleUser)
            and newOracleUser == priorUserStripped
            and bool(newOraclePassword)
            and newOraclePassword != priorOraclePassword
        )

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
        previousEnableSQL = config.get('enableSQL', False)
        newRetro = self.chkbRetroMode.isChecked()
        newEnableSQL = self.chkbEnableSQL.isChecked()
        tnsPath = self.qleTNSNames.text()

        if '%AppRoot%' in tnsPath:
            tnsPath = tnsPath.replace('%AppRoot%', Config.appRoot)
        hourMethod = 'EOP' if self.rbEOP.isChecked() else 'BOP'
        config.update({
            'utcOffset': self.cbUTCOffset.currentText(),
            'retroMode': newRetro,
            'qaqc': self.chkbQAQC.isChecked(),
            'rawData': self.chkbRawData.isChecked(),
            'debugMode': self.chkbDebug.isChecked(),
            'enableSQL': newEnableSQL,
            'tnsNamesLocation': tnsPath,
            'hourTimestampMethod': hourMethod,
            # Keep periodOffset in sync: EOP = True (end-of-period), BOP = False
            'periodOffset': hourMethod == 'EOP',
            'lastExportPath': config.get('lastExportPath', '')
        })

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2)
        if Config.debug:
            Logic.logMessage("DEBUG", "Saved user.config with retroMode: {}, qaqc: {}, rawData: {}, enableSQL: {}".format(newRetro, self.chkbQAQC.isChecked(), self.chkbRawData.isChecked(), newEnableSQL))
        Utils.reloadGlobals()

        if newRetro != previousRetro:
            reply = QMessageBox.question(
                self, "Retro Mode Change",
                "Restart DataDoctor for the retro mode change to take effect?\nOK to restart now, Cancel to revert to previous setting.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )

            if reply == QMessageBox.StandardButton.Ok:
                # Windows: os.execl often fails (pythonw, paths, launcher). Prefer
                # QProcess.startDetached + clean quit on all platforms.
                restarted = False
                try:
                    from PyQt6.QtCore import QProcess
                    from PyQt6.QtWidgets import QApplication
                    program = sys.executable
                    # sys.argv[0] is the script/module; remaining are extra args
                    arguments = list(sys.argv)
                    cwd = os.getcwd()
                    # startDetached(program, arguments) — arguments include script path
                    ok = QProcess.startDetached(program, arguments, cwd)
                    if ok:
                        restarted = True
                        Logic.logMessage(
                            "INFO",
                            f"Restarting DataDoctor via QProcess.startDetached: {program} {arguments}",
                        )
                        app = QApplication.instance()
                        if app is not None:
                            app.quit()
                        else:
                            sys.exit(0)
                    else:
                        Logic.logMessage(
                            "WARN",
                            "QProcess.startDetached returned False; trying subprocess",
                        )
                except Exception as e:
                    Logic.logException("Retro restart via QProcess failed", e)

                if not restarted:
                    try:
                        import subprocess
                        # close_fds=False is more reliable on Windows
                        kwargs = {}
                        if sys.platform == 'win32':
                            kwargs['close_fds'] = False
                            # DETACHED_PROCESS so child survives parent exit
                            CREATE_NEW_PROCESS_GROUP = 0x00000200
                            DETACHED_PROCESS = 0x00000008
                            kwargs['creationflags'] = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
                        subprocess.Popen([sys.executable] + list(sys.argv), cwd=os.getcwd(), **kwargs)
                        restarted = True
                        Logic.logMessage("INFO", "Restarting DataDoctor via subprocess.Popen")
                        from PyQt6.QtWidgets import QApplication
                        app = QApplication.instance()
                        if app is not None:
                            app.quit()
                        else:
                            sys.exit(0)
                    except Exception as e:
                        Logic.logException("Retro restart via subprocess failed", e)

                if not restarted and sys.platform != 'win32':
                    # Last resort on Unix only (historically reliable there)
                    try:
                        os.execl(sys.executable, sys.executable, *sys.argv)
                    except Exception as e:
                        Logic.logException("Retro restart via os.execl failed", e)

                if not restarted:
                    QMessageBox.warning(
                        self,
                        "Restart Failed",
                        "Could not restart DataDoctor automatically.\n\n"
                        "Please close and reopen the program for retro mode to apply.",
                    )
            else:
                self.chkbRetroMode.setChecked(previousRetro)
                config['retroMode'] = previousRetro

                with open(configPath, 'w', encoding='utf-8') as configFile:
                    json.dump(config, configFile, indent=2)
                Utils.reloadGlobals()

                if Config.debug:
                    Logic.logMessage("DEBUG", "Reverted retro mode to {}".format(previousRetro))

        # Dynamically show/hide SQL tab if enableSQL changed
        if newEnableSQL != previousEnableSQL:
            sqlTab = getattr(self.winMain, 'tabSQL', None) or self.winMain.findChild(QWidget, 'tabSQL')
            if sqlTab:
                self.winMain.tabSQL = sqlTab
                if newEnableSQL:
                    sqlIndex = self.winMain.tabWidget.indexOf(sqlTab)
                    if sqlIndex == -1:
                        insertIndex = 1 if self.winMain.tabWidget.indexOf(self.winMain.tabMain) != -1 else 0
                        self.winMain.tabWidget.insertTab(insertIndex, sqlTab, self.winMain.sqlTitle)
                        self.winMain.refreshSqlTab()
                        if Config.debug:
                            Logic.logMessage("DEBUG", f"Added tabSQL at index {insertIndex} after enableSQL change and refreshed")
                else:
                    sqlIndex = self.winMain.tabWidget.indexOf(sqlTab)
                    if sqlIndex != -1:
                        self.winMain.tabWidget.removeTab(sqlIndex)
                        if Config.debug:
                            Logic.logMessage("DEBUG", "Removed tabSQL after enableSQL change")

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

        # Multi-DB HDB password update (parallel); uses prior password to authenticate
        if hdbPasswordChangeRequested:
            reply = QMessageBox.question(
                self,
                "Update HDB Password",
                "Oracle password update detected.\n\n"
                "Update this password on all USBR HDB databases?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._startHdbPasswordChange(
                    username=newOracleUser,
                    oldPassword=priorOraclePassword,
                    newPassword=newOraclePassword,
                )
            else:
                Logic.logMessage(
                    "INFO",
                    "HDB password change declined by user "
                    "(local Options credentials were still saved)",
                )

        # Close Options (we disconnected the UI auto-accept)
        super().accept()

    def _startHdbPasswordChange(self, username, oldPassword, newPassword):
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
        worker = hdbPasswordChangeWorker(username, oldPassword, newPassword, signals)
        Logic.logMessage(
            "INFO",
            f"Starting HDB password change for user {username} on all USBR databases",
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
            Logic.logMessage(
                "INFO",
                f"HDB password prompt cancelled/skipped for {dbName}",
            )
            state['errors'].append((dbName, 'Skipped (no password entered)'))
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
        Returns the password string, or None if cancelled / empty.
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
            f"<b>{dbName}</b>:",
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

        # Stable order for display (strip |SCHEMA from config keys)
        order = {}
        for i, entry in enumerate(getattr(Config, 'hdbOracleDatabases', ()) or ()):
            name = str(entry).split('|', 1)[0].strip() if entry else ''
            if name:
                order[name] = i
        success.sort(key=lambda n: order.get(n, 999))
        errors.sort(key=lambda pair: order.get(pair[0] if isinstance(pair, (list, tuple)) else str(pair), 999))

        result = {'success': success, 'errors': errors}
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
        """Popup summarizing which DBs changed and which errored (not missing users)."""
        success = list((result or {}).get('success') or [])
        errors = list((result or {}).get('errors') or [])

        if not success and not errors:
            # Nothing changed and nothing reported (all silent missing, or no targets)
            Logic.logMessage(
                "INFO",
                "HDB password change: no databases updated",
            )
            revertNote = (
                "\n\nYour previous password was restored in Options."
                if passwordReverted
                else "\n\nCould not restore the previous password automatically; "
                     "re-enter it in Options → USBR if needed."
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
            "HDB password change results: changed on [{}]; errors on [{}]{}".format(
                ', '.join(success) if success else 'none',
                ', '.join(
                    (e[0] if isinstance(e, (list, tuple)) and e else str(e))
                    for e in errors
                ) if errors else 'none',
                '; local password reverted' if (not success and passwordReverted) else '',
            ),
        )

        QMessageBox.information(parent, "HDB Password Update", '\n'.join(lines).rstrip())