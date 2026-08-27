# Utils.py

import os
import sys
import json
import configparser
import subprocess
import tempfile
import time
from PyQt6.QtCore import Qt, QStandardPaths, QSize, QObject, QEvent, QTimer
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget,
    QListWidget, QTreeView, QPushButton, QCheckBox, QRadioButton, QComboBox,
    QApplication, QHeaderView, QStyleFactory,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QFontInfo, QFontMetrics, QGuiApplication, QIcon,
    QPixmap, QPalette, QColor, QCursor,
)
from core import Logic, Config, Utils

# Bundled fonts (cross-platform):
#   non-retro → Noto Sans  (matches Seifer's Linux system UI font)
#   retro     → Press Start 2P
defaultFontFamilyCache = None   # Noto Sans
defaultFontLoadAttempted = False
retroFontFamilyCache = None     # Press Start 2P
retroFontLoadAttempted = False

# Point sizes by control role: (non-retro, retro)
# Non-retro: 10pt Noto Sans — matches this machine's GNOME/Qt default.
# Retro: buttons stay at 6 (width/fit tuned); other roles larger so labels/lists/logs aren't tiny.
fontRoleSizes = {
    'ui':     (10, 8),   # labels, checkboxes, radios, combos, tabs, general
    'button': (10, 6),   # QPushButton — retro size kept at tuned 6pt
    'list':   (10, 8),   # list widgets / snippets / quick looks
    'table':  (10, 8),   # data tables
    'log':    (10, 10),  # log viewer
    'code':   (10, 9),   # SQL / plain text editors
    'about':  (10, 9),   # about dialog body (About always forces Press Start)
}

# Bundled default (non-retro) font faces — all register as family "Noto Sans"
defaultFontFiles = (
    'ui/fonts/NotoSans-Regular.ttf',
    'ui/fonts/NotoSans-Bold.ttf',
    'ui/fonts/NotoSans-Italic.ttf',
    'ui/fonts/NotoSans-BoldItalic.ttf',
)

# Absolute geometries that differ by font mode: (x, y, width, height)
# Default = Noto (Seifer-tuned 2026-07-24). Retro = pre-Noto baseline until tuned.
# Only controls listed here are moved; everything else stays at .ui geometry.
controlLayouts = {
    # Every control retro moves must also appear here so retro OFF restores Noto positions.
    'default': {
        # winMain — Data Query tab overlay icons (match winMain.ui; Windows y via platformLayoutYNudge)
        # .ui bases: Refresh (4,6), Undo (40,6), Upload (76,6) — 32×32, 4px gaps
        'btnRefresh': (4, 6, 32, 32),
        'btnUndo': (40, 6, 32, 32),
        'btnUpload': (76, 6, 32, 32),
        # winQuery
        'btnDataIdInfo': (376, 5, 31, 20),
        'btnIntervalInfo': (100, 76, 31, 20),
        'btnQueryOptionsInfo': (110, 401, 31, 20),
        'chkbOverlay': (150, 424, 131, 22),         # .ui
    },
    'retro': {
        # Press Start — same row as default, +34 x / +2 y (historical Refresh offset)
        'btnRefresh': (38, 8, 32, 32),
        'btnUndo': (74, 8, 32, 32),
        'btnUpload': (110, 8, 32, 32),
        'btnDataIdInfo': (406, 5, 31, 20),
        'btnIntervalInfo': (164, 76, 31, 20),
        'btnQueryOptionsInfo': (164, 401, 31, 20),
        'chkbOverlay': (162, 424, 131, 22),
    },
}

# Neon green used for retro scrollbars and tab chrome
retroNeonGreen = '#00FF00'

# Retro-only: smaller Press Start on these (objectName → leave rest at role sizes)
retroSmallFontControls = frozenset({
    'cbUTCOffset',
    'rbCustomDateTime',
    'rbPrevDayToCurrent',
    'rbPrevWeekToCurrent',
    'chkbDelta',
    'chkbOverlay',
    'lblTimeStampMethod',
    'rbBOP',
    'rbEOP',
})
retroSmallFontPt = 6  # one step under general ui 8pt

# Query window text buttons: one point larger than normal button role (retro 6→7, default 10→11)
queryLargeButtonControls = frozenset({
    'btnAddQuery',
    'btnQuery',
})

# Windows + retro only: one point smaller (Press Start is roomier on Win metrics)
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


