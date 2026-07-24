# Utils.py

import os
import sys
import json
import configparser
from PyQt6.QtCore import Qt, QStandardPaths, QSize, QObject, QEvent, QTimer
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget,
    QListWidget, QTreeView, QPushButton,
)
from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo, QFontMetrics, QGuiApplication, QIcon, QPixmap
from core import Logic, Config, Utils

# Bundled fonts (cross-platform):
#   non-retro → Noto Sans  (matches Seifer's Linux system UI font)
#   retro     → Press Start 2P
_defaultFontFamilyCache = None   # Noto Sans
_defaultFontLoadAttempted = False
_retroFontFamilyCache = None     # Press Start 2P
_retroFontLoadAttempted = False

# Point sizes by control role: (non-retro, retro)
# Non-retro: 10pt Noto Sans — matches this machine's GNOME/Qt default.
# Retro: buttons stay at 6 (width/fit tuned); other roles larger so labels/lists/logs aren't tiny.
FONT_ROLE_SIZES = {
    'ui':     (10, 8),   # labels, checkboxes, radios, combos, tabs, general
    'button': (10, 6),   # QPushButton — retro size kept at tuned 6pt
    'list':   (10, 8),   # list widgets / snippets / quick looks
    'table':  (10, 8),   # data tables
    'log':    (10, 10),  # log viewer
    'code':   (10, 9),   # SQL / plain text editors
    'about':  (10, 9),   # about dialog body (About always forces Press Start)
}

# Bundled default (non-retro) font faces — all register as family "Noto Sans"
_DEFAULT_FONT_FILES = (
    'ui/fonts/NotoSans-Regular.ttf',
    'ui/fonts/NotoSans-Bold.ttf',
    'ui/fonts/NotoSans-Italic.ttf',
    'ui/fonts/NotoSans-BoldItalic.ttf',
)

# Absolute geometries that differ by font mode: (x, y, width, height)
# Default = Noto (Seifer-tuned 2026-07-24). Retro = pre-Noto baseline until tuned.
# Only controls listed here are moved; everything else stays at .ui geometry.
CONTROL_LAYOUTS = {
    'default': {
        # winMain — Data Query tab overlay icons
        'btnRefresh': (22, 6, 32, 32),
        'btnUndo': (70, 6, 32, 32),
        # winOptions — Application tab checkboxes (nudged left under Noto labels)
        'chkbRawData': (74, 60, 21, 22),
        'chkbQAQC': (156, 90, 21, 22),
        'chkbRetroMode': (88, 120, 21, 22),
        'chkbDebug': (96, 150, 21, 22),
        'chkbEnableSQL': (128, 180, 21, 22),
        # winQuery — info icons next to labels
        'btnDataIdInfo': (376, 5, 31, 20),
        'btnIntervalInfo': (100, 76, 31, 20),
        'btnQueryOptionsInfo': (110, 401, 31, 20),
    },
    'retro': {
        # Pre-Noto baseline (Press Start tuning TBD — update these when retro layout starts)
        'btnRefresh': (26, 10, 32, 32),
        'btnUndo': (76, 10, 32, 32),
        'chkbRawData': (84, 60, 21, 22),
        'chkbQAQC': (178, 90, 21, 22),
        'chkbRetroMode': (100, 120, 21, 22),
        'chkbDebug': (110, 150, 21, 22),
        'chkbEnableSQL': (150, 180, 21, 22),
        'btnDataIdInfo': (382, 5, 31, 20),
        'btnIntervalInfo': (110, 76, 31, 20),
        'btnQueryOptionsInfo': (124, 401, 31, 20),
    },
}

# Query-style lists that need tight item rows on Windows non-retro
# (SQL snippet list + Query dataID list only — not every QListWidget)
COMPACT_LIST_OBJECT_NAMES = frozenset({'listSnippets', 'listQueryList'})

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

def _registerBundledFont(relativePath, label):
    """
    Register one TTF/OTF from the app bundle. Returns family name or None.
    Safe to call repeatedly for the same path (Qt may return a new id; we cache outside).
    """
    fontPath = Logic.resourcePath(relativePath)
    if not os.path.isfile(fontPath):
        Logic.logMessage("ERROR", f"{label} font file missing: {fontPath}")
        return None

    fontId = QFontDatabase.addApplicationFont(fontPath)
    if fontId == -1:
        Logic.logMessage("ERROR", f"Failed to register {label} font (addApplicationFont=-1): {fontPath}")
        return None

    families = QFontDatabase.applicationFontFamilies(fontId)
    if not families:
        Logic.logMessage("ERROR", f"{label} font registered but returned no families: {fontPath}")
        return None

    family = families[0]
    Logic.logMessage("INFO", f"Loaded {label} font family {family!r} from {fontPath}")
    return family


