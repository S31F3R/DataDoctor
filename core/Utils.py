# Utils.py

import os
import json
import configparser
from PyQt6.QtCore import Qt, QStandardPaths, QSize, QObject, QEvent, QTimer
from PyQt6.QtWidgets import QWidget, QLineEdit
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QPixmap
from core import Logic, Config, Utils

class customPasswordEdit(QLineEdit):
    """Password field using Qt's native echo modes (no dual realText/display bookkeeping).

    Masked   -> EchoMode.Password  (paste, type, backspace all handled by Qt; never clear text)
    Revealed -> EchoMode.Normal

    Previous approach manually painted mask characters while keeping EchoMode.Normal.
    On some platforms paste still wrote clear text into the widget without updating the
    parallel realText store, so typing/backspace then wiped or desynced the password.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.revealed = False
        self.setEchoMode(QLineEdit.EchoMode.Password)

        if Config.debug:
            Logic.logMessage("DEBUG", "customPasswordEdit initialized (native Password echo mode)")

    def setText(self, text):
        super().setText(text if text is not None else '')
        self.applyEchoMode()

    def applyEchoMode(self):
        self.setEchoMode(
            QLineEdit.EchoMode.Normal if self.revealed else QLineEdit.EchoMode.Password
        )

    def toggleReveal(self):
        self.revealed = not self.revealed
        self.applyEchoMode()

        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Reveal toggled: revealed={self.revealed}, len={len(self.text())}"
            )

    def setMasked(self, masked=True):
        """Force masked (True) or revealed (False) state."""
        self.revealed = not masked
        self.applyEchoMode()

    def isRevealed(self):
        return self.revealed

def applyStylesAndFonts(app, mainTable, queryList):
    """Apply stylesheet and retro font if enabled."""
    with open(Logic.resourcePath('ui/stylesheet.qss'), 'r') as f:
        app.setStyleSheet(f.read())
    config = loadConfig()
    Config.debug = config['debugMode']
    Config.utcOffset = config['utcOffset']
    Config.periodOffset = resolvePeriodOffset(config)
    Config.retroMode = config.get('retroMode', True)
    if Config.retroMode:
        fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
        fontId = QFontDatabase.addApplicationFont(fontPath)
        if fontId != -1:
            fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
            retroFontObj = QFont(fontFamily, 10)
            retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
            app.setFont(retroFontObj)
            if Config.debug:
                Logic.logMessage("DEBUG", "Applied retro font at startup")
        setRetroStyles(app, True, mainTable, queryList)
    else:
        setRetroStyles(app, False, mainTable, queryList)

def loadDataDictionary(table):
    """Load the data dictionary into the provided table."""
    Logic.buildDataDictionary(table)

def loadQuickLooks(cbQuickLook):
    """Load all Quick Looks into the provided combobox."""
    Logic.loadAllQuickLooks(cbQuickLook)

def loadDatabase(comboBox, queryType=None):
    """Populate the database combo box with static databases."""
    if comboBox:
        if Config.debug:
            Logic.logMessage("DEBUG", "Populating cbDatabase")
        comboBox.clear()

        if queryType == 'internal' and queryType != 'sql': 
            comboBox.addItem('AQUARIUS')

        # Populate database combobox        
        comboBox.addItem('USBR-LCHDB')
        comboBox.addItem('USBR-YAOHDB')
        comboBox.addItem('USBR-UCHDB2')
        comboBox.addItem('USBR-ECOHDB')
        comboBox.addItem('USBR-LBOHDB')
        comboBox.addItem('USBR-KBOHDB')

        if queryType != 'sql':
            comboBox.addItem('USGS-NWIS')
            comboBox.addItem('USBR-PNHYD')
            comboBox.addItem('USBR-GPHYD')

        if Config.debug:
            Logic.logMessage("DEBUG", f"Populated cbDatabase with {comboBox.count()} items")
    else:
        if Config.debug:
            Logic.logMessage("ERROR", "cbDatabase is None, cannot populate")

def buttonStyle(button, iconName=None, iconSize=None):
    """Apply flat, borderless style to a QPushButton with hover/press effects using resized icons if iconName provided."""
    if iconName:
        normalPath = Logic.resourcePath(f'ui/icons/{iconName}.png')
        hoverPath = Logic.resourcePath(f'ui/icons/hoover/{iconName}.png')
        pressedPath = Logic.resourcePath(f'ui/icons/pressed/{iconName}.png')

        # Load and resize pixmaps if paths exist
        normalPixmap = QPixmap(normalPath)
        hoverPixmap = QPixmap(hoverPath)
        pressedPixmap = QPixmap(pressedPath)

        if normalPixmap.isNull():
            Logic.logMessage("WARN", f"Missing normal icon for {iconName} at {normalPath}")
            normalPixmap = QPixmap()  # Empty fallback
        if hoverPixmap.isNull():
            Logic.logMessage("WARN", f"Missing hover icon for {iconName} at {hoverPath}")
            hoverPixmap = normalPixmap  # Fallback to normal
        if pressedPixmap.isNull():
            Logic.logMessage("WARN", f"Missing pressed icon for {iconName} at {pressedPath}")
            pressedPixmap = normalPixmap  # Fallback to normal

        # Resize if iconSize provided
        if iconSize and isinstance(iconSize, int) and iconSize > 0:
            normalPixmap = normalPixmap.scaled(iconSize, iconSize, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            hoverPixmap = hoverPixmap.scaled(iconSize, iconSize, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pressedPixmap = pressedPixmap.scaled(iconSize, iconSize, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            button.setIconSize(QSize(iconSize, iconSize))  # For icon-only buttons

        # Set initial icon
        button.setIcon(QIcon(normalPixmap))

        # Define local event filter for state swaps
        class ButtonEventFilter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Enter:
                    obj.setIcon(QIcon(hoverPixmap))
                elif event.type() == QEvent.Type.Leave:
                    obj.setIcon(QIcon(normalPixmap))
                elif event.type() == QEvent.Type.MouseButtonPress:
                    obj.setIcon(QIcon(pressedPixmap))
                elif event.type() == QEvent.Type.MouseButtonRelease:
                    obj.setIcon(QIcon(hoverPixmap if obj.underMouse() else normalPixmap))
                return super().eventFilter(obj, event)

        # Install filter (remove any existing to avoid duplicates)
        button.removeEventFilter(button)
        button.installEventFilter(ButtonEventFilter(button))

        # Apply flat stylesheet
        button.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: transparent;
                border: none;
            }
            QPushButton:focus {
                outline: none;
            }
        """)

        if Config.debug:
            sizeInfo = f" with resized: {iconSize}x{iconSize}" if iconSize else ""
            Logic.logMessage("DEBUG", f"Applied hover/pressed icon swaps to button with icon: {iconName}{sizeInfo}")
    else:
        button.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background: transparent;
            }
            QPushButton:pressed {
                background: transparent;
                border: none;
            }
            QPushButton:focus {
                outline: none;
            }
        """)

        if Config.debug:
            Logic.logMessage("DEBUG", "Applied basic flat style to button (no icon effects)")

def centerWindowToParent(ui):
    """Center a window relative to its parent (main window), robust for multi-monitor."""
    parent = ui.parent()
    if parent is None and hasattr(ui, 'winMain'):
        parent = ui.winMain
    if parent:
        # Get parent's screen for centering (multi-monitor aware)
        parentCenterPoint = parent.geometry().center()
        parentScreen = QGuiApplication.screenAt(parentCenterPoint)

        # Use parent's frame center for precise relative positioning
        parentCenter = parent.frameGeometry().center()

        # Fallback if null (invalid)
        if parentCenter.isNull():
            if parentScreen:
                parentCenter = parentScreen.availableGeometry().center()
            else:
                parentCenter = QGuiApplication.primaryScreen().availableGeometry().center()
    else:
        # No parent: Center on primary
        parentCenter = QGuiApplication.primaryScreen().availableGeometry().center()

    # Center child's frame on parent's center
    rect = ui.frameGeometry()
    rect.moveCenter(parentCenter)
    ui.move(rect.topLeft())

    if Config.debug:
        Logic.logMessage("DEBUG", f"centerWindowToParent: Centered {ui.objectName()} at {rect.topLeft().x()},{rect.topLeft().y()}")

def applyRetroFont(widget, pointSize=10):
    if Config.retroMode:
        fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
        fontId = QFontDatabase.addApplicationFont(fontPath)

        if fontId != -1:
            fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
            retroFontObj = QFont(fontFamily, pointSize)
            retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
            widget.setFont(retroFontObj)

            for child in widget.findChildren(QWidget):
                child.setFont(retroFontObj)
            if Config.debug:
                Logic.logMessage("DEBUG", f"Applied retro font to widget: {widget.objectName()}")
        else:
            if Config.debug:
                Logic.logMessage("ERROR", f"Failed to load retro font from {fontPath}")
    else:
        widget.setFont(QFont())

        for child in widget.findChildren(QWidget):
            child.setFont(QFont())
        if Config.debug:
            Logic.logMessage("DEBUG", f"Reverted widget {widget.objectName()} to system font")

def thickScrollBarStyle(retro=None, minHandle=48, track=20):
    """
    Scrollbar stylesheet with a grab-able handle (needed for tables with tens of
    thousands of rows). Uses neon green when retro mode is on.
    """
    if retro is None:
        retro = bool(getattr(Config, 'retroMode', True))
    handle = "#00FF00" if retro else "#6a6a6a"
    handleHover = "#66FF66" if retro else "#8a8a8a"
    trackBg = "#333333" if retro else "#2a2a2a"
    return f"""
        QScrollBar:vertical {{
            width: {track}px;
            margin: 0px;
            background: {trackBg};
        }}
        QScrollBar::handle:vertical {{
            min-height: {minHandle}px;
            background: {handle};
            border-radius: 4px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {handleHover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            height: {max(track - 4, 14)}px;
            background: {trackBg};
        }}
        QScrollBar::handle:horizontal {{
            min-width: {minHandle}px;
            background: {handle};
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {handleHover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
    """


def setRetroStyles(app, enable, mainTable=None, webQueryList=None, internalQueryList=None):
    """Apply or remove retro mode styles (e.g., scroll bars) dynamically."""
    # Global app scrollbars: neon green, slightly thicker than stock for grab-ability
    retroStyles = """
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #00FF00; /* Neon green handle */
            border-radius: 4px;
            min-height: 24px;
            min-width: 24px;
        }
        QScrollBar:vertical {
            background: #333333; /* Dark track for contrast */
            width: 14px;
        }
        QScrollBar:horizontal {
            background: #333333;
            height: 14px;
        }
    """
    if enable:
        # Apply to specific widgets
        for widget in [mainTable, webQueryList, internalQueryList]:
            if widget:
                widget.setStyleSheet(retroStyles)

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Applied retro scroll bar styles to {widget.objectName()}")
        app.setStyleSheet(app.styleSheet() + retroStyles)

        if Config.debug:
            Logic.logMessage("DEBUG", "Applied retro scroll bar styles globally")
    else:
        # Reset to base stylesheet
        with open(Logic.resourcePath('ui/stylesheet.qss'), 'r') as f:
            app.setStyleSheet(f.read())
        for widget in [mainTable, webQueryList, internalQueryList]:
            if widget:
                widget.setStyleSheet("")

                if Config.debug:
                    Logic.logMessage("DEBUG", f"Cleared retro scroll bar styles from {widget.objectName()}")
        if Config.debug:
            Logic.logMessage("DEBUG", "Reverted to base stylesheet")

def resolvePeriodOffset(config):
    """
    BOP/EOP UI saves hourTimestampMethod; runtime USBR code uses Config.periodOffset.
    EOP (end of period) => periodOffset True; BOP => False.
    Prefer hourTimestampMethod when present so Options radios drive behavior.
    """
    method = config.get('hourTimestampMethod')
    if method in ('EOP', 'BOP'):
        return method == 'EOP'
    return bool(config.get('periodOffset', True))

def loadConfig():
    convertConfigToJson()
    configPath = getConfigPath()
    defaults = {
        'lastExportPath': '',
        'debugMode': False,
        'utcOffset': 'UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London',
        'periodOffset': True,
        'hourTimestampMethod': 'EOP',
        'retroMode': False,
        'qaqc': True,
        'rawData': False,
        'lastQuickLook': '',
        'enableSQL': False
    }

    if os.path.exists(configPath):
        try:
            with open(configPath, 'r', encoding='utf-8') as configFile:
                config = json.load(configFile)
            if Config.debug:
                Logic.logMessage("DEBUG", f"Loaded config: {config}")

            # Migrate integer utcOffset and retroFont
            utcOffset = config.get('utcOffset', defaults['utcOffset'])
            if isinstance(utcOffset, (int, float)):
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Migrating integer utcOffset {utcOffset} to full string")
                offsetMap = {
                    -12: "UTC-12:00 | Baker Island",
                    -11: "UTC-11:00 | American Samoa",
                    -10: "UTC-10:00 | Hawaii",
                    -9.5: "UTC-09:30 | Marquesas Islands",
                    -9: "UTC-09:00 | Alaska",
                    -8: "UTC-08:00 | Pacific Time (US & Canada)",
                    -7: "UTC-07:00 | Mountain Time (US & Canada)/Arizona",
                    -6: "UTC-06:00 | Central Time (US & Canada)",
                    -5: "UTC-05:00 | Eastern Time (US & Canada)",
                    -4: "UTC-04:00 | Atlantic Time (Canada)",
                    -3.5: "UTC-03:30 | Newfoundland",
                    -3: "UTC-03:00 | Brasilia",
                    -2: "UTC-02:00 | Mid-Atlantic",
                    -1: "UTC-01:00 | Cape Verde Is.",
                    0: "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London",
                    1: "UTC+01:00 | Central European Time : Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
                    2: "UTC+02:00 | Eastern European Time : Athens, Bucharest, Istanbul",
                    3: "UTC+03:00 | Moscow, St. Petersburg, Volgograd",
                    3.5: "UTC+03:30 | Tehran",
                    4: "UTC+04:00 | Abu Dhabi, Muscat",
                    4.5: "UTC+04:30 | Kabul",
                    5: "UTC+05:00 | Islamabad, Karachi, Tashkent",
                    5.5: "UTC+05:30 | Chennai, Kolkata, Mumbai, New Delhi",
                    5.75: "UTC+05:45 | Kathmandu",
                    6: "UTC+06:00 | Astana, Dhaka",
                    6.5: "UTC+06:30 | Yangon (Rangoon)",
                    7: "UTC+07:00 | Bangkok, Hanoi, Jakarta",
                    8: "UTC+08:00 | Beijing, Chongqing, Hong Kong, Urumqi",
                    8.75: "UTC+08:45 | Eucla",
                    9: "UTC+09:00 | Osaka, Sapporo, Tokyo",
                    9.5: "UTC+09:30 | Adelaide, Darwin",
                    10: "UTC+10:00 | Brisbane, Canberra, Melbourne, Sydney",
                    10.5: "UTC+10:30 | Lord Howe Island",
                    11: "UTC+11:00 | Solomon Is., New Caledonia",
                    12: "UTC+12:00 | Auckland, Wellington",
                    12.75: "UTC+12:45 | Chatham Islands",
                    13: "UTC+13:00 | Samoa",
                    14: "UTC+14:00 | Kiritimati"
                }
                utcOffset = offsetMap.get(utcOffset, defaults['utcOffset'])
                config['utcOffset'] = utcOffset
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Migrated utcOffset to: {utcOffset}")
            if 'retroFont' in config:
                if Config.debug:
                    Logic.logMessage("DEBUG", "Migrating retroFont to retroMode")
                config['retroMode'] = config.pop('retroFont')
                if Config.debug:
                    Logic.logMessage("DEBUG", f"Migrated retroMode to: {config['retroMode']}")
            if 'colorMode' in config:
                if Config.debug:
                    Logic.logMessage("DEBUG", "Removing obsolete colorMode")
                config.pop('colorMode')

            # Check os env for existing TNS_ADMIN
            envTns = os.environ.get('TNS_ADMIN')

            # If existing TNS_ADMIN, overwrite config TNS_ADMIN location
            if envTns:
                config['tnsNamesLocation'] = envTns

            # Write updated config back to file if migrations occurred
            with open(configPath, 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Loaded full config: {config}")

            return config
        except Exception as e:
            Logic.logException("Failed to load user.config; using defaults", e)
            return defaults
    else:
        try:
            with open(configPath, 'w', encoding='utf-8') as configFile:
                json.dump(defaults, configFile, indent=2)
            if Config.debug:
                Logic.logMessage("DEBUG", f"Created default user.config with defaults: {defaults}")
        except Exception as e:
            Logic.logException("Failed to create default user.config", e)
        return defaults

def getConfigPath():
    configDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)

    if not os.path.exists(configDir):
        os.makedirs(configDir)
    return os.path.join(configDir, "user.config")

def getQuickLookDir():
    quickLookDir = os.path.join(getConfigDir(), "quickLook")
    queryDir = os.path.join(quickLookDir, "query")

    if not os.path.exists(quickLookDir):
        os.makedirs(quickLookDir)

        if Config.debug:
            Logic.logMessage("DEBUG", f"getQuickLookDir: Created quickLook directory: {quickLookDir}")
    if not os.path.exists(queryDir):        
        os.makedirs(queryDir)

        if Config.debug:
            Logic.logMessage("DEBUG", f"getQuickLookDir: Created query subfolder: {queryDir}")

    # Migrate existing .txt files from quickLook root to query subfolder
    for file in os.listdir(quickLookDir):
        if file.endswith(".txt"):
            srcPath = os.path.join(quickLookDir, file)
            dstPath = os.path.join(queryDir, file)

            if os.path.isfile(srcPath) and not os.path.exists(dstPath):
                try:
                    os.rename(srcPath, dstPath)
                    if Config.debug:
                        Logic.logMessage("DEBUG", f"getQuickLookDir: Moved {srcPath} to {dstPath}")
                except Exception as e:
                    if Config.debug:
                        Logic.logMessage("ERROR", f"getQuickLookDir: Failed to move {srcPath} to {dstPath}: {e}")
            elif os.path.exists(dstPath):
                if Config.debug:
                    Logic.logMessage("DEBUG", f"getQuickLookDir: Skipped moving {srcPath} as it already exists in {queryDir}")
    return queryDir

def getExampleQuickLookDir():
    return Logic.resourcePath("quickLook")

def convertConfigToJson():
    oldConfigPath = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation), "config.ini")
    newConfigPath = getConfigPath()

    if os.path.exists(oldConfigPath) and not os.path.exists(newConfigPath):
        config = configparser.ConfigParser()
        config.read(oldConfigPath)

        if Config.debug:
            Logic.logMessage("DEBUG", "Found config.ini, converting to user.config")
        settings = {
            'utcOffset': "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London",
            'retroFont': True,
            'qaqc': True,
            'rawData': False,
            'debugMode': False,
            'tnsNamesLocation': '',
            'hourTimestampMethod': 'EOP',
            'lastQuickLook': '',
            'colorMode': 'light',
            'lastExportPath': ''
        }

        if 'Settings' in config:
            settings['utcOffset'] = config['Settings'].get('utcOffset', settings['utcOffset'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted utcOffset: {settings['utcOffset']}")

            settings['retroFont'] = config['Settings'].getboolean('retroFont', settings['retroFont'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted retroFont: {settings['retroFont']}")

            settings['qaqc'] = config['Settings'].getboolean('qaqc', settings['qaqc'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted qaqc: {settings['qaqc']}")

            settings['rawData'] = config['Settings'].getboolean('rawData', settings['rawData'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted rawData: {settings['rawData']}")

            settings['debugMode'] = config['Settings'].getboolean('debugMode', settings['debugMode'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted debugMode: {settings['debugMode']}")

            settings['tnsNamesLocation'] = config['Settings'].get('tnsNamesLocation', settings['tnsNamesLocation'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted tnsNamesLocation: {settings['tnsNamesLocation']}")

            settings['hourTimestampMethod'] = config['Settings'].get('hourTimestampMethod', settings['hourTimestampMethod'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted hourTimestampMethod: {settings['hourTimestampMethod']}")

            settings['lastQuickLook'] = config['Settings'].get('lastQuickLook', settings['lastQuickLook'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted lastQuickLook: {settings['lastQuickLook']}")

            settings['colorMode'] = config['Settings'].get('colorMode', settings['colorMode'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted colorMode: {settings['colorMode']}")

            settings['lastExportPath'] = config['Settings'].get('lastExportPath', settings['lastExportPath'])
            if Config.debug:
                Logic.logMessage("DEBUG", f"Converted lastExportPath: {settings['lastExportPath']}")

        with open(newConfigPath, 'w', encoding='utf-8') as configFile:
            json.dump(settings, configFile, indent=2)
        if Config.debug:
            Logic.logMessage("DEBUG", "Converted config.ini to user.config")
    elif Config.debug:
        Logic.logMessage("DEBUG", "No config.ini found or user.config exists, skipping conversion")

def reloadGlobals():
    settings = loadConfig()
    Config.debug = settings['debugMode']
    Config.utcOffset = settings['utcOffset']
    Config.periodOffset = resolvePeriodOffset(settings)
    Config.retroMode = settings['retroMode']
    Config.qaqcEnabled = settings['qaqc']
    Config.rawData = settings['rawData']
    Config.enableSQL = settings['enableSQL']

    if Config.debug:
        Logic.logMessage("DEBUG", f"Globals reloaded from user.config, enableSQL={Config.enableSQL}, periodOffset={Config.periodOffset}, hourTimestampMethod={settings.get('hourTimestampMethod')}")

def getConfigDir():
    configDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    
    if not os.path.exists(configDir):
        os.makedirs(configDir)
    return configDir

def getLogDir():
    userConfigDir = Utils.getConfigDir()
    return os.path.join(userConfigDir, 'logs')

def getLogPath(filename):
    return os.path.join(Utils.getLogDir(), filename)

def getSqlSnippetDir():
    quickLookDir = os.path.join(getConfigDir(), "quickLook")
    sqlDir = os.path.join(quickLookDir, "sql")

    if not os.path.exists(sqlDir):
        os.makedirs(sqlDir)
        if Config.debug:
            Logic.logMessage("DEBUG", f"getSqlSnippetDir: Created sql directory: {sqlDir}")

    return sqlDir