def _findWindowsLauncherExe(script, cwd):
    """
    Prefer the VB.NET 'Data Doctor.exe' when present next to the install layout
    (zip root / launcher folder / parent of Project Files).
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
               os.path.isfile(os.path.join(Config.appRoot, 'DataDoctor.pyw')):
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
                launcher = _findWindowsLauncherExe(script, cwd)
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
        app = QApplication.instance()

        def quitApp():
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
    """Bundled Press Start 2P — retro mode only."""
    global retroFontFamilyCache, retroFontLoadAttempted
    if retroFontLoadAttempted:
        return retroFontFamilyCache
    retroFontLoadAttempted = True

    family = registerBundledFont(
        'ui/fonts/PressStart2P-Regular.ttf',
        'retro (Press Start 2P)',
    )
    retroFontFamilyCache = family
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
    """Point size for a control role (see fontRoleSizes)."""
    if retro is None:
        retro = bool(getattr(Config, 'retroMode', False))
    defaultPt, retroPt = fontRoleSizes.get(role, fontRoleSizes['ui'])
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
    Roles: ui, button, list, table, log, code, about — see fontRoleSizes.
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
    Vertical section size for data table ROWS (height, not width).

    Non-retro (Noto) on Linux: height+10 looks perfect (existing design).
    Non-retro on Windows: native styles add extra cell margin, so use less pad.
    Retro (Press Start): taller rows — QSS left/right padding only made columns
    wider; height must come from defaultSectionSize.
    """
    if metrics is None:
        if font is None:
            font = makeFontForRole('table')
        metrics = QFontMetrics(font)
    h = metrics.height()
    if Config.retroMode:
        # Press Start metrics.height() is tiny (~11 at 8pt); force real row height
        # Seifer: -2 from prior (was h+18 / min 32)
        return max(h + 16, 30)
    # Non-retro Noto Sans
    if sys.platform == 'win32':
        return max(h + 4, 20)
    return max(h + 10, 22)


def tableHeaderBarHeight(font=None, metrics=None):
    """
    Horizontal header band height (taller in retro for multi-line labels).
    Retro two-part headers use a blank line BETWEEN parts (part1 / blank / part2).
    """
    if metrics is None:
        if font is None:
            font = makeFontForRole('table')
        metrics = QFontMetrics(font)
    h = metrics.height()
    if Config.retroMode:
        # part1 + blank spacer + part2
        return max(h * 3 + 6, 42)
    return 0  # leave native