def ensureDefaultFontLoaded():
    """
    Bundled Noto Sans — non-retro default so Linux/Windows/macOS look the same.
    Registers Regular/Bold/Italic/BoldItalic; returns the family name or None.
    Falls back to the OS UI font only if every file fails to load.
    """
    global _defaultFontFamilyCache, _defaultFontLoadAttempted
    if _defaultFontLoadAttempted:
        return _defaultFontFamilyCache
    _defaultFontLoadAttempted = True

    family = None
    for rel in _DEFAULT_FONT_FILES:
        loaded = _registerBundledFont(rel, 'default (Noto Sans)')
        if loaded and not family:
            family = loaded

    _defaultFontFamilyCache = family
    Config.defaultFontLoaded = bool(family)
    if not family:
        Logic.logMessage(
            "WARN",
            "Bundled Noto Sans failed to load; non-retro will use the OS UI font",
        )
    return family


def ensureRetroFontLoaded():
    """Bundled Press Start 2P — retro mode only."""
    global _retroFontFamilyCache, _retroFontLoadAttempted
    if _retroFontLoadAttempted:
        return _retroFontFamilyCache
    _retroFontLoadAttempted = True

    family = _registerBundledFont(
        'ui/fonts/PressStart2P-Regular.ttf',
        'retro (Press Start 2P)',
    )
    _retroFontFamilyCache = family
    Config.retroFontLoaded = bool(family)
    return family


def activeFontFamily():
    """
    Family for the current mode.
    Retro → bundled Press Start 2P.
    Default → bundled Noto Sans (cross-platform); '' only if load failed.
    """
    if Config.retroMode:
        return ensureRetroFontLoaded() or ''
    return ensureDefaultFontLoaded() or ''


def rolePointSize(role='ui', retro=None):
    """Point size for a control role (see FONT_ROLE_SIZES)."""
    if retro is None:
        retro = bool(getattr(Config, 'retroMode', False))
    defaultPt, retroPt = FONT_ROLE_SIZES.get(role, FONT_ROLE_SIZES['ui'])
    size = retroPt if retro else defaultPt

    # HiDPI: step down slightly so dense pixel fonts / tables stay readable
    if size > 0:
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None and screen.logicalDotsPerInch() >= 140:
                size = max(5, size - 1)
        except Exception:
            pass
    return size


def uiPointSize(retro=None):
    """Base UI point size (role 'ui'). Kept for About / older call sites."""
    return rolePointSize('ui', retro=retro)


def makeFontForRole(role='ui', pointSize=None):
    """
    Build a QFont for a control role.
    Roles: ui, button, list, table, log, code, about — see FONT_ROLE_SIZES.
    Non-retro: bundled Noto Sans at role size (fallback OS font if missing).
    Retro: bundled Press Start 2P, no antialias.
    """
    family = activeFontFamily()
    if pointSize is not None:
        size = int(pointSize)
    else:
        size = rolePointSize(role)

    if family:
        pt = size if size > 0 else (6 if Config.retroMode else 10)
        font = QFont(family, pt)
        if Config.retroMode:
            font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        return font

    # Fallback: OS UI font (only if bundled default failed to load)
    font = QFont()
    if size > 0:
        font.setPointSize(size)
    return font


def makeUiFont(pointSize=None):
    """App-wide default font (UI role)."""
    font = makeFontForRole('ui', pointSize=pointSize)
    Config.uiFontFamily = activeFontFamily() or ''
    Config.fontSize = font.pointSize() if font.pointSize() > 0 else rolePointSize('ui')
    return font


def tableDefaultRowHeight(font=None, metrics=None):
    """
    Vertical section size for data tables — font + platform + mode aware.

    Non-retro (Noto) on Linux: height+10 looks perfect (existing design).
    Non-retro on Windows: native styles add extra cell margin, so use less pad
    so rows match the Linux density.
    Retro (Press Start): keep the roomier height+10 used by buildTable today.
    """
    if metrics is None:
        if font is None:
            font = makeFontForRole('table')
        metrics = QFontMetrics(font)
    h = metrics.height()
    if Config.retroMode:
        return max(h + 10, h + 2)
    # Non-retro Noto Sans
    if sys.platform == 'win32':
        # Windows QStyle bakes more internal item padding than Fusion/Linux
        return max(h + 4, 20)
    # Linux / macOS — match the density Seifer signed off on
    return max(h + 10, 22)


def applyTableRowMetrics(table, font=None):
    """Apply cross-platform default row height to a QTableWidget (headers + sections)."""
    if table is None:
        return
    try:
        if font is None:
            font = table.font()
        size = tableDefaultRowHeight(font)
        vHeader = table.verticalHeader()
        vHeader.setDefaultSectionSize(size)
        # Allow slightly smaller if user drags, but not below glyph height
        vHeader.setMinimumSectionSize(max(QFontMetrics(font).height() + 2, 16))
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyTableRowMetrics failed: {e}")


