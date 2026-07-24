# uiOptions.py

import os
import sys
import json
import keyring
from PyQt6.QtWidgets import QDialog, QComboBox, QLineEdit, QRadioButton, QDialogButtonBox, QCheckBox, QPushButton, QTabWidget, QMessageBox, QWidget
from PyQt6.QtCore import QTimer, QEvent
from PyQt6.QtGui import QIcon
from PyQt6 import uic
from core import Logic, Utils, Config

class uiOptions(QDialog):
    """Options editor: Stores database connection information and application settings."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winOptions.ui'), self)
        self.winMain = winMain

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
                    self.qleOraclePassword.setMaxLength(oldOraclePassword.maxLength())
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
                self.qleOraclePassword.setMaxLength(oldOraclePassword.maxLength())
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

        # Create events
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
        self.loadSettings()
        self.tabWidget.setCurrentIndex(0)

        if Config.debug:
            Logic.logMessage("DEBUG", "uiOptions showEvent")    

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
                python = sys.executable
                os.execl(python, python, *sys.argv)
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
            ("oracleUser", self.qleOracleUser.text()),
            ("oraclePassword", self.qleOraclePassword.text())
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