def formatTableHeaderLabel(text):
    """
    Retro: two-part headers get a blank line BETWEEN the parts (extra space before
    the 2nd line), not after the whole label. Idempotent. Default/Noto: unchanged.

    e.g. "Site Name\\nHOUR" → "Site Name\\n\\nHOUR"
    """
    if text is None:
        return ''
    s = str(text)
    if not Config.retroMode:
        return s
    s = s.strip('\n')
    if '\n' not in s:
        return s
    # First line vs everything after first break (second part may itself have spaces)
    first, rest = s.split('\n', 1)
    first = first.rstrip()
    rest = rest.lstrip('\n').strip()  # drop any prior spacer newlines; keep part-2 text
    if not rest:
        return first
    return f"{first}\n\n{rest}"


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
        if Config.retroMode:
            hHeader.setMinimumHeight(tableHeaderBarHeight(font, metrics))
        else:
            # Restore native header band when leaving retro (toggle / restart)
            hHeader.setMinimumHeight(0)
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyTableRowMetrics failed: {e}")


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
        if Config.retroMode:
            # Clear compact-list override so app-level retro padding applies.
            # Keep sql-pane-base so the snippet list stays Base in dark mode.
            listWidget.setStyleSheet(panePrefix)
            listWidget.setSpacing(0)
            return
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
    Move mode-specific absolute controls (default Noto vs retro Press Start).
    Call after UI load / on mode apply. Unknown names are skipped.
    Windows default mode can apply platformLayoutYNudge (e.g. Refresh/Undo +3 y).
    """
    mode = 'retro' if Config.retroMode else 'default'
    coords = controlLayouts.get(mode) or {}
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

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"applyModeControlLayouts: mode={mode} platform={sys.platform} "
            f"applied={len(byName)}/{len(coords)} yNudges={yNudges or '{}'}",
        )


def retroSpacingStylesheet():
    """
    Retro only — targeted VERTICAL room for Press Start (not width).

    Global padding was removed: left/right QSS on table cells/headers made the
    table look wider without making rows taller. Row height is set in
    tableDefaultRowHeight / applyTableRowMetrics instead.

    Keep only:
      • QTabBar::tab — taller tab labels (vertical pad)
      • QHeaderView::section — vertical pad only (no extra left/right)
      • List items — vertical pad (query/SQL lists)
      • Light checkbox/radio spacing for Press Start density
    """
    if not Config.retroMode:
        return ""
    # Tab chrome + close icons; stripped when retro off
    # (readBaseStylesheet / setRetroStyles rebuild without this block).
    # Hover for close is a 2nd image (same pattern as default dark/light pair).
    green = retroNeonGreen
    return f"""
    /* Retro tabs: neon green + black text. NO tab:hover fill — that lit the whole
       tab and stole hover from the close button. Only close-button:hover changes. */
    QTabBar::tab {{
        background: {green};
        color: #000000;
        padding-top: 6px;
        padding-bottom: 6px;
        padding-left: 8px;
        padding-right: 8px;
        border: 1px solid #00aa00;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {green};
        color: #000000;
        font-weight: bold;
        border: 1px solid #003300;
    }}
    QTabBar::tab:!selected {{
        background: #00cc00;
        color: #000000;
    }}
    /* Keep tab fill stable under mouse (no whole-tab brighten) */
    QTabBar::tab:hover,
    QTabBar::tab:selected:hover {{
        background: {green};
        color: #000000;
    }}
    QTabBar::tab:!selected:hover {{
        background: #00cc00;
        color: #000000;
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
    /* List item air (vertical); keep horizontal small */
    QListWidget::item, QListView::item {{
        padding-top: 5px;
        padding-bottom: 5px;
        padding-left: 3px;
        padding-right: 3px;
        min-height: 1.2em;
    }}
    QCheckBox, QRadioButton {{
        spacing: 10px;
        min-height: 1.3em;
    }}
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
    Retro-only small fonts for named radios/checkboxes/UTC combo (retroSmallFontControls).
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
    retroSmallFont = None
    if Config.retroMode:
        retroSmallFont = makeFontForRole('ui', pointSize=retroSmallFontPt)
    # Windows retro: named Query controls one point smaller
    winRetroSmaller = (
        Config.retroMode and sys.platform == 'win32'
    )
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
            if Config.retroMode and retroSmallFont is not None and name in retroSmallFontControls:
                w.setFont(retroSmallFont)
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
    Config.hdbOverwriteFlag = 'O' if config.get('hdbOverwriteFlag') else None

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
                et = event.type()
                if et == QEvent.Type.Enter:
                    obj.setIcon(QIcon(hoverPixmap))
                elif et in (QEvent.Type.Leave, QEvent.Type.Hide):
                    obj.setIcon(QIcon(normalPixmap))
                elif et == QEvent.Type.MouseButtonPress:
                    obj.setIcon(QIcon(pressedPixmap))
                elif et == QEvent.Type.MouseButtonRelease:
                    # Modal dialogs (History, Categories) can leave underMouse()
                    # stuck True on Windows until a later hover. Sync from cursor.
                    def syncIcon():
                        try:
                            pos = obj.mapFromGlobal(QCursor.pos())
                            if (
                                obj.isVisible()
                                and obj.isEnabled()
                                and obj.rect().contains(pos)
                            ):
                                obj.setIcon(QIcon(hoverPixmap))
                            else:
                                obj.setIcon(QIcon(normalPixmap))
                        except Exception:
                            obj.setIcon(QIcon(normalPixmap))
                    QTimer.singleShot(0, syncIcon)
                return super().eventFilter(obj, event)

        # Install filter (remove any existing to avoid duplicates)
        oldFilt = getattr(button, '_ddIconFilter', None)
        if oldFilt is not None:
            button.removeEventFilter(oldFilt)
        filt = ButtonEventFilter(button)
        button._ddIconFilter = filt
        button.installEventFilter(filt)

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
        'lastGraphSavePath': '',
        'debugMode': False,
        'utcOffset': 'UTC+00:00 | Greenwich Mean Time : Dublin, Edinburgh, Lisbon, London',
        'periodOffset': True,
        'hourTimestampMethod': 'EOP',
        'retroMode': False,
        'qaqc': True,
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

_savedStyleName = None  # native style key before a Light/Dark Fusion override


def _paletteIsDark(pal):
    bg = pal.color(QPalette.ColorRole.Window)
    lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
    return lum < 0.45


def _forcedSchemePalette(dark):
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


def _styleKey(app):
    st = app.style()
    if st is None:
        return ''
    return (st.objectName() or '').strip()


def _setAppStyle(app, key):
    if not key:
        return
    style = QStyleFactory.create(key)
    if style is not None:
        app.setStyle(style)


def _applyHintScheme(app, scheme):
    hints = app.styleHints()
    if hints is None or not hasattr(hints, 'setColorScheme'):
        return
    try:
        hints.setColorScheme(scheme)
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"setColorScheme failed: {e}")


def _pushPalette(app, pal):
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


def _windowsAppsUseDark():
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
        if "/*sql-pane-base*/" not in existing:
            widget.setStyleSheet(
                "/*sql-pane-base*/\n"
                "background-color: palette(base);\n"
                "color: palette(text);\n"
                + existing
            )
    except Exception as e:
        if Config.debug:
            Logic.logMessage("DEBUG", f"applyBasePaneBackground failed: {e}")


def _restyleMarkedPanes(app):
    try:
        widgets = list(app.allWidgets())
    except Exception:
        return
    for w in widgets:
        try:
            if w.property("sqlPane"):
                applyBasePaneBackground(w)
        except Exception:
            pass


def resetStyledButtonHover(button):
    """Clear a stuck hover/pressed icon after a modal dialog (Windows)."""
    if button is None:
        return
    try:
        button.setDown(False)
        button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    except Exception:
        pass


def _restoreNativePalette(app):
    _applyHintScheme(app, Qt.ColorScheme.Unknown)
    current = _styleKey(app)
    if _savedStyleName and current.lower() != _savedStyleName.lower():
        _setAppStyle(app, _savedStyleName)
    # Empty QPalette() is a baked light palette, not "follow OS".
    _pushPalette(app, app.style().standardPalette())


def _applyForcedTheme(app, wantDark):
    scheme = Qt.ColorScheme.Dark if wantDark else Qt.ColorScheme.Light
    _applyHintScheme(app, scheme)
    pal = app.style().standardPalette()
    if _paletteIsDark(pal) != wantDark:
        current = _styleKey(app)
        if current.lower() != 'fusion':
            _setAppStyle(app, 'Fusion')
            _applyHintScheme(app, scheme)
            pal = app.style().standardPalette()
        if _paletteIsDark(pal) != wantDark:
            pal = _forcedSchemePalette(wantDark)
    _pushPalette(app, pal)


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
    global _savedStyleName
    name = theme if theme is not None else getattr(Config, 'colorTheme', 'system')
    name = str(name or 'system').strip().lower()
    if name not in ('system', 'light', 'dark'):
        name = 'system'
    Config.colorTheme = name
    app = QApplication.instance()
    if app is None:
        return
    if not _savedStyleName:
        _savedStyleName = _styleKey(app)

    if name == 'system':
        osDark = _windowsAppsUseDark()
        if osDark is None:
            _restoreNativePalette(app)
        else:
            _applyForcedTheme(app, wantDark=osDark)
    else:
        _applyForcedTheme(app, wantDark=(name == 'dark'))

    _restyleMarkedPanes(app)
    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"applyColorTheme {name} style={_styleKey(app)!r} "
            f"darkPalette={_paletteIsDark(app.palette())} "
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


def reloadGlobals():
    """
    Refresh runtime flags from user.config.

    Config.retroMode is intentionally NOT updated here. Retro fonts/layouts must
    only apply at process start (applyStylesAndFonts). Mid-session reloads of
    retroMode caused Query / tables to partially flip after Options save.
    """
    settings = loadConfig()
    Config.debug = settings['debugMode']
    Config.utcOffset = settings['utcOffset']
    Config.periodOffset = resolvePeriodOffset(settings)
    Config.qaqcEnabled = settings['qaqc']
    Config.rawData = settings['rawData']
    theme = str(settings.get('colorTheme') or 'system').strip().lower()
    if theme not in ('system', 'light', 'dark'):
        theme = 'system'
    Config.colorTheme = theme
    Config.labelDataTypeUSBR = bool(settings.get('labelDataTypeUSBR', True))
    Config.labelDataTypeAquarius = bool(settings.get('labelDataTypeAquarius', True))
    Config.labelDataTypeUSGS = bool(settings.get('labelDataTypeUSGS', True))
    Config.hdbOverwriteFlag = 'O' if settings.get('hdbOverwriteFlag') else None

    if Config.debug:
        Logic.logMessage(
            "DEBUG",
            f"Globals reloaded from user.config, "
            f"periodOffset={Config.periodOffset}, "
            f"hourTimestampMethod={settings.get('hourTimestampMethod')}, "
            f"sessionRetroMode={Config.retroMode} "
            f"(file retroMode={settings.get('retroMode')} applies on next start)",
        )

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