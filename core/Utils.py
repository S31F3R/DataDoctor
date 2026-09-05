# Utils.py

import os
import sys
import json
import re
import configparser
import subprocess
import tempfile
import time
import weakref
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import Qt, QStandardPaths, QSize, QObject, QEvent, QTimer
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget,
    QListWidget, QListWidgetItem, QTreeView, QPushButton, QCheckBox,
    QRadioButton, QComboBox, QLabel, QTabBar, QTabWidget, QApplication,
    QHeaderView, QStyleFactory,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QFontInfo, QFontMetrics, QGuiApplication, QIcon,
    QPixmap, QPalette, QColor, QCursor,
)
from core import Logic, Config, Utils

# Bundled fonts (cross-platform):
#   non-retro → Noto Sans  (matches Seifer's Linux system UI font)
#   retro     → Silkscreen (same 8-bit arcade look as Press Start 2P, different maker)
#               Press Start 2P stays for About arcade games
defaultFontFamilyCache = None   # Noto Sans
defaultFontLoadAttempted = False
retroFontFamilyCache = None     # Silkscreen
retroFontLoadAttempted = False

# ---------------------------------------------------------------------------
# Font size knobs — 0 = the point sizes in fontRoleSizes below.
# Retro Silkscreen looks small at those pts; raise retroFontSizeAdjust
# (e.g. 2 → UI 8→10, buttons 6→8). Non-retro: leave at 0 for 10pt Noto.
# Live retro apply (Options) picks these up without a restart.
defaultFontSizeAdjust = 0
retroFontSizeAdjust = 4

# Point sizes by control role: (non-retro, retro) before the knobs above.
# Non-retro: 10pt Noto Sans — matches this machine's GNOME/Qt default.
# Retro: Silkscreen at the old Press Start 8/6 sizes (then + retroFontSizeAdjust).
fontRoleSizes = {
    'ui':     (10, 8),   # labels, checkboxes, radios, combos, tabs, general
    'button': (10, 6),   # QPushButton — retro size kept at tuned 6pt
    'list':   (10, 8),   # list widgets / snippets / quick looks
    'table':  (10, 8),   # data tables
    'log':    (10, 10),  # log viewer
    'code':   (10, 9),   # SQL / plain text editors
    'about':  (10, 9),   # about dialog body (arcade still uses Press Start)
}

# Bundled default (non-retro) font faces — all register as family "Noto Sans"
defaultFontFiles = (
    'ui/fonts/NotoSans-Regular.ttf',
    'ui/fonts/NotoSans-Bold.ttf',
    'ui/fonts/NotoSans-Italic.ttf',
    'ui/fonts/NotoSans-BoldItalic.ttf',
)

# ---------------------------------------------------------------------------
# Retro mode inventory — FONT vs LAYOUT vs CHROME, and where to edit.
#
# Retro uses Noto spacing (row heights, tab/list padding, header labels).
# Silkscreen + neon chrome stay. Extra x,y for a few overlay buttons lives in
# retroAlwaysLayouts (applied on top of controlLayouts when retro is on).
#
# FONT (always on in retro):
#   defaultFontSizeAdjust / retroFontSizeAdjust  this file — global pt knobs
#   ensureRetroFontLoaded()     this file — Silkscreen TTF in ui/fonts/
#   fontRoleSizes               this file — (Noto pt, retro pt) per role
#   queryRetroSmallControls     this file — named radios/checkboxes (ui − 2pt)
#   retroSmallFontPt            this file
#   winRetroSmallerControls     this file — Windows Query buttons −1pt
#   applyRoleFonts()            this file
#   ui/uiAbout.py               Press Start 2P for arcade games only
#
# LAYOUT:
#   controlLayouts              this file — Noto x,y (restored when retro off)
#   retroAlwaysLayouts          this file — Refresh/Undo/Upload + info buttons
#   applyModeControlLayouts()   this file
#   tableDefaultRowHeight()     this file — Silkscreen em-box, no extra pad
#   applyRetroQueryWindow()     this file — Windows query extra width
#
# CHROME (always on in retro):
#   setRetroStyles()            this file — neon scrollbar handles
#   retroSpacingStylesheet()    this file — green tabs + retro close icons
#   retroNeonGreen              this file
# ---------------------------------------------------------------------------

# Extra retro geometries (info buttons except Data ID, main-table Refresh/Undo/Upload).
# Query width: Windows ~2 Silkscreen characters so USGS-NWIS fits. Linux: original.
queryWindowBase = (960, 668)
queryRetroExtraWWin = 96
queryRetroExtraWLinux = 0
retroAlwaysLayouts = {
    'btnRefresh': (54, 8, 32, 32),
    'btnUndo': (90, 8, 32, 32),
    'btnUpload': (126, 8, 32, 32),
    'btnIntervalInfo': (164, 76, 31, 20),
    'btnQueryOptionsInfo': (170, 401, 31, 20),
}

# Absolute Noto geometries. Retro overlays retroAlwaysLayouts on top.
# Only controls listed here are moved; everything else stays at .ui geometry.
# Every control retro moves must also appear here so retro OFF restores Noto.
controlLayouts = {
    # winMain — Data Query tab overlay icons (match winMain.ui; Windows y via platformLayoutYNudge)
    # .ui bases: Refresh (4,6), Undo (40,6), Upload (76,6) — 32×32, 4px gaps
    'btnRefresh': (14, 6, 32, 32),
    'btnUndo': (50, 6, 32, 32),
    'btnUpload': (86, 6, 32, 32),
    # winQuery
    'btnDataIdInfo': (376, 5, 31, 20),
    'btnIntervalInfo': (100, 76, 31, 20),
    'btnQueryOptionsInfo': (110, 401, 31, 20),
    'chkbOverlay': (150, 424, 131, 22),         # .ui
    'chkbQAQC': (150, 448, 131, 22),
}

# Neon green used for retro scrollbars and tab chrome
retroNeonGreen = '#00FF00'

# Query-window radios/checkboxes: one step under UI.
queryRetroSmallControls = frozenset({
    'rbCustomDateTime',
    'rbPrevDayToCurrent',
    'rbPrevWeekToCurrent',
    'chkbDelta',
    'chkbOverlay',
    'chkbRawData',
    'chkbQAQC',
})
retroSmallFontPt = 4  # one step under general ui 8pt; also gets retroFontSizeAdjust

# Query window text buttons: one point larger than normal button role (retro 6→7, default 10→11)
queryLargeButtonControls = frozenset({
    'btnAddQuery',
    'btnQuery',
})

# Retro: Load/Save/Clear/Delete Quick Look −1pt (Silkscreen clips at button role).
winRetroSmallerControls = frozenset({
    'btnLoadQuickLook',
    'btnClearQuery',
    'btnSaveQuickLook',
    'btnDeleteQuickLook',  # same row as Load/Save; keep quartet consistent
    'listQueryList',
})

# Extra Y offset (pixels) applied on a given platform for default (Noto) mode only.
# Overlay icons: Linux y=6; Windows y=8 (+2). Final for non-retro.
platformLayoutYNudge = {
    'win32': {
        'default': {
            'btnRefresh': 2,
            'btnUndo': 2,
            'btnUpload': 2,
        },
    },
}

# Query-style lists that need tight item rows on Windows non-retro
# (SQL snippet list + Query dataID list only — not every QListWidget)
compactListObjectNames = frozenset({'listSnippets', 'listQueryList'})


def findWindowsLauncherExe(script, cwd):
    """
    Prefer the VB.NET 'Data Doctor.exe' when present next to the install layout
    (zip root / launcher folder / parent of pythonFiles).
    """
    candidates = []
    roots = []
    for base in (cwd, os.path.dirname(script) if script else '', Config.appRoot or ''):
        if not base:
            continue
        base = os.path.abspath(base)
        roots.append(base)
        roots.append(os.path.dirname(base))  # Project Files → zip root
        roots.append(os.path.dirname(os.path.dirname(base)))
    seen = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        for name in ('Data Doctor.exe', 'DataDoctor.exe'):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                candidates.append(path)
    return candidates[0] if candidates else None