def nonRetroPlatformStylesheet():
    """
    Non-retro (Noto) spacing tweaks that differ by platform.
    Table item padding only here — listSnippets/listQueryList use applyCompactListStyle.
    Never QTabBar/QPushButton chrome.
    """
    if Config.retroMode:
        return ""
    if sys.platform == 'win32':
        # Optional table tightening (harmless; row height is the main table control)
        return """
    QTableWidget::item, QTableView::item {
        padding-top: 0px;
        padding-bottom: 0px;
        padding-left: 3px;
        padding-right: 3px;
    }
    """
    return ""


def applyCompactListStyle(listWidget):
    """
    Tighten vertical item padding on SQL snippet list + Query dataID list.
    Windows non-retro only (Linux Noto list density was already fine).
    Retro keeps global retroSpacingStylesheet on these lists.
    """
    if listWidget is None:
        return
    name = listWidget.objectName() or ''
    if name not in COMPACT_LIST_OBJECT_NAMES:
        return
    try:
        if Config.retroMode:
            # Clear widget-local override so app-level retro list padding applies
            # (don't wipe thick scrollbar styles if any were set only here)
            existing = listWidget.styleSheet() or ''
            if '/*compact-list*/' in existing:
                listWidget.setStyleSheet('')
            listWidget.setSpacing(0)
            return
        if sys.platform == 'win32':
            listWidget.setSpacing(0)
            listWidget.setStyleSheet("""
                /*compact-list*/
                QListWidget::item {
                    padding-top: 0px;
                    padding-bottom: 0px;
                    padding-left: 2px;
                    padding-right: 2px;
                    min-height: 0px;
                }
            """)
        else:
            # Linux/macOS non-retro: leave native metrics (looked correct)
            listWidget.setSpacing(0)
            existing = listWidget.styleSheet() or ''
            if '/*compact-list*/' in existing:
                listWidget.setStyleSheet('')
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyCompactListStyle({name}) failed: {e}")


def applyModeControlLayouts(app=None, root=None):
    """
    Move mode-specific absolute controls (default Noto vs retro Press Start).
    Call after UI load / on mode apply. Unknown names are skipped.
    """
    mode = 'retro' if Config.retroMode else 'default'
    coords = CONTROL_LAYOUTS.get(mode) or {}
    if not coords:
        return

    if root is not None:
        widgets = [root] + list(root.findChildren(QWidget))
    elif app is not None:
        try:
            widgets = list(app.allWidgets())
        except Exception:
            widgets = list(app.topLevelWidgets())
    else:
        return

    byName = {}
    for w in widgets:
        n = w.objectName()
        if n and n in coords:
            byName[n] = w

    for name, (x, y, w, h) in coords.items():
        widget = byName.get(name)
        if widget is None:
            continue
        try:
            widget.setGeometry(x, y, w, h)
        except Exception as e:
            if Config.debug:
                Logic.logMessage("DEBUG", f"applyModeControlLayouts {name}: {e}")

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"applyModeControlLayouts: mode={mode} applied={len(byName)}/{len(coords)}",
        )


def retroSpacingStylesheet():
    """
    Extra vertical room for dense pixel fonts (Press Start looks like -2 line gap).
    Only list/table/checkbox spacing — never QTabBar/QPushButton padding (Windows
    native metrics break if those go into stylesheet mode).
    """
    if not Config.retroMode:
        return ""
    return """
    QListWidget::item, QListView::item {
        padding-top: 5px;
        padding-bottom: 5px;
        padding-left: 3px;
        padding-right: 3px;
        min-height: 1.2em;
    }
    QTableWidget::item, QTableView::item {
        padding-top: 4px;
        padding-bottom: 4px;
        padding-left: 3px;
        padding-right: 3px;
    }
    QCheckBox, QRadioButton {
        spacing: 10px;
        min-height: 1.3em;
    }
    QComboBox {
        padding-top: 2px;
        padding-bottom: 2px;
        min-height: 1.2em;
    }
    QLabel {
        padding-top: 1px;
        padding-bottom: 1px;
    }
    """


def readBaseStylesheet():
    """
    Base qss (hover, tab close) + mode/platform item spacing.
    Fonts are applied via QFont (not QSS font-size on tabs/buttons) so Windows
    keeps native tab/button chrome.
    """
    path = Logic.resourcePath('ui/stylesheet.qss')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            base = f.read()
    except Exception as e:
        Logic.logMessage("ERROR", f"Could not read stylesheet {path}: {e}")
        base = ""
    return base + "\n" + retroSpacingStylesheet() + "\n" + nonRetroPlatformStylesheet()


