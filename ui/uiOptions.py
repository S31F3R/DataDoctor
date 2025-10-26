import os
import sys
import json
import keyring
from PyQt6.QtWidgets import QDialog, QComboBox, QLineEdit, QRadioButton, QDialogButtonBox, QCheckBox, QPushButton, QTabWidget, QMessageBox
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
        self.qleAQPassword = self.findChild(QLineEdit, 'qleAQPassword')
        self.qleUSGSAPIKey = self.findChild(QLineEdit, 'qleUSGSAPIKey')
        self.qleTNSNames = self.findChild(QLineEdit, 'qleTNSNames')
        self.rbBOP = self.findChild(QRadioButton, 'rbBOP')
        self.rbEOP = self.findChild(QRadioButton, 'rbEOP')
        self.btnbOptions = self.findChild(QDialogButtonBox, 'btnbOptions')
        self.cbRetroMode = self.findChild(QCheckBox, 'cbRetroMode')
        self.cbQAQC = self.findChild(QCheckBox, 'cbQAQC')
        self.cbRawData = self.findChild(QCheckBox, 'cbRawData')
        self.cbDebug = self.findChild(QCheckBox, 'cbDebug')
        self.tabWidget = self.findChild(QTabWidget, 'tabWidget')
        self.btnShowPassword = self.findChild(QPushButton, 'btnShowPassword')
        self.btnShowUSGSKey = self.findChild(QPushButton, 'btnShowUSGSKey')
        self.qleOracleUser = self.findChild(QLineEdit, 'qleOracleUser')
        self.qleOraclePassword = self.findChild(QLineEdit, 'qleOraclePassword')
        self.btnShowOraclePassword = self.findChild(QPushButton, 'btnShowOraclePassword')

        # Set button style
        Utils.buttonStyle(self.btnShowPassword)
        Utils.buttonStyle(self.btnShowUSGSKey)
        Utils.buttonStyle(self.btnShowOraclePassword)

        # Timers for password and key show
        self.lastCharTimer = QTimer(self)
        self.lastCharTimer.setSingleShot(True)
        self.lastCharTimer.timeout.connect(self.maskLastChar)
        self.lastCharTimerUSGS = QTimer(self)
        self.lastCharTimerUSGS.setSingleShot(True)
        self.lastCharTimerUSGS.timeout.connect(self.maskLastCharUSGS)
        self.lastCharTimerOracle = QTimer(self)
        self.lastCharTimerOracle.setSingleShot(True)
        self.lastCharTimerOracle.timeout.connect(self.maskLastCharOracle)

        # Create events
        self.btnbOptions.accepted.connect(self.onSavePressed)
        self.btnShowPassword.clicked.connect(self.togglePasswordVisibility)
        self.btnShowUSGSKey.clicked.connect(self.toggleUSGSKeyVisibility)
        self.btnShowOraclePassword.clicked.connect(self.toggleOraclePasswordVisibility)

        # Mask password and key
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)
        self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password)
        self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Password)

        # Install event filters
        self.qleAQPassword.installEventFilter(self)
        self.qleUSGSAPIKey.installEventFilter(self)
        self.qleOraclePassword.installEventFilter(self)

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
            print("[DEBUG] uiOptions initialized")

    def showEvent(self, event):
        if Config.debug:
            print(f"[DEBUG] uiOptions showEvent")

        Utils.centerWindowToParent(self)
        super().showEvent(event)
        self.loadSettings()
        self.tabWidget.setCurrentIndex(0)

        if Config.debug:
            print("[DEBUG] uiOptions showEvent")

    def eventFilter(self, obj, event):
        if obj == self.qleAQPassword and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimer.isActive():
                self.lastCharTimer.stop()

            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimer.start(500)

            if Config.debug:
                print("[DEBUG] AQ password keypress, showing temporarily")
        elif obj == self.qleUSGSAPIKey and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimerUSGS.isActive():
                self.lastCharTimerUSGS.stop()

            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerUSGS.start(500)

            if Config.debug:
                print("[DEBUG] USGS API key keypress, showing temporarily")
        elif obj == self.qleOraclePassword and event.type() == QEvent.Type.KeyPress:
            if self.lastCharTimerOracle.isActive():
                self.lastCharTimerOracle.stop()

            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerOracle.start(500)

            if Config.debug:
                print("[DEBUG] Oracle password keypress, showing temporarily")
        elif obj == self.qleAQPassword and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimer.isActive():
                self.lastCharTimer.stop()

            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimer.start(500)

            if Config.debug:
                print("[DEBUG] AQ password paste, showing temporarily")
        elif obj == self.qleUSGSAPIKey and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimerUSGS.isActive():
                self.lastCharTimerUSGS.stop()

            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerUSGS.start(500)

            if Config.debug:
                print("[DEBUG] USGS API key paste, showing temporarily")
        elif obj == self.qleOraclePassword and event.type() == QEvent.Type.InputMethod:
            if self.lastCharTimerOracle.isActive():
                self.lastCharTimerOracle.stop()

            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.lastCharTimerOracle.start(500)

            if Config.debug:
                print("[DEBUG] Oracle password paste, showing temporarily")
        return super().eventFilter(obj, event)

    def maskLastChar(self):
        self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)
        if Config.debug:
            print("[DEBUG] AQ password re-masked")

    def maskLastCharUSGS(self):
        self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password)
        if Config.debug:
            print("[DEBUG] USGS API key re-masked")

    def maskLastCharOracle(self):
        self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Password)
        if Config.debug:
            print("[DEBUG] Oracle password re-masked")

    def togglePasswordVisibility(self):
        if self.lastCharTimer.isActive():
            self.lastCharTimer.stop()

        if self.qleAQPassword.echoMode() == QLineEdit.EchoMode.Password:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))

            if Config.debug:
                print("[DEBUG] AQ password shown via button")
        else:
            self.qleAQPassword.setEchoMode(QLineEdit.EchoMode.Password)
            self.btnShowPassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

            if Config.debug:
                print("[DEBUG] AQ password masked via button")

    def toggleUSGSKeyVisibility(self):
        if self.lastCharTimerUSGS.isActive():
            self.lastCharTimerUSGS.stop()
            
        if self.qleUSGSAPIKey.echoMode() == QLineEdit.EchoMode.Password:
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))

            if Config.debug:
                print("[DEBUG] USGS API key shown via button")
        else:
            self.qleUSGSAPIKey.setEchoMode(QLineEdit.EchoMode.Password)
            self.btnShowUSGSKey.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

            if Config.debug:
                print("[DEBUG] USGS API key masked via button")

    def toggleOraclePasswordVisibility(self):
        if self.lastCharTimerOracle.isActive():
            self.lastCharTimerOracle.stop()

        if self.qleOraclePassword.echoMode() == QLineEdit.EchoMode.Password:
            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btnShowOraclePassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Hidden.png')))

            if Config.debug:
                print("[DEBUG] Oracle password shown via button")
        else:
            self.qleOraclePassword.setEchoMode(QLineEdit.EchoMode.Password)
            self.btnShowOraclePassword.setIcon(QIcon(Logic.resourcePath('ui/icons/Visible.png')))

            if Config.debug:
                print("[DEBUG] Oracle password masked via button")

    def loadSettings(self):
        configPath = Utils.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    print("[DEBUG] Loaded config from user.config: {}".format(config))
            except Exception as e:
                if Config.debug:
                    print("[ERROR] Failed to load user.config: {}".format(e))
        utcOffset = config.get('utcOffset', "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London")
        index = self.cbUTCOffset.findText(utcOffset)

        if index != -1:
            self.cbUTCOffset.setCurrentIndex(index)
            if Config.debug:
                print("[DEBUG] Set cbUTCOffset to: {}".format(utcOffset))
        else:
            self.cbUTCOffset.setCurrentIndex(14)
            if Config.debug:
                print("[DEBUG] utcOffset '{}' not found, set to default UTC+00:00".format(utcOffset))                
        self.cbRetroMode.setChecked(bool(config.get('retroMode', True)))        
        if Config.debug:
            print("[DEBUG] Set cbRetroMode to: {}".format(self.cbRetroMode.isChecked()))

        self.cbQAQC.setChecked(bool(config.get('qaqc', True)))
        if Config.debug:
            print("[DEBUG] Set cbQAQC to: {}".format(self.cbQAQC.isChecked()))

        self.cbRawData.setChecked(bool(config.get('rawData', False)))
        if Config.debug:
            print("[DEBUG] Set cbRawData to: {}".format(self.cbRawData.isChecked()))

        self.cbDebug.setChecked(bool(config.get('debugMode', False)))
        if Config.debug:
            print("[DEBUG] Set cbDebug to: {}".format(self.cbDebug.isChecked()))

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
            print("[DEBUG] Set qleTNSNames to: {}".format(tnsPath))
        hourMethod = config.get('hourTimestampMethod', 'EOP')

        if hourMethod == 'EOP':
            self.rbEOP.setChecked(True)
        else:
            self.rbBOP.setChecked(True)
        if Config.debug:
            print("[DEBUG] Set hourTimestampMethod to: {}".format(hourMethod))
        try:
            self.qleAQServer.setText(keyring.get_password("DataDoctor", "aqServer") or "")
            self.qleAQUser.setText(keyring.get_password("DataDoctor", "aqUser") or "")
            self.qleAQPassword.setText(keyring.get_password("DataDoctor", "aqPassword") or "")
            self.qleUSGSAPIKey.setText(keyring.get_password("DataDoctor", "usgsApiKey") or "")
            self.qleOracleUser.setText(keyring.get_password("DataDoctor", "oracleUser") or "")
            self.qleOraclePassword.setText(keyring.get_password("DataDoctor", "oraclePassword") or "")

            if Config.debug:
                print("[DEBUG] Successfully loaded keyring credentials")
        except Exception as e:
            if Config.debug:
                print("[ERROR] Failed to load keyring credentials: {}. Using empty strings".format(e))
            self.qleAQServer.setText("")
            self.qleAQUser.setText("")
            self.qleAQPassword.setText("")
            self.qleUSGSAPIKey.setText("")
            self.qleOracleUser.setText("")
            self.qleOraclePassword.setText("")
        if Config.debug:
            print("[DEBUG] Settings loaded")

    def onSavePressed(self):
        configPath = Utils.getConfigPath()
        config = {}

        if os.path.exists(configPath):
            try:
                with open(configPath, 'r', encoding='utf-8') as configFile:
                    config = json.load(configFile)
                if Config.debug:
                    print("[DEBUG] Read existing user.config: {}".format(config))
            except Exception as e:
                if Config.debug:
                    print("[ERROR] Failed to load user.config for save: {}".format(e))
        previousRetro = config.get('retroMode', True)
        newRetro = self.cbRetroMode.isChecked()
        tnsPath = self.qleTNSNames.text()

        if '%AppRoot%' in tnsPath:
            tnsPath = tnsPath.replace('%AppRoot%', Config.appRoot)
        config.update({
            'utcOffset': self.cbUTCOffset.currentText(),
            'retroMode': newRetro,
            'qaqc': self.cbQAQC.isChecked(),
            'rawData': self.cbRawData.isChecked(),
            'debugMode': self.cbDebug.isChecked(),
            'tnsNamesLocation': tnsPath,
            'hourTimestampMethod': 'EOP' if self.rbEOP.isChecked() else 'BOP',
            'lastExportPath': config.get('lastExportPath', '')
        })

        with open(configPath, 'w', encoding='utf-8') as configFile:
            json.dump(config, configFile, indent=2)
        if Config.debug:
            print("[DEBUG] Saved user.config with retroMode: {}".format(newRetro))
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
                self.cbRetroMode.setChecked(previousRetro)
                config['retroMode'] = previousRetro

                with open(configPath, 'w', encoding='utf-8') as configFile:
                    json.dump(config, configFile, indent=2)
                Utils.reloadGlobals()

                if Config.debug:
                    print("[DEBUG] Reverted retro mode to {}".format(previousRetro))
        credentials = [
            ("aqServer", self.qleAQServer.text()),
            ("aqUser", self.qleAQUser.text()),
            ("aqPassword", self.qleAQPassword.text()),
            ("usgsApiKey", self.qleUSGSAPIKey.text()),
            ("oracleUser", self.qleOracleUser.text()),
            ("oraclePassword", self.qleOraclePassword.text())
        ]

        for key, value in credentials:
            if value and isinstance(value, str) and value.strip():
                try:
                    keyring.set_password("DataDoctor", key, value)

                    if Config.debug:
                        print("[DEBUG] Saved {} to keyring".format(key))
                except Exception as e:
                    if Config.debug:
                        print("[ERROR] Failed to save {} to keyring: {}".format(key, e))
                    QMessageBox.warning(self, "Credential Save Error", "Failed to save {}: {}".format(key, e))
            elif Config.debug:
                print("[DEBUG] Skipped saving {} to keyring: empty or invalid".format(key))