def restartApplication():
    """
    Relaunch this process then quit the current app.

    Windows cannot reliably use os.execl (pythonw, spaces, VB launcher).
    Strategy:
      1. Prefer python + DataDoctor.py(w) (same process that is running)
      2. Fall back to Data Doctor.exe launcher only if no script path
      3. On Windows: temp .cmd waits, starts app, logs to %TEMP%\\DataDoctorRestart.log
      4. On Unix: QProcess.startDetached / subprocess, then quit

    Returns True if a restart was scheduled, False on hard failure.
    Retro mode (and other config) must already be saved before calling.
    """
    try:
        program = os.path.abspath(sys.executable)
        # sys.argv[0] may be relative; resolve against cwd
        argv0 = sys.argv[0] if sys.argv else ''
        script = os.path.abspath(argv0) if argv0 else ''
        if script and not os.path.isfile(script):
            for alt in (
                script,
                script + 'w' if not script.endswith('w') else script[:-1],
                os.path.join(Config.appRoot or '', 'DataDoctor.py'),
                os.path.join(Config.appRoot or '', 'DataDoctor.pyw'),
                os.path.join(Config.appRoot or '', 'app.pyw'),
            ):
                if alt and os.path.isfile(alt):
                    script = os.path.abspath(alt)
                    break
        extra = list(sys.argv[1:]) if len(sys.argv) > 1 else []
        cwd = os.getcwd()

        if script and os.path.isfile(script):
            cwd = os.path.dirname(script) or cwd
        if Config.appRoot and os.path.isdir(Config.appRoot):
            if os.path.isfile(os.path.join(Config.appRoot, 'DataDoctor.py')) or \
               os.path.isfile(os.path.join(Config.appRoot, 'DataDoctor.pyw')) or \
               os.path.isfile(os.path.join(Config.appRoot, 'app.pyw')):
                cwd = Config.appRoot

        Logic.logMessage(
            "INFO",
            f"restartApplication: program={program!r} script={script!r} "
            f"extra={extra!r} cwd={cwd!r} platform={sys.platform}",
        )

        if sys.platform == 'win32':
            # Prefer re-exec of the same Python + script (avoids wrong/old launcher)
            childCwd = cwd
            if script and os.path.isfile(script):
                # Use pythonw if current is pythonw (no console flash)
                exe = program
                childArgs = [exe, script] + extra
            else:
                launcher = findWindowsLauncherExe(script, cwd)
                if launcher:
                    childCwd = os.path.dirname(launcher) or cwd
                    childArgs = [launcher]
                    Logic.logMessage(
                        "INFO",
                        f"restartApplication: fallback Windows launcher {launcher!r}",
                    )
                else:
                    childArgs = [program] + extra

            logPath = os.path.join(tempfile.gettempdir(), 'DataDoctorRestart.log')
            # Build a robust .cmd: delay, cd, start, log failures (no interactive pause)
            quotedArgs = ' '.join(f'"{a}"' for a in childArgs)
            batLines = [
                '@echo off',
                'setlocal EnableExtensions',
                f'echo DataDoctor restart %DATE% %TIME% > "{logPath}"',
                f'echo cwd={childCwd} >> "{logPath}"',
                f'echo cmd={quotedArgs} >> "{logPath}"',
                'rem Wait for parent process to exit',
                'ping -n 3 127.0.0.1 >nul',
                f'cd /d "{childCwd}" 2>> "{logPath}"',
                f'if errorlevel 1 echo CD failed >> "{logPath}"',
                # start "" = empty window title; /D sets working directory
                f'start "" /D "{childCwd}" {quotedArgs}',
                f'if errorlevel 1 (',
                f'  echo START failed errorlevel=%errorlevel% >> "{logPath}"',
                f') else (',
                f'  echo START ok >> "{logPath}"',
                f')',
                'del "%~f0" >nul 2>&1',
                '',
            ]
            fd, batPath = tempfile.mkstemp(suffix='.cmd', prefix='DataDoctorRestart_')
            os.close(fd)
            with open(batPath, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write('\r\n'.join(batLines))

            Logic.logMessage(
                "INFO",
                f"restartApplication: bat={batPath} log={logPath} args={childArgs}",
            )

            # Launch hidden cmd that runs the bat — DETACHED, no CREATE_NO_WINDOW
            # combo that fails on some hosts; use SW_HIDE via start /b from python.
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000
            launched = False
            # 1) Detached cmd /c bat (hidden console)
            try:
                subprocess.Popen(
                    ['cmd.exe', '/c', batPath],
                    cwd=childCwd,
                    close_fds=True,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                launched = True
            except Exception as e:
                Logic.logMessage("WARN", f"restartApplication: hidden cmd failed ({e})")

            # 2) ShellExecute on the bat
            if not launched:
                try:
                    os.startfile(batPath)  # nosec B606
                    launched = True
                except Exception as e:
                    Logic.logMessage("WARN", f"restartApplication: startfile failed ({e})")

            # 3) Last resort: start child immediately (may race with exit)
            if not launched:
                try:
                    subprocess.Popen(
                        childArgs,
                        cwd=childCwd,
                        close_fds=True,
                        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    launched = True
                    Logic.logMessage("INFO", "restartApplication: direct Popen child")
                except Exception as e:
                    Logic.logException("restartApplication: all Windows launch paths failed", e)
                    return False

            if not launched:
                return False
        else:
            # Linux / macOS
            args = [program]
            if script and os.path.isfile(script):
                args.append(script)
            args.extend(extra)
            try:
                from PyQt6.QtCore import QProcess
                ok = QProcess.startDetached(program, args[1:], cwd)
                if not ok:
                    raise RuntimeError('QProcess.startDetached returned False')
                Logic.logMessage("INFO", f"restartApplication: QProcess.startDetached {args}")
            except Exception as e:
                Logic.logMessage("WARN", f"restartApplication: QProcess failed ({e}); subprocess")
                subprocess.Popen(args, cwd=cwd, start_new_session=True)
                Logic.logMessage("INFO", f"restartApplication: subprocess.Popen {args}")

        # Quit after a short delay so the restart spawn is fully underway
        Logic.appIsQuitting = True
        app = QApplication.instance()

        def quitApp():
            Logic.appIsQuitting = True
            try:
                if app is not None:
                    app.closeAllWindows()
                    app.quit()
                else:
                    os._exit(0)  # library API
            except Exception:
                os._exit(0)  # library API

        if app is not None:
            delayMs = 500 if sys.platform == 'win32' else 250
            QTimer.singleShot(delayMs, quitApp)
        else:
            time.sleep(0.3)
            os._exit(0)  # library API
        return True
    except Exception as e:
        Logic.logException("restartApplication failed", e)
        return False


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

def registerBundledFont(relativePath, label):
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
    global defaultFontFamilyCache, defaultFontLoadAttempted
    if defaultFontLoadAttempted:
        return defaultFontFamilyCache
    defaultFontLoadAttempted = True

    family = None
    for rel in defaultFontFiles:
        loaded = registerBundledFont(rel, 'default (Noto Sans)')
        if loaded and not family:
            family = loaded

    defaultFontFamilyCache = family
    Config.defaultFontLoaded = bool(family)
    if not family:
        Logic.logMessage(
            "WARN",
            "Bundled Noto Sans failed to load; non-retro will use the OS UI font",
        )
    return family


def ensureRetroFontLoaded():
    """Bundled Silkscreen — retro UI (Press Start 2P remains for About games)."""
    global retroFontFamilyCache, retroFontLoadAttempted
    if retroFontLoadAttempted:
        return retroFontFamilyCache
    retroFontLoadAttempted = True

    family = None
    for rel, label in (
        ('ui/fonts/Silkscreen-Regular.ttf', 'retro (Silkscreen)'),
        ('ui/fonts/Silkscreen-Bold.ttf', 'retro bold (Silkscreen)'),
    ):
        loaded = registerBundledFont(rel, label)
        if loaded and not family:
            family = loaded
    if not family:
        family = registerBundledFont(
            'ui/fonts/PressStart2P-Regular.ttf',
            'retro fallback (Press Start 2P)',
        )
    retroFontFamilyCache = family
    Config.retroFontLoaded = bool(family)
    return family


def activeFontFamily():
    """
    Family for the current mode.
    Retro → bundled Silkscreen.
    Default → bundled Noto Sans (cross-platform); '' only if load failed.
    """
    if Config.retroMode:
        return ensureRetroFontLoaded() or ''
    return ensureDefaultFontLoaded() or ''


def rolePointSize(role='ui', retro=None):
    """Point size for a control role (see fontRoleSizes + the size knobs)."""
    if retro is None:
        retro = bool(getattr(Config, 'retroMode', False))
    defaultPt, retroPt = fontRoleSizes.get(role, fontRoleSizes['ui'])
    size = retroPt if retro else defaultPt
    adjust = retroFontSizeAdjust if retro else defaultFontSizeAdjust
    try:
        size = int(size) + int(adjust)
    except (TypeError, ValueError):
        pass
    size = max(5, size)

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
    Roles: ui, button, list, table, log, code, about — see fontRoleSizes.
    Non-retro: bundled Noto Sans at role size (fallback OS font if missing).
    Retro: bundled Silkscreen.
    """
    family = activeFontFamily()
    if pointSize is not None:
        size = int(pointSize)
    else:
        size = rolePointSize(role)

    if family:
        pt = size if size > 0 else (6 if Config.retroMode else 10)
        font = QFont()
        try:
            font.setFamilies([family])
        except Exception:
            font.setFamily(family)
        font.setPointSize(pt)
        if Config.retroMode and family and (
            'Press Start' in family or 'Silkscreen' in family
        ):
            font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        else:
            # PreferMatch: do not silently substitute Segoe UI / Arial on Windows
            # after QApplication.setStyle() (Fusion) resets widget fonts.
            try:
                font.setStyleStrategy(
                    QFont.StyleStrategy.PreferAntialias
                    | QFont.StyleStrategy.PreferMatch
                )
            except Exception:
                font.setStyleStrategy(QFont.StyleStrategy.PreferMatch)
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
    Vertical section size for data table ROWS (height, not width).

    Non-retro (Noto) on Linux: height+10 looks perfect (existing design).
    Non-retro on Windows: native styles add extra cell margin, so use less pad.
    Retro (Silkscreen): no extra pad — the em-box is already tall.
    """
    if metrics is None:
        if font is None:
            font = makeFontForRole('table')
        metrics = QFontMetrics(font)
    h = metrics.height()
    if Config.retroMode:
        # No extra Noto-style pad — Silkscreen em-box is already tall.
        return max(h - 2, 18)
    if sys.platform == 'win32':
        return max(h + 4, 20)
    return max(h + 10, 22)


def tableHeaderBarHeight(font=None, metrics=None):
    """Native horizontal header band (no extra retro spacer)."""
    return 0


def formatTableHeaderLabel(text):
    """Header text as stored. Kept as a hook for Query / TableOps callers."""
    if text is None:
        return ''
    return str(text)


def applyTableRowMetrics(table, font=None):
    """Apply row HEIGHT + (retro) header bar HEIGHT — never column width."""
    if table is None:
        return
    try:
        if font is None:
            font = table.font()
        metrics = QFontMetrics(font)
        size = tableDefaultRowHeight(font, metrics)
        vHeader = table.verticalHeader()
        vHeader.setDefaultSectionSize(size)
        vHeader.setMinimumSectionSize(max(metrics.height() + 2, 16))

        hHeader = table.horizontalHeader()
        # Horizontal header may highlight selection (column pick); widths stay
        # Interactive so "selected" chrome does not resize sections.
        hHeader.setHighlightSections(True)
        vHeader.setHighlightSections(False)
        hHeader.setMinimumHeight(tableHeaderBarHeight(font, metrics))
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyTableRowMetrics failed: {e}")


def sizeVerticalHeader(table):
    """
    Timestamp rail width using the same measure as data columns.

    Data cells: horizontalAdvance(text) + 22. The rail was too wide when
    sizeHint won, then too tight when we used tightBoundingRect + 4 (clipped
    the trailing 00). Lock to advance + 22 so Silkscreen matches the value
    columns; zero section padding so that 22px is the only extra.
    """
    if table is None:
        return
    try:
        vHeader = table.verticalHeader()
    except Exception:
        return
    if vHeader is None or not vHeader.isVisible():
        return
    try:
        vHeader.setSortIndicatorShown(False)
        vHeader.setSectionsClickable(False)
        vHeader.setHighlightSections(False)
    except Exception:
        pass
    font = vHeader.font() if vHeader.font() is not None else table.font()
    metrics = QFontMetrics(font)
    sample = "01/01/26 00:00:00"
    best = metrics.horizontalAdvance(sample)
    n = table.rowCount()
    for r in range(min(n, 40)):
        it = table.verticalHeaderItem(r)
        if it is None or not it.text():
            continue
        best = max(best, metrics.horizontalAdvance(it.text()))
    # Same fudge as autoSizeTableColumns for a cell-driven column
    w = max(best + 22, 8)
    vHeader.setStyleSheet(
        "QHeaderView { padding: 0px; }"
        "QHeaderView::section { padding: 0px; margin: 0px; }"
    )
    try:
        vHeader.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass
    align = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
    vHeader.setDefaultAlignment(align)
    for r in range(n):
        it = table.verticalHeaderItem(r)
        if it is not None:
            it.setTextAlignment(align)
    vHeader.setFixedWidth(w)


def autoSizeTableColumns(table, sampleRows=100):
    """
    Size columns from final header labels + a sample of displayed cell text.

    Call only after headers are final and cell text has been formatted
    (valuePrecision, overlay/delta rewrite). Never scan every row.
    """
    if table is None:
        return
    numCols = table.columnCount()
    numRows = table.rowCount()
    if numCols == 0:
        return

    # Horizontal may highlight selection; keep Interactive resize so highlight
    # chrome never re-measures column width (that caused giant headers).
    try:
        hHeader = table.horizontalHeader()
        vHeader = table.verticalHeader()
        hHeader.setHighlightSections(True)
        hHeader.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        vHeader.setHighlightSections(False)
    except Exception:
        pass

    font = table.font()
    metrics = QFontMetrics(font)
    sampleN = min(sampleRows, numRows)

    for c in range(numCols):
        headerItem = table.horizontalHeaderItem(c)
        headerText = headerItem.text() if headerItem else ''
        # Blank spacer lines (retro multi-line headers) do not drive width
        headerLines = [line.strip() for line in headerText.split('\n') if line.strip()]
        headerWidth = max(
            (metrics.horizontalAdvance(line) for line in headerLines),
            default=40,
        )
        maxCell = metrics.horizontalAdvance('0.00')
        for r in range(sampleN):
            it = table.item(r, c)
            if it and it.text():
                maxCell = max(maxCell, metrics.horizontalAdvance(it.text()))
        # Same fudge as original buildTable / modifyTable math
        finalWidth = max(maxCell, headerWidth)
        if headerWidth > maxCell:
            finalWidth = maxCell + (headerWidth - maxCell) + 10
        else:
            finalWidth += 20
        # Extra pad so multi-line header text is not clipped at edges
        finalWidth += 2
        table.setColumnWidth(c, finalWidth)

    sizeVerticalHeader(table)

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"autoSizeTableColumns: {numCols} cols, sampleRows={sampleN}/{numRows}",
        )


def nonRetroPlatformStylesheet():
    """
    Non-retro (Noto) spacing tweaks that differ by platform.
    Table item padding only here — listSnippets/listQueryList use applyCompactListStyle.
    Never QTabBar/QPushButton chrome.
    """
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
    if name not in compactListObjectNames:
        return
    try:
        existing = listWidget.styleSheet() or ''
        panePrefix = ''
        if '/*sql-pane-base*/' in existing:
            panePrefix = (
                "/*sql-pane-base*/\n"
                "background-color: palette(base);\n"
                "color: palette(text);\n"
            )
        if sys.platform == 'win32':
            listWidget.setSpacing(0)
            listWidget.setStyleSheet(
                panePrefix
                + """
                /*compact-list*/
                QListWidget::item {
                    padding-top: 0px;
                    padding-bottom: 0px;
                    padding-left: 2px;
                    padding-right: 2px;
                    min-height: 0px;
                }
            """
            )
        else:
            # Linux/macOS non-retro: leave native metrics (looked correct)
            listWidget.setSpacing(0)
            if '/*compact-list*/' in existing:
                listWidget.setStyleSheet(panePrefix)
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyCompactListStyle({name}) failed: {e}")


def applyModeControlLayouts(app=None, root=None):
    """
    Move mode-specific absolute controls (Noto, plus retroAlwaysLayouts in retro).
    Call after UI load / on mode apply. Unknown names are skipped.
    Windows default mode can apply platformLayoutYNudge (e.g. Refresh/Undo +3 y).
    """
    mode = 'retro' if Config.retroMode else 'default'
    coords = dict(controlLayouts)
    if Config.retroMode:
        coords.update(retroAlwaysLayouts)
    if not coords:
        return

    yNudges = (
        platformLayoutYNudge.get(sys.platform, {}).get(mode, {})
        if not Config.retroMode
        else {}
    )

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
            yAdj = y + int(yNudges.get(name, 0))
            widget.setGeometry(x, yAdj, w, h)
        except Exception as e:
            if Config.debug:
                Logic.logMessage("DEBUG", f"applyModeControlLayouts {name}: {e}")

    if root is not None and type(root).__name__ in ("uiQuery", "winInternalQuery"):
        applyRetroQueryWindow(root)
    elif app is not None:
        try:
            for w in app.topLevelWidgets():
                if type(w).__name__ in ("uiQuery", "winInternalQuery") or w.objectName() == "winInternalQuery":
                    applyRetroQueryWindow(w)
        except Exception:
            pass

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"applyModeControlLayouts: mode={mode} platform={sys.platform} "
            f"applied={len(byName)}/{len(coords)} yNudges={yNudges or '{}'}",
        )


def applyRetroQueryWindow(win):
    """Widen query Data ID / list / add / search ~4 characters in retro."""
    if win is None:
        return
    extra = 0
    if Config.retroMode:
        extra = queryRetroExtraWWin if sys.platform == 'win32' else queryRetroExtraWLinux
    w = queryWindowBase[0] + extra
    h = queryWindowBase[1]
    try:
        win.setMaximumSize(w, h)
        win.setFixedSize(w, h)
    except Exception:
        try:
            win.resize(w, h)
        except Exception:
            pass
    geos = {
        "qleDataID": (328, 29, 621 + extra, 32),
        "listQueryList": (328, 128, 621 + extra, 529),
        "btnSearch": (780 + extra, 65, 32, 32),
        "btnAddQuery": (810 + extra, 65, 141, 31),
    }
    for name, (x, y, ww, hh) in geos.items():
        widget = getattr(win, name, None)
        if widget is None:
            try:
                widget = win.findChild(QWidget, name)
            except Exception:
                widget = None
        if widget is None:
            continue
        try:
            widget.setGeometry(x, y, ww, hh)
        except Exception:
            pass


def retroSpacingStylesheet():
    """
    Retro only — neon tab chrome and close icons.

    Row height is set in tableDefaultRowHeight / applyTableRowMetrics, not QSS.
    """
    if not Config.retroMode:
        return ""
    # Tab chrome + close icons; stripped when retro off
    # (readBaseStylesheet / setRetroStyles rebuild without this block).
    # Hover for close is a 2nd image (same pattern as default dark/light pair).
    green = retroNeonGreen
    # Tab pad is Noto-sized; colors / close icons are chrome.
    pad = "padding: 4px 6px;"
    return f"""
    /* Retro tabs: neon green + #323232 text (not 0,0,0). */
    QTabBar::tab {{
        background: {green};
        color: #323232;
        {pad}
        border: 1px solid #00aa00;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {green};
        color: #323232;
        font-weight: bold;
        border: 1px solid #003300;
    }}
    QTabBar::tab:!selected {{
        background: #00cc00;
        color: #323232;
    }}
    /* Keep tab fill stable under mouse (no whole-tab brighten) */
    QTabBar::tab:hover,
    QTabBar::tab:selected:hover {{
        background: {green};
        color: #323232;
    }}
    QTabBar::tab:!selected:hover {{
        background: #00cc00;
        color: #323232;
    }}
    /* Close only: black disc + green X; hover = 2nd image (brighter X) */
    QTabBar::close-button {{
        image: url(ui/icons/Tab-close-retro.png);
        background: transparent;
        border: none;
        border-radius: 8px;
        subcontrol-position: right;
        subcontrol-origin: padding;
        width: 16px;
        height: 16px;
        margin-right: 10px;
    }}
    QTabBar::close-button:hover {{
        image: url(ui/icons/Tab-close-retro-hover.png);
        background: transparent;
    }}
    QTabBar::close-button:pressed {{
        image: url(ui/icons/Tab-close-retro-pressed.png);
        background: transparent;
    }}
    """


qssUrlRe = re.compile(r'url\(\s*[\'"]?([^)\'"]+)[\'"]?\s*\)')


def resolveStylesheetUrls(qss):
    """
    Rewrite QSS url(...) to absolute paths.

    Relative urls (ui/icons/Tab-close-dark.png) are resolved from CWD, which
    is wrong in an AppImage / frozen launch. resourcePath stays valid.
    """
    if not qss:
        return qss

    def repl(match):
        raw = (match.group(1) or '').strip()
        if not raw:
            return match.group(0)
        lower = raw.lower()
        if lower.startswith('file:') or lower.startswith('qrc:'):
            return match.group(0)
        if raw.startswith('/') or (len(raw) > 1 and raw[1] == ':'):
            try:
                posix = Path(raw).as_posix()
            except Exception:
                posix = raw.replace('\\', '/')
            return f'url("{posix}")'
        path = Logic.resourcePath(raw)
        try:
            posix = Path(path).resolve().as_posix()
        except Exception:
            posix = str(path).replace('\\', '/')
        if Config.debug and not os.path.isfile(path):
            Logic.logMessage("DEBUG", f"QSS url missing: {raw} -> {path}")
        return f'url("{posix}")'

    return qssUrlRe.sub(repl, qss)


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
    return resolveStylesheetUrls(
        base + "\n" + retroSpacingStylesheet() + "\n" + nonRetroPlatformStylesheet()
    )


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


def logResolvedUiFont(app=None, where='apply'):
    """
    Log requested vs actually resolved family.

    Windows native / Fusion setStyle() often substitutes Segoe UI; that is
    why Query radios and Options checkboxes look larger than Linux Noto.
    """
    app = app or QApplication.instance()
    requested = (getattr(Config, 'uiFontFamily', None) or activeFontFamily() or '').strip()
    actual = ''
    exact = None
    pt = None
    try:
        font = app.font() if app is not None else makeUiFont()
        info = QFontInfo(font)
        actual = (info.family() or '').strip()
        exact = info.exactMatch()
        pt = info.pointSize()
    except Exception as e:
        Logic.logMessage("WARN", f"UI font ({where}): could not read QFontInfo: {e}")
        return
    Logic.logMessage(
        "INFO",
        "UI font ({}): requested={!r} actual={!r} pt={} exact={} "
        "style={} defaultLoaded={} retroLoaded={} retroMode={}".format(
            where,
            requested or '(none)',
            actual or '(none)',
            pt,
            exact,
            styleKey(app) if app is not None else '',
            getattr(Config, 'defaultFontLoaded', False),
            getattr(Config, 'retroFontLoaded', False),
            bool(getattr(Config, 'retroMode', False)),
        ),
    )
    if requested and actual:
        req = requested.casefold()
        got = actual.casefold()
        if req not in got and got not in req:
            Logic.logMessage(
                "WARN",
                "UI font mismatch ({}): bundled {!r} resolved as {!r}. "
                "Windows will look different from Linux (controls may not fit). "
                "Confirm ui/fonts/*.ttf is in the install (pythonFiles/ui/fonts/).".format(
                    where, requested, actual
                ),
            )


def applyRoleFonts(app=None, root=None):
    """
    Set role-specific sizes: buttons stay smaller in retro; log/code larger, etc.
    Call after new windows open if they create tables/editors themselves.
    Retro-only small fonts for named Query radios/checkboxes (queryRetroSmallControls).
    """
    buttonFont = makeFontForRole('button')
    # Add Query / Query Data: one point larger than standard button role
    queryLargeButtonFont = makeFontForRole(
        'button',
        pointSize=max(rolePointSize('button') + 1, 1),
    )
    logFont = makeFontForRole('log')
    tableFont = makeFontForRole('table')
    listFont = makeFontForRole('list')
    codeFont = makeFontForRole('code')
    uiFont = makeFontForRole('ui')
    comboFont = uiFont
    querySmallFont = None
    if Config.retroMode:
        querySmallFont = makeFontForRole(
            'ui',
            pointSize=max(5, int(retroSmallFontPt) + int(retroFontSizeAdjust)),
        )
    # Retro: named Query controls one point smaller (all platforms)
    winRetroSmaller = bool(Config.retroMode)
    winSmallerButtonFont = None
    winSmallerListFont = None
    if winRetroSmaller:
        winSmallerButtonFont = makeFontForRole(
            'button', pointSize=max(rolePointSize('button') - 1, 5)
        )
        winSmallerListFont = makeFontForRole(
            'list', pointSize=max(rolePointSize('list') - 1, 5)
        )

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
            name = w.objectName() or ''
            # Retro notes: specific controls at 6pt Press Start (Noto/default untouched)
            if Config.retroMode and querySmallFont is not None and name in queryRetroSmallControls:
                w.setFont(querySmallFont)
                continue
            # Windows + retro: Load/Clear/Save/Delete Quick Look + dataID list −1pt
            if winRetroSmaller and name in winRetroSmallerControls:
                if isinstance(w, QListWidget) and winSmallerListFont is not None:
                    w.setFont(winSmallerListFont)
                    applyCompactListStyle(w)
                    continue
                if isinstance(w, QPushButton) and winSmallerButtonFont is not None:
                    w.setFont(winSmallerButtonFont)
                    continue
            if isinstance(w, QPushButton):
                if name in queryLargeButtonControls:
                    w.setFont(queryLargeButtonFont)
                else:
                    # Keep retro button size at the tuned width/fit (smaller than labels)
                    w.setFont(buttonFont)
            elif isinstance(w, (QPlainTextEdit, QTextEdit)):
                lname = name.lower()
                if 'log' in lname:
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
                try:
                    for i in range(w.count()):
                        it = w.item(i)
                        if it is not None:
                            it.setFont(listFont)
                except Exception:
                    pass
            elif isinstance(w, QTreeView):
                w.setFont(listFont)
            elif isinstance(w, QTabBar):
                w.setFont(uiFont)
            elif isinstance(w, QTabWidget):
                w.setFont(uiFont)
                try:
                    if w.tabBar() is not None:
                        w.tabBar().setFont(uiFont)
                except Exception:
                    pass
            elif isinstance(w, QComboBox):
                w.setFont(comboFont)
                try:
                    w.view().setFont(comboFont)
                except Exception:
                    pass
            elif isinstance(w, (QLabel, QRadioButton, QCheckBox, QLineEdit)):
                w.setFont(uiFont)
            else:
                try:
                    w.setFont(uiFont)
                except Exception:
                    pass
        except Exception:
            pass


def applyStylesAndFonts(app, mainTable, queryList):
    """Load config, stylesheet, and bundled UI fonts (Noto Sans or Press Start)."""
    config = loadConfig()
    Config.debug = config['debugMode']
    Config.utcOffset = config['utcOffset']
    Config.periodOffset = resolvePeriodOffset(config)
    Config.retroMode = config.get('retroMode', True)
    Config.hdbOverwriteFlag = 'O' if config.get('hdbOverwriteFlag') else None

    # Pre-register the font for the active mode (About arcade still wants Press Start)
    if Config.retroMode:
        ensureRetroFontLoaded()
    else:
        ensureDefaultFontLoaded()
        ensureRetroFontLoaded()  # About dialog still loads a pixel font

    app.setStyleSheet(readBaseStylesheet())
    propagateUiFont(app)
    # Mode-specific ABS button/checkbox positions (default Noto vs retro)
    applyModeControlLayouts(app=app)

    logResolvedUiFont(app, where='applyStylesAndFonts')

    setRetroStyles(app, bool(Config.retroMode), mainTable, queryList)
    # setRetroStyles may clear listQueryList stylesheet — re-apply compact list padding
    try:
        for w in app.allWidgets():
            if isinstance(w, QListWidget):
                applyCompactListStyle(w)
    except Exception:
        pass

def loadDataDictionary(table):
    """Load the data dictionary into the provided table (migrates schema if needed)."""
    Logic.ensureDataDictionarySchema()
    Logic.buildDataDictionary(table)
    # Combobox delegates + combo column widths (editor window only — safe no-op otherwise)
    try:
        parent = table.window() if table is not None else None
        if parent is not None and hasattr(parent, 'applyValuePrecisionDelegate'):
            parent.applyValuePrecisionDelegate()
        if parent is not None and hasattr(parent, 'applyDatabaseDelegate'):
            parent.applyDatabaseDelegate()
        if parent is not None and hasattr(parent, 'sizeComboColumns'):
            parent.sizeComboColumns()
    except Exception:
        pass

def loadQuickLooks(cbQuickLook):
    """Load all Quick Looks into the provided combobox."""
    Logic.loadAllQuickLooks(cbQuickLook)

def hdbDatabaseLabel(entry):
    """
    Strip optional |SCHEMA suffix from an hdbOracleDatabases entry.
    'USBR-UCHDB2|UCHDBA' → 'USBR-UCHDB2'; bare names pass through.
    """
    s = str(entry or '').strip()
    if '|' in s:
        return s.split('|', 1)[0].strip()
    return s


def hdbSchemaForDatabase(dbName):
    """
    Resolve HDB Oracle schema for a database label (e.g. USBR-UCHDB2 → UCHDBA).

    Prefer Config.hdbOracleDatabases 'LABEL|SCHEMA' entries. Fall back to the
    historical rstrip('2')+'A' derivation when the DB is not listed.
    """
    label = hdbDatabaseLabel(dbName)
    if not label:
        return ''

    # Match against config entries (with or without USBR- prefix on either side)
    entries = getattr(Config, 'hdbOracleDatabases', ()) or ()
    labelUpper = label.upper()
    shortUpper = labelUpper.split('-', 1)[-1] if '-' in labelUpper else labelUpper

    for entry in entries:
        entryStr = str(entry or '').strip()
        if not entryStr:
            continue
        if '|' in entryStr:
            namePart, schemaPart = entryStr.split('|', 1)
            namePart = namePart.strip()
            schemaPart = schemaPart.strip()
        else:
            namePart, schemaPart = entryStr, ''
        nameUpper = namePart.upper()
        nameShort = nameUpper.split('-', 1)[-1] if '-' in nameUpper else nameUpper
        if nameUpper == labelUpper or nameShort == shortUpper:
            if schemaPart:
                return schemaPart.upper()
            break

    # Legacy derivation: uchdb2 → UCHDBA, lchdb → LCHDBA
    dsn = shortUpper.lower()
    if dsn.endswith('2'):
        return dsn.upper().rstrip('2') + 'A'
    return dsn.upper() + 'A'


def hdbAccessUncheckedNames():
    """Display names the user turned off in Options → Oracle Access List."""
    try:
        names = loadConfig().get('hdbAccessUnchecked') or []
    except Exception:
        names = []
    return set(str(n).strip() for n in names if str(n).strip())


def programDatabases(queryType=None, applyAccessList=None):
    """
    Ordered list of database labels used by query combos / data dictionary.

    queryType:
      'internal' — include AQUARIUS + HDBs + public sources
      'sql'      — HDBs only (Oracle targets)
      None / other — public-style: HDBs + USGS + PNHYD + GPHYD (no AQUARIUS)

    applyAccessList (default True for internal/sql, False otherwise):
      skip HDBs the user unchecked. Public query always shows every HDB.
      Data Dictionary should pass False so every source stays editable.
    """
    names = []
    seen = set()

    def add(name):
        n = (name or '').strip()
        if n and n not in seen:
            names.append(n)
            seen.add(n)

    if applyAccessList is None:
        applyAccessList = queryType in ('internal', 'sql')
    unchecked = hdbAccessUncheckedNames() if applyAccessList else set()

    if queryType == 'internal':
        add('AQUARIUS')

    for entry in getattr(Config, 'hdbOracleDatabases', ()) or ():
        label = hdbDatabaseLabel(entry)
        if applyAccessList and label in unchecked:
            continue
        add(label)

    # Fallback if config empty
    if not any(n.startswith('USBR-') and n not in ('USBR-PNHYD', 'USBR-GPHYD') for n in names):
        for name in (
            'USBR-LCHDB', 'USBR-YAOHDB', 'USBR-UCHDB2',
            'USBR-ECOHDB', 'USBR-LBOHDB', 'USBR-KBOHDB',
        ):
            if applyAccessList and name in unchecked:
                continue
            add(name)

    if queryType != 'sql':
        add('USGS-NWIS')
        add('USBR-PNHYD')
        add('USBR-GPHYD')

    return names


def loadDatabase(comboBox, queryType=None):
    """Populate the database combo box with static databases (no |SCHEMA in labels)."""
    if comboBox:
        if Config.debug:
            Logic.logMessage("DEBUG", "Populating cbDatabase")
        comboBox.clear()
        for name in programDatabases(queryType=queryType):
            comboBox.addItem(name)

        if Config.debug:
            Logic.logMessage("DEBUG", f"Populated cbDatabase with {comboBox.count()} items")
    else:
        if Config.debug:
            Logic.logMessage("ERROR", "cbDatabase is None, cannot populate")

def iconButtonCursorOver(widget):
    """True if the cursor is inside widget. Do not use underMouse() — it sticks after modals."""
    if widget is None:
        return False
    try:
        if not widget.isVisible() or not widget.isEnabled():
            return False
        return widget.rect().contains(widget.mapFromGlobal(QCursor.pos()))
    except Exception:
        return False


styledIconButtons = []
appIconHoverFilter = None


def pruneStyledIconButtons():
    styledIconButtons[:] = [ref for ref in styledIconButtons if ref() is not None]


def registerStyledIconButton(button):
    pruneStyledIconButtons()
    styledIconButtons.append(weakref.ref(button))
    ensureAppIconHoverFilter()


def syncOneIconButton(button):
    if button is None:
        return
    try:
        over = iconButtonCursorOver(button)
        if button.isDown():
            icon = getattr(button, '_ddPressedIcon', None)
        elif over:
            icon = getattr(button, '_ddHoverIcon', None)
        else:
            icon = getattr(button, '_ddNormalIcon', None)
            button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        if icon is not None:
            button.setIcon(icon)
    except RuntimeError:
        pass
    except Exception:
        pass


def syncAllIconButtonHovers():
    pruneStyledIconButtons()
    for ref in styledIconButtons:
        syncOneIconButton(ref())


class AppIconHoverFilter(QObject):
    """
    Mouse Leave is often swallowed after a modal or a slot exception, so the
    hover icon sticks until the cursor re-enters that button. Any mouse move
    or window deactivate re-syncs every icon button from the real cursor.
    """

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.WindowActivate,
            QEvent.Type.ApplicationDeactivate,
            QEvent.Type.ApplicationActivate,
        ):
            syncAllIconButtonHovers()
        return False