def propagateUiFont(app, font=None):
    """
    Apply base UI font to the app default and every existing widget, then
    upgrade specific control types to role sizes (log larger, etc.).
    """
    if font is None:
        font = makeUiFont()
    app.setFont(font)
    try:
        widgets = list(app.allWidgets())
    except Exception:
        widgets = list(app.topLevelWidgets())
    for w in widgets:
        try:
            w.setFont(font)
        except Exception:
            pass
    applyRoleFonts(app)
    return font


def applyRoleFonts(app=None, root=None):
    """
    Set role-specific sizes: buttons stay smaller in retro; log/code larger, etc.
    Call after new windows open if they create tables/editors themselves.
    """
    buttonFont = makeFontForRole('button')
    logFont = makeFontForRole('log')
    tableFont = makeFontForRole('table')
    listFont = makeFontForRole('list')
    codeFont = makeFontForRole('code')

    if root is not None:
        widgets = [root] + list(root.findChildren(QWidget))
    elif app is not None:
        try:
            widgets = list(app.allWidgets())
        except Exception:
            widgets = list(app.topLevelWidgets())
    else:
        return

    for w in widgets:
        try:
            if isinstance(w, QPushButton):
                # Keep retro button size at the tuned width/fit (smaller than labels)
                w.setFont(buttonFont)
            elif isinstance(w, (QPlainTextEdit, QTextEdit)):
                name = (w.objectName() or '').lower()
                if 'log' in name:
                    w.setFont(logFont)
                else:
                    w.setFont(codeFont)
            elif isinstance(w, QTableWidget):
                w.setFont(tableFont)
                try:
                    w.horizontalHeader().setFont(tableFont)
                    w.verticalHeader().setFont(tableFont)
                except Exception:
                    pass
                applyTableRowMetrics(w, tableFont)
            elif isinstance(w, QListWidget):
                w.setFont(listFont)
                applyCompactListStyle(w)
            elif isinstance(w, QTreeView):
                w.setFont(listFont)
        except Exception:
            pass


def applyStylesAndFonts(app, mainTable, queryList):
    """Load config, stylesheet, and bundled UI fonts (Noto Sans or Press Start)."""
    config = loadConfig()
    Config.debug = config['debugMode']
    Config.utcOffset = config['utcOffset']
    Config.periodOffset = resolvePeriodOffset(config)
    Config.retroMode = config.get('retroMode', True)

    # Pre-register the font for the active mode (and About always wants Press Start)
    if Config.retroMode:
        ensureRetroFontLoaded()
    else:
        ensureDefaultFontLoaded()
        ensureRetroFontLoaded()  # About dialog always uses pixel font

    app.setStyleSheet(readBaseStylesheet())
    appFont = propagateUiFont(app)
    # Mode-specific ABS button/checkbox positions (default Noto vs retro)
    applyModeControlLayouts(app=app)

    try:
        info = QFontInfo(appFont)
        Logic.logMessage(
            "INFO",
            "UI font: platform={} retroMode={} requested={!r} actual={!r} "
            "uiPt={} buttonPt={} logPt={} defaultLoaded={} retroLoaded={}".format(
                sys.platform,
                Config.retroMode,
                Config.uiFontFamily or '(system fallback)',
                info.family(),
                rolePointSize('ui'),
                rolePointSize('button'),
                rolePointSize('log'),
                Config.defaultFontLoaded,
                Config.retroFontLoaded,
            ),
        )
    except Exception as e:
        Logic.logMessage("WARN", f"UI font diagnostics failed: {e}")

    setRetroStyles(app, bool(Config.retroMode), mainTable, queryList)
    # setRetroStyles may clear listQueryList stylesheet — re-apply compact list padding
    try:
        for w in app.allWidgets():
            if isinstance(w, QListWidget):
                applyCompactListStyle(w)
    except Exception:
        pass

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

def applyRetroFont(widget, pointSize=None):
    """
    Apply the current UI font (bundled Noto Sans or Press Start) to a widget tree.
    pointSize=None uses the UI role size for the active mode.
    """
    font = makeUiFont(pointSize)
    widget.setFont(font)
    for child in widget.findChildren(QWidget):
        child.setFont(font)
    applyRoleFonts(root=widget)
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"applyRetroFont: {widget.objectName()} family={font.family()!r} "
            f"size={font.pointSize()} retro={Config.retroMode}",
        )

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
        # Keep font rules; append scroll theme only
        app.setStyleSheet(readBaseStylesheet() + retroStyles)

        if Config.debug:
            Logic.logMessage("DEBUG", "Applied retro scroll bar styles globally")
    else:
        # Reset to base stylesheet + current font rules (no neon scroll handles)
        app.setStyleSheet(readBaseStylesheet())
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