def ensureAppIconHoverFilter():
    global appIconHoverFilter
    if appIconHoverFilter is not None:
        return
    app = QApplication.instance()
    if app is None:
        return
    appIconHoverFilter = AppIconHoverFilter(app)
    app.installEventFilter(appIconHoverFilter)


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

        normalIcon = QIcon(normalPixmap)
        hoverIcon = QIcon(hoverPixmap)
        pressedIcon = QIcon(pressedPixmap)
        button._ddNormalIcon = normalIcon
        button._ddHoverIcon = hoverIcon
        button._ddPressedIcon = pressedIcon
        button.setIcon(normalIcon)
        button.setFlat(True)
        button.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        button.setMouseTracking(True)
        registerStyledIconButton(button)

        # Define local event filter for state swaps
        class ButtonEventFilter(QObject):
            def eventFilter(self, obj, event):
                et = event.type()
                if et in (
                    QEvent.Type.Enter,
                    QEvent.Type.HoverEnter,
                    QEvent.Type.HoverMove,
                ):
                    # Fake Enter after a modal: only hover if the cursor is
                    # actually over the button.
                    syncOneIconButton(obj)
                elif et in (
                    QEvent.Type.Leave,
                    QEvent.Type.HoverLeave,
                    QEvent.Type.Hide,
                ):
                    obj.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    obj.setIcon(normalIcon)
                elif et == QEvent.Type.MouseButtonPress:
                    obj.setIcon(pressedIcon)
                elif et == QEvent.Type.MouseButtonRelease:
                    def syncIcon():
                        syncOneIconButton(obj)
                    syncIcon()
                    QTimer.singleShot(0, syncIcon)
                    QTimer.singleShot(50, syncIcon)
                    QTimer.singleShot(150, syncIcon)
                return super().eventFilter(obj, event)

        # Install filter (remove any existing to avoid duplicates)
        oldFilt = getattr(button, '_ddIconFilter', None)
        if oldFilt is not None:
            button.removeEventFilter(oldFilt)
        filt = ButtonEventFilter(button)
        button._ddIconFilter = filt
        button.installEventFilter(filt)
        # After clicked slots (modal or exception dialog), wait until no
        # modal is up, then force a cursor-based restore.
        def syncAfterClick(*unused, btn=button):
            def tick(retries=40):
                app = QApplication.instance()
                if app is not None and app.activeModalWidget() is not None:
                    if retries > 0:
                        QTimer.singleShot(50, lambda: tick(retries - 1))
                    return
                resetStyledButtonHover(btn)
            QTimer.singleShot(0, lambda: tick())
            QTimer.singleShot(200, lambda: resetStyledButtonHover(btn))
        oldClick = getattr(button, '_ddHoverClickHook', None)
        if oldClick is not None:
            try:
                button.clicked.disconnect(oldClick)
            except TypeError:
                pass
        button._ddHoverClickHook = syncAfterClick
        button.clicked.connect(syncAfterClick)

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

def bindIndependentWindow(widget, owner=None, allowMaximize=True):
    """
    Make widget a real top-level window so minimize goes to the taskbar.

    QMainWindow(parent=main) is transient for main. Several WMs (GNOME especially)
    then shade-minimize to a tiny title bar instead of a taskbar entry. Detached
    Graph already uses parent=None for this reason. Main closeEvent still calls
    closeAllWindows(), so these stay tied to app lifetime.
    """
    if widget is None:
        return
    flags = (
        Qt.WindowType.Window
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowSystemMenuHint
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    if allowMaximize:
        flags |= Qt.WindowType.WindowMaximizeButtonHint
    widget.setWindowFlags(flags)
    widget.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    if owner is not None and Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"bindIndependentWindow: {widget.objectName() or widget.__class__.__name__}",
        )


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
    if retro:
        handle, handleHover = "#00FF00", "#66FF66"
        app = QApplication.instance()
        light = app is not None and not paletteIsDark(app.palette())
        trackBg = "#e0e0e0" if light else "#333333"
    else:
        app = QApplication.instance()
        dark = paletteIsDark(app.palette()) if app is not None else True
        if dark:
            handle, handleHover, trackBg = "#6a6a6a", "#8a8a8a", "#2a2a2a"
        else:
            handle, handleHover, trackBg = "#9a9a9a", "#7a7a7a", "#e0e0e0"
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
    light = app is not None and not paletteIsDark(app.palette())
    trackBg = "#e0e0e0" if light else "#333333"
    # Neon green paddle; track follows light/dark (was always black).
    retroStyles = f"""
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: #00FF00;
            border-radius: 4px;
            min-height: 24px;
            min-width: 24px;
        }}
        QScrollBar:vertical {{
            background: {trackBg};
            width: 14px;
        }}
        QScrollBar:horizontal {{
            background: {trackBg};
            height: 14px;
        }}
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

# Options → UTC offset combo. Hours include DST when matching the OS clock.
utcOffsetChoices = (
    (-12.0, "UTC-12:00 | Baker Island"),
    (-11.0, "UTC-11:00 | American Samoa"),
    (-10.0, "UTC-10:00 | Hawaii"),
    (-9.5, "UTC-09:30 | Marquesas Islands"),
    (-9.0, "UTC-09:00 | Alaska"),
    (-8.0, "UTC-08:00 | Pacific Time (US & Canada)"),
    (-7.0, "UTC-07:00 | Mountain Time (US & Canada)/Arizona"),
    (-6.0, "UTC-06:00 | Central Time (US & Canada)"),
    (-5.0, "UTC-05:00 | Eastern Time (US & Canada)"),
    (-4.0, "UTC-04:00 | Atlantic Time (Canada)"),
    (-3.5, "UTC-03:30 | Newfoundland"),
    (-3.0, "UTC-03:00 | Brasilia"),
    (-2.0, "UTC-02:00 | Mid-Atlantic"),
    (-1.0, "UTC-01:00 | Cape Verde Is."),
    (0.0, "UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London"),
    (1.0, "UTC+01:00 | Central European Time : Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna"),
    (2.0, "UTC+02:00 | Eastern European Time : Athens, Bucharest, Istanbul"),
    (3.0, "UTC+03:00 | Moscow, St. Petersburg, Volgograd"),
    (3.5, "UTC+03:30 | Tehran"),
    (4.0, "UTC+04:00 | Abu Dhabi, Muscat"),
    (4.5, "UTC+04:30 | Kabul"),
    (5.0, "UTC+05:00 | Islamabad, Karachi, Tashkent"),
    (5.5, "UTC+05:30 | Chennai, Kolkata, Mumbai, New Delhi"),
    (5.75, "UTC+05:45 | Kathmandu"),
    (6.0, "UTC+06:00 | Astana, Dhaka"),
    (6.5, "UTC+06:30 | Yangon (Rangoon)"),
    (7.0, "UTC+07:00 | Bangkok, Hanoi, Jakarta"),
    (8.0, "UTC+08:00 | Beijing, Chongqing, Hong Kong, Urumqi"),
    (8.75, "UTC+08:45 | Eucla"),
    (9.0, "UTC+09:00 | Osaka, Sapporo, Tokyo"),
    (9.5, "UTC+09:30 | Adelaide, Darwin"),
    (10.0, "UTC+10:00 | Brisbane, Canberra, Melbourne, Sydney"),
    (10.5, "UTC+10:30 | Lord Howe Island"),
    (11.0, "UTC+11:00 | Solomon Is., New Caledonia"),
    (12.0, "UTC+12:00 | Auckland, Wellington"),
    (12.75, "UTC+12:45 | Chatham Islands"),
    (13.0, "UTC+13:00 | Samoa"),
    (14.0, "UTC+14:00 | Kiritimati"),
)


def localUtcOffsetHours():
    """Current OS timezone offset in hours (Windows / Linux / macOS, includes DST)."""
    try:
        delta = datetime.now().astimezone().utcoffset()
        if delta is None:
            return 0.0
        return round(delta.total_seconds() / 3600.0, 2)
    except Exception as e:
        Logic.logMessage("WARN", f"localUtcOffsetHours failed: {e}")
        return 0.0


def utcOffsetLabelForHours(hours):
    """Pick the combo label whose hours match, or the closest listed offset."""
    try:
        hours = round(float(hours), 2)
    except (TypeError, ValueError):
        hours = 0.0
    byHours = {h: label for h, label in utcOffsetChoices}
    if hours in byHours:
        return byHours[hours]
    return min(utcOffsetChoices, key=lambda item: abs(item[0] - hours))[1]


def defaultUtcOffsetLabel():
    """First-install default: the computer's current UTC offset."""
    return utcOffsetLabelForHours(localUtcOffsetHours())

def loadConfig():
    convertConfigToJson()
    configPath = getConfigPath()
    defaults = {
        'lastExportPath': '',
        'lastGraphSavePath': '',
        'debugMode': False,
        'utcOffset': defaultUtcOffsetLabel(),
        'periodOffset': True,
        'hourTimestampMethod': 'EOP',
        'retroMode': False,
        'qaqc': False,
        'rawData': False,
        'lastQuickLook': '',
        # stable = GitHub full releases only; beta = include pre-releases (-rc / -beta)
        'updateChannel': 'stable',
        'colorTheme': 'system',
        'labelDataTypeUSBR': True,
        'labelDataTypeAquarius': True,
        'labelDataTypeUSGS': True,
        'hdbOverwriteFlag': False,
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
                utcOffset = utcOffsetLabelForHours(utcOffset)
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

            # Do not copy TNS_ADMIN into tnsNamesLocation. Env is read at
            # Instant Client setup; persisting it made Options show a system
            # Oracle path on machines that should use packaged network/admin.

            # Write updated config back to file if migrations occurred
            with open(configPath, 'w', encoding='utf-8') as configFile:
                json.dump(config, configFile, indent=2)

            if Config.debug:
                Logic.logMessage("DEBUG", f"Loaded full config: {config}")

            return applyTableColorOverrides(config)
        except Exception as e:
            Logic.logException("Failed to load user.config; using defaults", e)
            return applyTableColorOverrides(defaults)
    else:
        try:
            with open(configPath, 'w', encoding='utf-8') as configFile:
                json.dump(defaults, configFile, indent=2)
            if Config.debug:
                Logic.logMessage("DEBUG", f"Created default user.config with defaults: {defaults}")
        except Exception as e:
            Logic.logException("Failed to create default user.config", e)
        return applyTableColorOverrides(defaults)


def applyTableColorOverrides(settings):
    try:
        from core import TableColors
        TableColors.setOverrides((settings or {}).get("tableColors"))
    except Exception:
        pass
    return settings

def ensurePrivateDir(path):
    """Create a user-only directory on POSIX (no-op mode on Windows)."""
    os.makedirs(path, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except Exception:
            pass
    return path


def ensurePrivateFile(path):
    if os.name != "nt" and path and os.path.isfile(path):
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    return path


def getConfigPath():
    configDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)

    if not os.path.exists(configDir):
        ensurePrivateDir(configDir)
    path = os.path.join(configDir, "user.config")
    if os.path.isfile(path):
        ensurePrivateFile(path)
    return path

def getQuickLookDir():
    quickLookDir = os.path.join(getConfigDir(), "quickLook")
    queryDir = os.path.join(quickLookDir, "query")

    if not os.path.exists(quickLookDir):
        ensurePrivateDir(quickLookDir)

        if Config.debug:
            Logic.logMessage("DEBUG", f"getQuickLookDir: Created quickLook directory: {quickLookDir}")
    if not os.path.exists(queryDir):        
        ensurePrivateDir(queryDir)

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
            'utcOffset': defaultUtcOffsetLabel(),
            'retroFont': True,
            'qaqc': False,
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

savedStyleName = None  # native style key before a Light/Dark Fusion override


def paletteIsDark(pal):
    bg = pal.color(QPalette.ColorRole.Window)
    lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
    return lum < 0.45


def forcedSchemePalette(dark):
    """Fusion-like palette so Light/Dark do not depend on the OS theme."""
    pal = QPalette()
    if dark:
        window, base, alt = QColor(53, 53, 53), QColor(35, 35, 35), QColor(66, 66, 66)
        text, button = QColor(255, 255, 255), QColor(53, 53, 53)
        highlight, disabled = QColor(42, 130, 218), QColor(127, 127, 127)
        placeholder = QColor(160, 160, 160)
        tooltipBg, tooltipFg = QColor(53, 53, 53), QColor(255, 255, 255)
    else:
        window, base, alt = QColor(239, 239, 239), QColor(255, 255, 255), QColor(247, 247, 247)
        text, button = QColor(0, 0, 0), QColor(239, 239, 239)
        highlight, disabled = QColor(48, 140, 198), QColor(120, 120, 120)
        placeholder = QColor(128, 128, 128)
        tooltipBg, tooltipFg = QColor(255, 255, 220), QColor(0, 0, 0)
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, alt)
    pal.setColor(QPalette.ColorRole.ToolTipBase, tooltipBg)
    pal.setColor(QPalette.ColorRole.ToolTipText, tooltipFg)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.PlaceholderText, placeholder)
    pal.setColor(QPalette.ColorRole.Link, highlight)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return pal


def styleKey(app):
    st = app.style()
    if st is None:
        return ''
    return (st.objectName() or '').strip()


def setAppStyle(app, key):
    if not key:
        return
    style = QStyleFactory.create(key)
    if style is not None:
        app.setStyle(style)


def applyHintScheme(app, scheme):
    hints = app.styleHints()
    if hints is None or not hasattr(hints, 'setColorScheme'):
        return
    try:
        hints.setColorScheme(scheme)
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"setColorScheme failed: {e}")


def pushPalette(app, pal):
    """Make this palette what every widget (and Config.systemTextColor) sees."""
    app.setPalette(pal)
    Config.systemTextColor = pal.color(QPalette.ColorRole.Text)
    try:
        widgets = list(app.allWidgets())
    except Exception:
        widgets = list(app.topLevelWidgets())
    for w in widgets:
        try:
            w.setPalette(pal)
            w.update()
        except Exception:
            pass


def windowsAppsUseDark():
    """True if Windows apps are in dark mode; None if unknown / not Windows."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except Exception:
        return None


def applyBasePaneBackground(widget):
    """
    Fill editors / tables / lists with palette Base.

    On Windows the first SQL widgets (from the .ui) often paint Window (too
    light in dark mode) while later tabs use Base. Mark the widget so a later
    theme change can restyle it.
    """
    if widget is None:
        return
    try:
        widget.setProperty("sqlPane", True)
        widget.setBackgroundRole(QPalette.ColorRole.Base)
        widget.setAutoFillBackground(True)
        app = QApplication.instance()
        if app is not None:
            pal = app.palette()
            widget.setPalette(pal)
            vp = getattr(widget, "viewport", None)
            if callable(vp):
                view = vp()
                if view is not None:
                    view.setPalette(pal)
                    view.setBackgroundRole(QPalette.ColorRole.Base)
                    view.setAutoFillBackground(True)
        existing = widget.styleSheet() or ""
        prefix = (
            "/*sql-pane-base*/\n"
            "background-color: palette(base);\n"
            "color: palette(text);\n"
        )
        rest = existing
        if existing.startswith("/*sql-pane-base*/"):
            parts = existing.split("\n", 3)
            rest = parts[3] if len(parts) > 3 else ""
        widget.setStyleSheet(prefix + rest)
        try:
            st = widget.style()
            if st is not None:
                st.unpolish(widget)
                st.polish(widget)
        except Exception:
            pass
        widget.update()
        restyleTextDocument(widget)
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyBasePaneBackground failed: {e}")


def restyleTextDocument(widget):
    """QPlainTextEdit keeps the char color from construction; palette changes
    do not rewrite existing text. Force the current Text role onto the document."""
    if widget is None or not isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return
    try:
        pal = widget.palette()
        text = pal.color(QPalette.ColorRole.Text)
        from PyQt6.QtGui import QTextCharFormat, QTextCursor
        fmt = QTextCharFormat()
        fmt.setForeground(text)
        cursor = widget.textCursor()
        savedPos = cursor.position()
        savedAnchor = cursor.anchor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        cursor.setPosition(savedAnchor)
        cursor.setPosition(savedPos, QTextCursor.MoveMode.KeepAnchor if savedPos != savedAnchor else QTextCursor.MoveMode.MoveAnchor)
        widget.setTextCursor(cursor)
        widget.setCurrentCharFormat(fmt)
    except Exception:
        pass


def restyleMarkedPanes(app):
    try:
        widgets = list(app.allWidgets())
    except Exception:
        return
    for w in widgets:
        try:
            if w.property("sqlPane"):
                applyBasePaneBackground(w)
            elif isinstance(w, (QPlainTextEdit, QTextEdit, QComboBox, QTableWidget, QListWidget)):
                restyleTextDocument(w)
                try:
                    st = w.style()
                    if st is not None:
                        st.unpolish(w)
                        st.polish(w)
                    w.update()
                except Exception:
                    pass
        except Exception:
            pass


def resetStyledButtonHover(button):
    """Clear a stuck hover/pressed icon after a modal dialog or slot error."""
    if button is None:
        return

    def apply():
        try:
            button.setDown(False)
            button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            syncOneIconButton(button)
            st = button.style()
            if st is not None:
                st.unpolish(button)
                st.polish(button)
            button.update()
        except Exception:
            pass

    apply()
    QTimer.singleShot(0, apply)
    QTimer.singleShot(50, apply)
    QTimer.singleShot(150, apply)


def restoreNativePalette(app):
    applyHintScheme(app, Qt.ColorScheme.Unknown)
    current = styleKey(app)
    if savedStyleName and current.lower() != savedStyleName.lower():
        setAppStyle(app, savedStyleName)
    # Empty QPalette() is a baked light palette, not "follow OS".
    pushPalette(app, app.style().standardPalette())


def applyForcedTheme(app, wantDark):
    scheme = Qt.ColorScheme.Dark if wantDark else Qt.ColorScheme.Light
    applyHintScheme(app, scheme)
    # Windows 11 native style paints checkbox/radio indicators from the OS
    # theme and ignores a pushed palette (dark boxes on a light System UI).
    # Fusion honors Light/Dark palettes for those indicators on every machine.
    if sys.platform == 'win32':
        current = styleKey(app)
        if current.lower() != 'fusion':
            setAppStyle(app, 'Fusion')
            applyHintScheme(app, scheme)
    pal = app.style().standardPalette()
    if paletteIsDark(pal) != wantDark:
        current = styleKey(app)
        if current.lower() != 'fusion':
            setAppStyle(app, 'Fusion')
            applyHintScheme(app, scheme)
            pal = app.style().standardPalette()
        if paletteIsDark(pal) != wantDark:
            pal = forcedSchemePalette(wantDark)
    pushPalette(app, pal)


def applyColorTheme(theme=None):
    """
    Light/Dark pretend the OS is in that mode.

    Qt's setColorScheme is only a hint — native GTK and Windows styles often
    keep the real system palette (labels/tables stay dark). We set the hint so
    colorScheme() matches, then install a light or dark palette as the app
    palette (Fusion if the native style still serves the old colors). System
    restores the original style and palette on Linux/macOS. On Windows, System
    follows AppsUseLightTheme with the same Light/Dark palettes — the native
    Windows style does not pick up OS dark mode.
    """
    global savedStyleName
    name = theme if theme is not None else getattr(Config, 'colorTheme', 'system')
    name = str(name or 'system').strip().lower()
    if name not in ('system', 'light', 'dark'):
        name = 'system'
    Config.colorTheme = name
    app = QApplication.instance()
    if app is None:
        return
    if not savedStyleName:
        savedStyleName = styleKey(app)

    if name == 'system':
        osDark = windowsAppsUseDark()
        if osDark is None:
            restoreNativePalette(app)
        else:
            applyForcedTheme(app, wantDark=osDark)
    else:
        applyForcedTheme(app, wantDark=(name == 'dark'))

    restyleMarkedPanes(app)
    try:
        from ui.uiSql import SqlWorkbench
        appWin = None
        for w in app.topLevelWidgets():
            if type(w).__name__ == "uiMain":
                appWin = w
                break
        wb = getattr(appWin, "sqlWorkbench", None) if appWin is not None else None
        if wb is not None and hasattr(wb, "_stylePanes"):
            wb._stylePanes()
    except Exception:
        pass
    # QApplication.setStyle() resets widget fonts to the style default
    # (Segoe UI on Windows). Re-apply bundled Noto / Press Start so Linux
    # and Windows match. Skip the pre-logging startup call — widgets and
    # retroMode are not ready yet.
    if getattr(Logic, 'loggingInitialized', False):
        try:
            propagateUiFont(app)
            logResolvedUiFont(app, where=f'applyColorTheme:{name}')
        except Exception as e:
            Logic.logMessage("WARN", f"applyColorTheme re-apply font failed: {e}")
        try:
            for w in app.topLevelWidgets():
                if type(w).__name__ == "uiMain":
                    graph = getattr(w, "tabGraph", None)
                    if graph is not None and hasattr(graph, "reapplyTheme"):
                        graph.reapplyTheme()
                    break
        except Exception:
            pass
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"applyColorTheme {name} style={styleKey(app)!r} "
            f"darkPalette={paletteIsDark(app.palette())} "
            f"text={Config.systemTextColor.name() if hasattr(Config.systemTextColor, 'name') else Config.systemTextColor}",
        )


def includeDataTypeInLabel(database):
    """Options per-source 'Add Data Type to Labels' (dict headers)."""
    db = (database or '').strip().upper()
    if db.startswith('USBR'):
        return bool(getattr(Config, 'labelDataTypeUSBR', True))
    if db.startswith('AQUARIUS') or db == 'AQUARIUS':
        return bool(getattr(Config, 'labelDataTypeAquarius', True))
    if db.startswith('USGS'):
        return bool(getattr(Config, 'labelDataTypeUSGS', True))
    return True


def hdbOverwriteFlagValue():
    """
    MODIFY_R_BASE OVERWRITE_FLAG from Options → USBR → Overwrite Flag.
    'O' allows replacing an existing HDB value; None binds Oracle NULL.
    """
    val = getattr(Config, 'hdbOverwriteFlag', None)
    if val in (None, False, 0, '', 'N', 'n'):
        return None
    if val in (True, 1, '1', 'O', 'o', 'Y', 'y'):
        return 'O'
    return 'O'


def refreshHdbOverwriteFlag():
    """Re-read Overwrite Flag from user.config (once per upload, not per row)."""
    try:
        path = getConfigPath()
        if not os.path.isfile(path):
            Config.hdbOverwriteFlag = None
            return None
        with open(path, encoding='utf-8') as f:
            settings = json.load(f)
        Config.hdbOverwriteFlag = 'O' if settings.get('hdbOverwriteFlag') else None
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"refreshHdbOverwriteFlag failed: {e}")
    return hdbOverwriteFlagValue()


def hdbAccessDisplayNames():
    """USBR-LCHDB from Config.hdbOracleDatabases entries (drop |SCHEMA)."""
    names = []
    for entry in getattr(Config, 'hdbOracleDatabases', ()) or ():
        raw = str(entry or '').strip()
        if not raw:
            continue
        name = raw.split('|', 1)[0].strip()
        if name:
            names.append(name)
    return names


def applyLiveAppearance(app=None):
    """
    Apply current Config.retroMode + colorTheme without restarting:
    fonts, layouts, scrollbar chrome, SQL panes, open graph.
    """
    app = app or QApplication.instance()
    if app is None:
        return
    if Config.retroMode:
        ensureRetroFontLoaded()
    else:
        ensureDefaultFontLoaded()
    applyColorTheme()
    applyModeControlLayouts(app=app)
    mainTable = None
    queryList = None
    graph = None
    try:
        for w in app.topLevelWidgets():
            if type(w).__name__ == "uiMain":
                mainTable = getattr(w, "mainTable", None)
                q = getattr(w, "winQuery", None)
                queryList = getattr(q, "listQueryList", None) if q is not None else None
                graph = getattr(w, "tabGraph", None)
                if q is not None:
                    applyRetroQueryWindow(q)
                break
    except Exception:
        pass
    setRetroStyles(app, bool(Config.retroMode), mainTable, queryList)
    # Stylesheet / Fusion can reset widget fonts — re-apply after chrome.
    try:
        propagateUiFont(app)
    except Exception:
        pass
    try:
        for w in app.allWidgets():
            if isinstance(w, QListWidget):
                applyCompactListStyle(w)
    except Exception:
        pass
    if mainTable is not None and mainTable.columnCount() > 0:
        try:
            applyTableRowMetrics(mainTable, mainTable.font())
            autoSizeTableColumns(mainTable)
            sizeVerticalHeader(mainTable)
        except Exception as e:
            Logic.logException("applyLiveAppearance: table resize failed", e)
    if graph is not None and hasattr(graph, "reapplyTheme"):
        try:
            graph.reapplyTheme()
        except Exception as e:
            Logic.logException("applyLiveAppearance: graph reapplyTheme failed", e)


def reloadGlobals():
    """Refresh runtime flags from user.config, including retroMode (live apply)."""
    settings = loadConfig()
    Config.debug = settings['debugMode']
    Config.utcOffset = settings['utcOffset']
    Config.periodOffset = resolvePeriodOffset(settings)
    Config.retroMode = bool(settings.get('retroMode', False))
    # rawData / qaqcEnabled are Query-window flags (Quick Look + last query),
    # not Options globals. Do not reload them from user.config.
    theme = str(settings.get('colorTheme') or 'system').strip().lower()
    if theme not in ('system', 'light', 'dark'):
        theme = 'system'
    Config.colorTheme = theme
    Config.labelDataTypeUSBR = bool(settings.get('labelDataTypeUSBR', True))
    Config.labelDataTypeAquarius = bool(settings.get('labelDataTypeAquarius', True))
    Config.labelDataTypeUSGS = bool(settings.get('labelDataTypeUSGS', True))
    Config.hdbOverwriteFlag = 'O' if settings.get('hdbOverwriteFlag') else None
    try:
        from core import TableColors
        TableColors.reloadFromConfig(settings)
    except Exception:
        pass

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"Globals reloaded from user.config, "
            f"periodOffset={Config.periodOffset}, "
            f"hourTimestampMethod={settings.get('hourTimestampMethod')}, "
            f"retroMode={Config.retroMode}",
        )

def defaultConfigDir():
    """
    Per-user config dir without Qt. Matches QStandardPaths AppConfigLocation
    once QApplication.applicationName is 'Data Doctor'.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, "Data Doctor")
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", "Data Doctor"
        )
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(xdg, "Data Doctor")


def getConfigDir():
    configDir = ""
    try:
        loc = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        if loc and os.path.basename(loc.rstrip("\\/")) == "Data Doctor":
            configDir = loc
    except Exception:
        pass
    if not configDir:
        configDir = defaultConfigDir()
    if not os.path.exists(configDir):
        ensurePrivateDir(configDir)
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
        ensurePrivateDir(sqlDir)
        if Config.debug:
            Logic.logMessage("DEBUG", f"getSqlSnippetDir: Created sql directory: {sqlDir}")

    return sqlDir


def sqlSnippetStem(name: str) -> str:
    """Basename only; no path separators or '..'."""
    s = (name or "").strip().replace("\\", "/")
    s = os.path.basename(s)
    if s.lower().endswith(".sql"):
        s = s[:-4]
    if not s or s in (".", "..") or "/" in s or "\\" in s:
        raise ValueError("invalid snippet name")
    return s


def sqlSnippetPath(name: str) -> str:
    stem = sqlSnippetStem(name)
    sqlDir = os.path.realpath(getSqlSnippetDir())
    path = os.path.realpath(os.path.join(sqlDir, stem + ".sql"))
    if os.path.commonpath([sqlDir, path]) != sqlDir:
        raise ValueError("invalid snippet name")
    return path