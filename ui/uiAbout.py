# uiAbout.py

import json
import math
import os
import random
import shutil
import struct
import subprocess
import time
import wave

from PyQt6.QtWidgets import (
    QDialog, QLabel, QTextBrowser, QPushButton, QMessageBox,
    QListWidget, QListWidgetItem, QApplication, QAbstractItemView,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QUrl, QSize, QObject, QEvent, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QFont, QIcon, QImage
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6 import uic

from core import Logic, Utils, Version

try:
    import pygame
    from pygame.math import Vector2
except Exception:  # pragma: no cover
    pygame = None
    Vector2 = None


# user.config optional map (refMarks) — short keys, integer values
def _readMark(key):
    try:
        cfg = Utils.loadConfig()
        marks = cfg.get("refMarks") or {}
        return max(0, int(marks.get(key, 0)))
    except Exception:
        return 0


def _writeMark(key, value):
    try:
        cfg = Utils.loadConfig()
        marks = dict(cfg.get("refMarks") or {})
        marks[str(key)] = int(value)
        cfg["refMarks"] = marks
        path = Utils.getConfigPath()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# Populated by _addTitle calls further down in this file.
# Each entry: title (list), splash (launch line), factory(host, markKey)->session, key
_CATALOG = []


def _addTitle(title, splash, factory, markKey):
    """Register a cabinet title. factory(host, markKey) returns a play session."""
    _CATALOG.append({
        "title": title,
        "splash": splash,
        "factory": factory,
        "key": markKey,
    })


class uiAbout(QDialog):
    """About dialog: Retro PNG bg with transparent info overlay and looping music."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winAbout.ui'), self)
        self.winMain = winMain
        self._cabinetMode = False
        self._playMode = False
        self._splashMode = False
        self._cabList = None
        self._cabHeader = None
        self._cabHint = None
        self._playLabel = None
        self._splashBg = None
        self._splashTitle = None
        self._splashRpo = None
        self._splashRpoFx = None
        self._splashAnim = None
        self._splashHoldTimer = None
        self._gameTimer = None
        self._session = None
        self._pendingEntry = None
        self._lastTick = 0.0
        self._playKeys = {
            "left": False, "right": False, "up": False, "down": False,
        }
        self._playPulses = []  # one-shot: escape, space, p, r, click

        # Define controls
        self.backgroundLabel = self.findChild(QLabel, 'backgroundLabel')
        self.textInfo = self.findChild(QTextBrowser, 'textInfo')
        self.buttonSecret = self.findChild(QPushButton, 'buttonSecret')
        self.setFixedSize(900, 479)
        self.setWindowTitle('About Data Doctor')

        # Setup window
        pngPath = Logic.resourcePath('ui/DataDoctor.png')
        pixmap = QPixmap(pngPath)
        scaledPixmap = pixmap.scaled(900, 479, Qt.AspectRatioMode.KeepAspectRatio)
        self.backgroundLabel.setPixmap(scaledPixmap)
        self.backgroundLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # About always uses the pixel font (CRT look), with roomy line-height
        aboutFont = Utils.makeFontForRole('about')
        # Prefer Press Start when available even if retro is off
        fam = Utils.ensureRetroFontLoaded() or aboutFont.family()
        pt = Utils.rolePointSize('about', retro=True)
        retroFontObj = QFont(fam, pt)
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self._retroFam = fam
        self._retroPt = pt
        self.textInfo.setFont(retroFontObj)

        infoList = [
            ('Version', Version.displayVersion()),
            ('GitHub', f'https://github.com/{Version.GITHUB_REPO}'),
            ('Author', 'S31F3R'),
            ('License', 'GPL-3.0'),
            ('Music', 'By Eric Matyas at www.soundimage.org')
        ]

        htmlContent = (
            f'<html><body style="color: white; font-family: \'{fam}\'; '
            f'font-size: {pt}pt; padding-left: 50px; white-space: nowrap; line-height: 2.2;">'
        )

        for label, content in infoList:
            if 'GitHub' in label:
                htmlContent += f'{label}: <a href="{content}" style="color: white;">{content}</a><br>'
            else:
                htmlContent += f'{label}: {content}<br>'
        htmlContent += '</body></html>'

        self.textInfo.setHtml(htmlContent)
        self.textInfo.setOpenExternalLinks(True)
        self.textInfo.setStyleSheet("background-color: transparent; border: none;")
        self.textInfo.setGeometry(70, 140, 800, 200)
        self.setupSecretButton()
        # QMediaPlayer (music role) instead of QSoundEffect (event role): better for a
        # long looping track, and avoids PipeWire/Pulse muting "event" streams on Linux.
        # Same Qt6 APIs on Windows/macOS/Linux — keep audioOutput alive on self.
        self.mediaPlayer = None
        self.audioOutput = None
        self.setupMusic()
        self._ensureCabinetWidgets()
        self._ensurePlayHost()

    def setupMusic(self):
        """Load looping About music. Safe no-op if multimedia backend is unavailable."""
        try:
            wavPath = Logic.resourcePath('ui/sounds/8-Bit-Perplexion.wav')
            self.audioOutput = QAudioOutput(self)
            self.audioOutput.setVolume(0.8)
            self.mediaPlayer = QMediaPlayer(self)
            self.mediaPlayer.setAudioOutput(self.audioOutput)
            self.mediaPlayer.setSource(QUrl.fromLocalFile(wavPath))
            # -1 == QMediaPlayer.Loops.Infinite (literal avoids enum quirks across PyQt builds)
            self.mediaPlayer.setLoops(-1)
            self.mediaPlayer.errorOccurred.connect(self.onMusicError)
        except Exception as e:
            self.mediaPlayer = None
            self.audioOutput = None
            Logic.logMessage("WARN", f"Failed to load about music: {e}")

    def onMusicError(self, error, errorString):
        Logic.logMessage("WARN", f"About music error: {error} {errorString}")

    def startMusic(self):
        if not self.mediaPlayer:
            return
        if self._playMode or self._splashMode:
            return
        # Restart cleanly when the dialog is reopened
        self.mediaPlayer.setPosition(0)
        self.mediaPlayer.play()

    def stopMusic(self):
        if self.mediaPlayer:
            self.mediaPlayer.stop()

    def setupSecretButton(self):
        """Tiny corner control — The Net (1995) π backdoor icon, bottom-right."""
        if not self.buttonSecret:
            return
        # Stay above the background art; bottom-right like Angela's screen
        self.buttonSecret.raise_()
        self.buttonSecret.setGeometry(900 - 26, 479 - 26, 22, 22)
        self.buttonSecret.setText("")
        self.buttonSecret.setFlat(True)
        self.buttonSecret.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buttonSecret.setToolTip("")
        self.buttonSecret.setStyleSheet(
            "QPushButton { border: none; background: transparent; padding: 0; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 25); border-radius: 2px; }"
            "QPushButton:pressed { background: rgba(255, 255, 255, 40); }"
        )
        # Clean 48x48 π glyph for The Net easter egg (bottom-right corner).
        iconPath = Logic.resourcePath('ui/icons/pi.png')
        if os.path.exists(iconPath):
            self.buttonSecret.setIcon(QIcon(iconPath))
        # Movie pi is small and quiet in the corner
        self.buttonSecret.setIconSize(QSize(16, 16))
        self.buttonSecret.clicked.connect(self.buttonSecretPressed)

    def buttonSecretPressed(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle(" ")
        dlg.setText("Are you worthy?")
        dlg.setIcon(QMessageBox.Icon.Question)
        dlg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        noBtn = dlg.addButton("NO", QMessageBox.ButtonRole.RejectRole)
        dlg.setDefaultButton(noBtn)
        dlg.setEscapeButton(noBtn)

        filterObj = _WorthyKeyFilter(dlg, self)
        dlg.installEventFilter(filterObj)
        # Catch keys even when a child has focus
        for child in dlg.findChildren(QObject):
            try:
                child.installEventFilter(filterObj)
            except Exception:
                pass

        dlg.exec()

    def _ensureCabinetWidgets(self):
        """Overlay list used only after the gate. Starfield stays; chrome hides."""
        fam = getattr(self, "_retroFam", "monospace")
        pt = getattr(self, "_retroPt", 9)
        header = QLabel(self)
        header.setObjectName("cabHeader")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setGeometry(0, 70, 900, 40)
        header.setStyleSheet(
            f"color: white; background: transparent; font-family: '{fam}'; font-size: {pt + 2}pt;"
        )
        header.setText("SELECT")
        header.hide()
        self._cabHeader = header

        lst = QListWidget(self)
        lst.setObjectName("cabList")
        lst.setGeometry(180, 120, 540, 280)
        lst.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        lst.setStyleSheet(
            "QListWidget {"
            "  background: transparent; border: none; outline: none;"
            f"  color: white; font-family: '{fam}'; font-size: {pt}pt;"
            "}"
            "QListWidget::item { padding: 14px 8px; color: white; }"
            "QListWidget::item:selected {"
            "  background: rgba(255, 255, 0, 55); color: #ffff66;"
            "}"
            "QListWidget::item:hover { background: rgba(255, 255, 255, 20); }"
            "QScrollBar:vertical { width: 0px; background: transparent; }"
        )
        lst.itemActivated.connect(self._onCabinetActivate)
        lst.installEventFilter(self)
        lst.hide()
        self._cabList = lst

        hint = QLabel(self)
        hint.setObjectName("cabHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setGeometry(0, 420, 900, 30)
        hint.setStyleSheet(
            f"color: rgba(255,255,255,180); background: transparent; "
            f"font-family: '{fam}'; font-size: {max(6, pt - 2)}pt;"
        )
        hint.setText("ENTER  ·  ESC")
        hint.hide()
        self._cabHint = hint

    def _ensurePlayHost(self):
        """In-window canvas + coin-op style splash (shared by every title)."""
        fam = getattr(self, "_retroFam", "monospace")
        pt = getattr(self, "_retroPt", 9)

        play = QLabel(self)
        play.setObjectName("playHost")
        play.setGeometry(0, 0, 900, 479)
        play.setAlignment(Qt.AlignmentFlag.AlignCenter)
        play.setStyleSheet("background-color: black;")
        play.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        play.hide()
        play.installEventFilter(self)
        self._playLabel = play

        bg = QLabel(self)
        bg.setObjectName("splashBg")
        bg.setGeometry(0, 0, 900, 479)
        bg.setStyleSheet("background-color: black;")
        bg.hide()
        self._splashBg = bg

        title = QLabel(self)
        title.setObjectName("splashTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setGeometry(40, 150, 820, 50)
        title.setStyleSheet(
            f"color: #ffff66; background: transparent; "
            f"font-family: '{fam}'; font-size: {pt + 2}pt;"
        )
        title.hide()
        self._splashTitle = title

        rpo = QLabel(self)
        rpo.setObjectName("splashRpo")
        rpo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rpo.setGeometry(40, 240, 820, 40)
        rpo.setText("READY PLAYER ONE")
        rpo.setStyleSheet(
            f"color: #66ffff; background: transparent; "
            f"font-family: '{fam}'; font-size: {pt + 1}pt;"
        )
        fx = QGraphicsOpacityEffect(rpo)
        fx.setOpacity(0.0)
        rpo.setGraphicsEffect(fx)
        rpo.hide()
        self._splashRpo = rpo
        self._splashRpoFx = fx

        self._gameTimer = QTimer(self)
        self._gameTimer.setInterval(16)  # ~60 fps
        self._gameTimer.timeout.connect(self._onGameTick)

        self._splashHoldTimer = QTimer(self)
        self._splashHoldTimer.setSingleShot(True)
        self._splashHoldTimer.timeout.connect(self._onSplashHoldDone)

    def eventFilter(self, obj, event):
        # Catalog navigation
        if (
            self._cabinetMode
            and not self._playMode
            and not self._splashMode
            and obj is self._cabList
            and event.type() == QEvent.Type.KeyPress
        ):
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._closeCabinet()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._launchIndex(self._cabList.currentRow())
                return True

        # In-window play / splash input
        if self._playMode or self._splashMode:
            if obj is self._playLabel or obj is self:
                et = event.type()
                if et == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    self._handlePlayKey(event.key(), True)
                    return True
                if et == QEvent.Type.KeyRelease and not event.isAutoRepeat():
                    self._handlePlayKey(event.key(), False)
                    return True
                if et == QEvent.Type.MouseButtonPress and self._playMode:
                    self._playPulses.append("click")
                    return True
        return super().eventFilter(obj, event)

    def _handlePlayKey(self, key, pressed):
        mapping = {
            Qt.Key.Key_Left: "left", Qt.Key.Key_A: "left",
            Qt.Key.Key_Right: "right", Qt.Key.Key_D: "right",
            Qt.Key.Key_Up: "up", Qt.Key.Key_W: "up",
            Qt.Key.Key_Down: "down", Qt.Key.Key_S: "down",
        }
        if key in mapping:
            self._playKeys[mapping[key]] = pressed
            return
        if not pressed:
            return
        if key == Qt.Key.Key_Escape:
            self._playPulses.append("escape")
        elif key == Qt.Key.Key_Space:
            self._playPulses.append("space")
        elif key in (Qt.Key.Key_P,):
            self._playPulses.append("p")
        elif key in (Qt.Key.Key_R,):
            self._playPulses.append("r")

    def _openCabinet(self):
        if self.textInfo is not None:
            self.textInfo.hide()
        if self.buttonSecret is not None:
            self.buttonSecret.hide()
        self._cabinetMode = True
        self._refreshCatalog()
        self._showCatalogChrome(True)
        if self._cabList is not None:
            self._cabList.setFocus(Qt.FocusReason.OtherFocusReason)

    def _showCatalogChrome(self, visible):
        for w in (self._cabHeader, self._cabList, self._cabHint):
            if w is None:
                continue
            if visible:
                w.show()
                w.raise_()
            else:
                w.hide()

    def _closeCabinet(self):
        self._stopEmbeddedSession()
        self._hideSplash()
        self._showCatalogChrome(False)
        self._cabinetMode = False
        self._playMode = False
        self._splashMode = False
        if self.textInfo is not None:
            self.textInfo.show()
        if self.buttonSecret is not None:
            self.buttonSecret.show()
            self.buttonSecret.raise_()

    def _resetToDefaultAbout(self):
        """Full reset used on close so next open is stock About."""
        self._stopEmbeddedSession()
        self._hideSplash()
        self._showCatalogChrome(False)
        self._cabinetMode = False
        self._playMode = False
        self._splashMode = False
        self._pendingEntry = None
        self._playKeys = {k: False for k in self._playKeys}
        self._playPulses = []
        if self._playLabel is not None:
            self._playLabel.hide()
            self._playLabel.clear()
        if self.textInfo is not None:
            self.textInfo.show()
        if self.buttonSecret is not None:
            self.buttonSecret.show()
            self.buttonSecret.raise_()

    def _refreshCatalog(self):
        if self._cabList is None:
            return
        self._cabList.clear()
        for entry in _CATALOG:
            mark = _readMark(entry["key"])
            label = entry["title"]
            if mark > 0:
                label = f"{entry['title']}    HI {mark}"
            item = QListWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            item.setData(Qt.ItemDataRole.UserRole, entry["key"])
            self._cabList.addItem(item)
        if self._cabList.count() > 0:
            self._cabList.setCurrentRow(0)

    def _onCabinetActivate(self, item):
        if item is None:
            return
        self._launchIndex(self._cabList.row(item))

    def _launchIndex(self, row):
        if row < 0 or row >= len(_CATALOG):
            return
        entry = _CATALOG[row]
        if pygame is None or entry.get("factory") is None:
            QMessageBox.information(self, " ", "Unavailable")
            return
        self.stopMusic()
        self._showCatalogChrome(False)
        self._startSplash(entry)

    def _startSplash(self, entry):
        """Shared coin-op intro: title line, then fade READY PLAYER ONE, hold, play."""
        self._stopEmbeddedSession()
        self._pendingEntry = entry
        self._splashMode = True
        self._playMode = False

        if self._splashTitle is not None:
            self._splashTitle.setText(entry.get("splash") or entry.get("title") or "")
        if self._splashRpoFx is not None:
            self._splashRpoFx.setOpacity(0.0)

        for w in (self._splashBg, self._splashTitle, self._splashRpo):
            if w is not None:
                w.show()
                w.raise_()

        # Cancel any prior anim/hold
        if self._splashAnim is not None:
            try:
                self._splashAnim.stop()
            except Exception:
                pass
            self._splashAnim = None
        if self._splashHoldTimer is not None:
            self._splashHoldTimer.stop()

        # Fade in secondary line (~1.6s), then hold ~2s before play
        if self._splashRpoFx is not None:
            anim = QPropertyAnimation(self._splashRpoFx, b"opacity", self)
            anim.setDuration(1600)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            anim.finished.connect(self._onSplashFadeDone)
            self._splashAnim = anim
            anim.start()
        else:
            self._onSplashFadeDone()

    def _onSplashFadeDone(self):
        if not self._splashMode:
            return
        if self._splashHoldTimer is not None:
            self._splashHoldTimer.start(2000)

    def _onSplashHoldDone(self):
        if not self._splashMode:
            return
        entry = self._pendingEntry
        self._hideSplash()
        if entry is None:
            self._returnToCatalog()
            return
        self._beginEmbeddedSession(entry)

    def _hideSplash(self):
        self._splashMode = False
        if self._splashAnim is not None:
            try:
                self._splashAnim.stop()
            except Exception:
                pass
            self._splashAnim = None
        if self._splashHoldTimer is not None:
            self._splashHoldTimer.stop()
        for w in (self._splashBg, self._splashTitle, self._splashRpo):
            if w is not None:
                w.hide()
        if self._splashRpoFx is not None:
            self._splashRpoFx.setOpacity(0.0)

    def _beginEmbeddedSession(self, entry):
        self._pendingEntry = None
        self._playMode = True
        self._playKeys = {k: False for k in self._playKeys}
        self._playPulses = []
        self._lastTick = time.perf_counter()

        try:
            self._session = entry["factory"](self, entry["key"])
        except Exception as e:
            Logic.logMessage("WARN", f"Optional view failed: {e}")
            self._playMode = False
            self._returnToCatalog()
            return

        if self._playLabel is not None:
            self._playLabel.show()
            self._playLabel.raise_()
            self._playLabel.setFocus(Qt.FocusReason.OtherFocusReason)
            self._playLabel.clear()

        if self._gameTimer is not None:
            self._gameTimer.start()

    def _onGameTick(self):
        if not self._playMode or self._session is None:
            return
        now = time.perf_counter()
        dt = max(0.0, min(0.05, now - self._lastTick))
        self._lastTick = now
        try:
            img = self._session.tick(dt, self._playKeys, self._playPulses)
            self._playPulses = []
            if img is not None and self._playLabel is not None:
                self._playLabel.setPixmap(QPixmap.fromImage(img))
            if not getattr(self._session, "running", True):
                self._stopEmbeddedSession()
                self._returnToCatalog()
        except Exception as e:
            Logic.logMessage("WARN", f"Optional view failed: {e}")
            self._stopEmbeddedSession()
            self._returnToCatalog()

    def _stopEmbeddedSession(self):
        if self._gameTimer is not None:
            self._gameTimer.stop()
        sess = self._session
        self._session = None
        self._playMode = False
        if sess is not None:
            try:
                sess.stop()
            except Exception:
                pass
        if self._playLabel is not None:
            self._playLabel.hide()
            self._playLabel.clear()
        self._playKeys = {k: False for k in self._playKeys}
        self._playPulses = []

    def _returnToCatalog(self):
        self._hideSplash()
        self._stopEmbeddedSession()
        if self._cabinetMode:
            self._showCatalogChrome(True)
            self._refreshCatalog()
            if self._cabList is not None:
                self._cabList.setFocus(Qt.FocusReason.OtherFocusReason)
            # Soft ambient while browsing list
            self.startMusic()
        else:
            self.startMusic()

    def keyPressEvent(self, event):
        if self._splashMode:
            # Allow skip: Esc cancels to catalog; Space/Enter skips hold after fade
            if event.key() == Qt.Key.Key_Escape:
                self._hideSplash()
                self._returnToCatalog()
                return
            if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Only skip remaining hold if already fully faded
                if self._splashRpoFx is not None and self._splashRpoFx.opacity() >= 0.99:
                    if self._splashHoldTimer is not None:
                        self._splashHoldTimer.stop()
                    self._onSplashHoldDone()
                return
        if self._playMode:
            if not event.isAutoRepeat():
                self._handlePlayKey(event.key(), True)
            return
        if self._cabinetMode:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._closeCabinet()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._cabList is not None:
                    self._launchIndex(self._cabList.currentRow())
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self._playMode and not event.isAutoRepeat():
            self._handlePlayKey(event.key(), False)
            return
        super().keyReleaseEvent(event)

    def showEvent(self, event):
        Utils.centerWindowToParent(self)
        # Never resume mid-cabinet/play after a close — stock About only
        if not self._cabinetMode and not self._playMode and not self._splashMode:
            if self.textInfo is not None:
                self.textInfo.show()
            if self.buttonSecret is not None:
                self.buttonSecret.show()
                self.buttonSecret.raise_()
            self.startMusic()
        super().showEvent(event)

    def closeEvent(self, event):
        self.stopMusic()
        self._resetToDefaultAbout()
        super().closeEvent(event)

    def reject(self):
        # Esc / dialog reject also forces stock About next time
        self.stopMusic()
        self._resetToDefaultAbout()
        super().reject()


class _WorthyKeyFilter(QObject):
    """Key sequence gate for the worthy dialog. Opaque on purpose."""

    def __init__(self, dialog, about):
        super().__init__(dialog)
        self._dialog = dialog
        self._about = about
        self._buf = []
        # Arrow form + letter tail; WASD form is accepted via remaps below
        self._need = [
            Qt.Key.Key_Up, Qt.Key.Key_Up,
            Qt.Key.Key_Down, Qt.Key.Key_Down,
            Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_B, Qt.Key.Key_A,
        ]
        self._done = False

    def _mapKey(self, key, text):
        # WASD ↔ arrows; B/A letters (any case)
        if key in (Qt.Key.Key_W,):
            return Qt.Key.Key_Up
        if key in (Qt.Key.Key_S,):
            return Qt.Key.Key_Down
        if key in (Qt.Key.Key_A,):
            # Ambiguous: A is both left (WASD) and the final letter.
            # Prefer letter A when we are already past the directional prefix.
            if len(self._buf) >= 8:
                return Qt.Key.Key_A
            return Qt.Key.Key_Left
        if key in (Qt.Key.Key_D,):
            return Qt.Key.Key_Right
        if key in (Qt.Key.Key_B,):
            return Qt.Key.Key_B
        if key in (
            Qt.Key.Key_Up, Qt.Key.Key_Down,
            Qt.Key.Key_Left, Qt.Key.Key_Right,
        ):
            return key
        # Typed character fallback (e.g. some layouts)
        ch = (text or '').lower()
        if ch == 'w':
            return Qt.Key.Key_Up
        if ch == 's':
            return Qt.Key.Key_Down
        if ch == 'a':
            if len(self._buf) >= 8:
                return Qt.Key.Key_A
            return Qt.Key.Key_Left
        if ch == 'd':
            return Qt.Key.Key_Right
        if ch == 'b':
            return Qt.Key.Key_B
        return None

    def eventFilter(self, obj, event):
        if self._done or event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(obj, event)

        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._buf == self._need:
                self._done = True
                self._dialog.done(1)
                about = self._about
                if about is not None:
                    QApplication.instance().processEvents()
                    about._openCabinet()
                return True
            # Wrong sequence + Enter: reset and stay on dialog
            self._buf = []
            return True

        mapped = self._mapKey(key, event.text())
        if mapped is None:
            # Ignore modifiers / unrelated keys without full reset (shift on BA)
            if key in (
                Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
                Qt.Key.Key_Meta, Qt.Key.Key_CapsLock,
            ):
                return False
            self._buf = []
            return False

        expected = self._need[len(self._buf)] if len(self._buf) < len(self._need) else None
        if expected is not None and mapped == expected:
            self._buf.append(mapped)
        else:
            # Restart if this key could begin a new attempt
            if mapped == self._need[0]:
                self._buf = [mapped]
            else:
                self._buf = []
        return True


# ===========================================================================
# Below: cabinet titles (keep additions registered via _addTitle)
# ===========================================================================


if pygame is not None:
    # Screen matches the Data Doctor About dialog (winAbout.ui / uiAbout.py): 900 x 479
    windowWidth = 900
    windowHeight = 479
    mazeCols = 28
    mazeRows = 26
    # Largest integer tile that still leaves a HUD strip inside 479px height
    tileSize = (windowHeight - 36) // mazeRows  # 17 → maze 476 x 442, HUD 37px
    mazePixelW = mazeCols * tileSize
    mazePixelH = mazeRows * tileSize
    hudHeight = windowHeight - mazePixelH
    # Horizontal centering offset (playfield is narrower than the window)
    offsetX = (windowWidth - mazePixelW) // 2
    offsetY = 0
    width = windowWidth
    height = windowHeight
    # Speeds were tuned at tileSize 16; scale so feel stays consistent
    speedScale = tileSize / 16.0
    fps = 60
    sampleRate = 22050

    # Colors
    BLACK = (0, 0, 0)
    BLUE = (0, 0, 200)
    WHITE = (255, 255, 255)
    YELLOW = (255, 255, 0)
    RED = (255, 0, 0)
    PINK = (255, 184, 255)
    CYAN = (0, 255, 255)
    ORANGE = (255, 184, 82)
    frightenedBlue = (33, 33, 255)
    frightenedWhite = (255, 255, 255)

    # Game constants (speeds scale with tile size)
    pacmanSpeed = 2.0 * speedScale
    ghostSpeedBase = 1.75 * speedScale
    pelletPoints = 10
    powerPelletPoints = 50
    ghostPoints = [200, 400, 800, 1600]
    centerSnap = 2.5 * speedScale  # How close to tile center before allowing a turn

    # Rows that open to the side tunnels (wrap left/right)
    tunnelRows = frozenset({8, 9, 10, 14, 15, 16})

    # Classic-ish maze layout
    # 0 = empty/walkable, 1 = wall, 2 = pellet, 3 = power pellet
    mazeLayout = [
        "1111111111111111111111111111",
        "1222222222222112222222222221",
        "1211112111112112111112111121",
        "1311112111112112111112111131",
        "1222222222222222222222222221",
        "1211112112111111112112111121",
        "1222222112222112222112222221",
        "1111112111110110111112111111",
        "0000012111110110111112100000",
        "0000012110000000000112100000",
        "0000012110111111110112100000",
        "1111112110111111110112111111",
        "1000000000000000000000000001",
        "1111112110111111110112111111",
        "0000012110111111110112100000",
        "0000012110000000000112100000",
        "0000012110111111110112100000",
        "1111112110111111110112111111",
        "1222222222222112222222222221",
        "1211112111112112111112111121",
        "1322212112222222222112112231",
        "1111212112111111112112111211",
        "1222212222222112222222221221",
        "1211112111112112111112111121",
        "1222222222222222222222222221",
        "1111111111111111111111111111",
    ]


    def loadMaze():
        maze = []
        pellets = []
        powerPellets = []
        for y, row in enumerate(mazeLayout):
            mazeRow = []
            for x, char in enumerate(row):
                if char == "1":
                    mazeRow.append(1)
                else:
                    mazeRow.append(0)
                    if char == "2":
                        pellets.append((x, y))
                    elif char == "3":
                        powerPellets.append((x, y))
            maze.append(mazeRow)
        return maze, pellets, powerPellets


    maze, initialPellets, initialPowerPellets = loadMaze()


    def isWall(x, y):
        """Check if tile (x, y) is a wall. Tunnel rows wrap off-screen."""
        if y < 0 or y >= mazeRows:
            return True
        if x < 0 or x >= mazeCols:
            return y not in tunnelRows
        return maze[y][x] == 1


    def getTileCenter(tx, ty):
        return Vector2(tx * tileSize + tileSize // 2, ty * tileSize + tileSize // 2)


    def applyTunnelWrap(pos):
        """Wrap horizontally through side tunnels."""
        maxX = mazeCols * tileSize
        if pos.x < 0:
            pos.x += maxX
        elif pos.x >= maxX:
            pos.x -= maxX
        return pos


    def tileFromPos(pos):
        tx = int(pos.x // tileSize) % mazeCols
        ty = int(pos.y // tileSize)
        return tx, ty


    # ---------------------------------------------------------------------------
    # Sound generation (classic arcade-style effects, synthesized)
    # ---------------------------------------------------------------------------

    def clampSample(value):
        return max(-32767, min(32767, int(value)))


    def writeWav(path, samples):
        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sampleRate)
            frames = b"".join(struct.pack("<h", clampSample(s)) for s in samples)
            wf.writeframes(frames)


    def sineWave(freq, t):
        return math.sin(2 * math.pi * freq * t)


    def squareWave(freq, t):
        return 1.0 if sineWave(freq, t) >= 0 else -1.0


    def envelope(i, n, attack=0.02, release=0.15):
        if n <= 1:
            return 0.0
        t = i / (n - 1)
        a = min(1.0, t / attack) if attack > 0 else 1.0
        r = min(1.0, (1.0 - t) / release) if release > 0 else 1.0
        return a * r


    def genWakka(high=True):
        """Classic short chomp — alternating high/low chirp."""
        freq = 740 if high else 520
        n = int(sampleRate * 0.07)
        samples = []
        for i in range(n):
            t = i / sampleRate
            env = envelope(i, n, 0.01, 0.35)
            samples.append(9000 * env * squareWave(freq, t))
        return samples


    def genEatGhost():
        """Ascending blips when a frightened ghost is eaten."""
        samples = []
        for step, freq in enumerate((400, 530, 700, 920, 1200)):
            n = int(sampleRate * 0.07)
            for i in range(n):
                t = i / sampleRate
                env = envelope(i, n, 0.05, 0.25)
                samples.append(11000 * env * sineWave(freq, t))
        return samples


    def genDeath():
        """Descending warble for Pac-Man death."""
        samples = []
        duration = 1.4
        n = int(sampleRate * duration)
        for i in range(n):
            t = i / sampleRate
            # Falling base tone with vibrato
            base = 700 - 450 * (t / duration)
            vib = 30 * math.sin(2 * math.pi * 12 * t)
            env = envelope(i, n, 0.02, 0.2) * (1.0 - 0.3 * (t / duration))
            samples.append(12000 * env * sineWave(base + vib, t))
        return samples


    def genPowerPellet():
        """Bright ding for power pellet."""
        samples = []
        for freq in (520, 780, 1040):
            n = int(sampleRate * 0.09)
            for i in range(n):
                t = i / sampleRate
                env = envelope(i, n, 0.02, 0.4)
                samples.append(10000 * env * sineWave(freq, t))
        return samples


    def genStartJingle():
        """Short intro-style jingle."""
        notes = [
            (392, 0.12), (523, 0.12), (659, 0.12), (784, 0.18),
            (659, 0.10), (784, 0.28),
        ]
        samples = []
        for freq, dur in notes:
            n = int(sampleRate * dur)
            for i in range(n):
                t = i / sampleRate
                env = envelope(i, n, 0.04, 0.25)
                tone = 0.7 * sineWave(freq, t) + 0.3 * sineWave(freq * 2, t)
                samples.append(10000 * env * tone)
        return samples


    def genExtraLife():
        """Extra-life / level-clear sparkle."""
        samples = []
        for freq in (880, 1175, 1480, 1760):
            n = int(sampleRate * 0.08)
            for i in range(n):
                t = i / sampleRate
                env = envelope(i, n, 0.03, 0.3)
                samples.append(9000 * env * sineWave(freq, t))
        return samples


    def genSiren(frightened=False):
        """Looping ghost siren (normal or frightened)."""
        duration = 0.45
        n = int(sampleRate * duration)
        samples = []
        lo, hi = (180, 320) if not frightened else (280, 480)
        for i in range(n):
            t = i / sampleRate
            # Triangle-ish sweep up then down
            phase = (t / duration) * 2.0
            if phase > 1.0:
                phase = 2.0 - phase
            freq = lo + (hi - lo) * phase
            env = 0.55
            samples.append(7000 * env * sineWave(freq, t))
        return samples


    def ensureSoundFiles(soundDir):
        """Fill missing clips only when the directory is writable (dev fallback)."""
        if not soundDir or not os.path.isdir(soundDir):
            return
        if not os.access(soundDir, os.W_OK):
            return
        generators = {
            "n0.wav": lambda: genWakka(True),
            "n1.wav": lambda: genWakka(False),
            "n2.wav": genEatGhost,
            "n3.wav": genDeath,
            "n4.wav": genPowerPellet,
            "n5.wav": genStartJingle,
            "n6.wav": genExtraLife,
            "n7.wav": lambda: genSiren(False),
            "n8.wav": lambda: genSiren(True),
        }
        for name, gen in generators.items():
            path = os.path.join(soundDir, name)
            if not os.path.isfile(path):
                try:
                    writeWav(path, gen())
                except OSError:
                    pass




    class SoundManager:
        """Plays classic arcade SFX via pygame.mixer, or simpleaudio as fallback."""

        mapping = {
            "wakka0": "n0.wav",
            "wakka1": "n1.wav",
            "eatGhost": "n2.wav",
            "death": "n3.wav",
            "powerPellet": "n4.wav",
            "start": "n5.wav",
            "extraLife": "n6.wav",
            "siren": "n7.wav",
            "frightened": "n8.wav",
        }

        def __init__(self, soundDir):
            self.enabled = False
            self.backend = None  # "pygame" or "simpleaudio"
            self.sounds = {}
            self.paths = {}
            self.wakkaToggle = 0
            self.loopKey = None
            self.loopPlay = None  # simpleaudio PlayObject or pygame Channel
            self.soundDir = soundDir

            ensureSoundFiles(soundDir)
            for key, filename in self.mapping.items():
                self.paths[key] = os.path.join(soundDir, filename)

            if self.initPygameMixer():
                self.backend = "pygame"
                self.enabled = True
                return
            if self.initPaplay():
                self.backend = "paplay"
                self.enabled = True
                return
            pass  # silent if no audio backend

        def initPygameMixer(self):
            try:
                _ = pygame.mixer.get_init
            except (NotImplementedError, AttributeError):
                return False
            try:
                if pygame.mixer.get_init() is None:
                    pygame.mixer.init(frequency=sampleRate, size=-16, channels=1, buffer=512)
            except (pygame.error, NotImplementedError):
                return False

            volumes = {
                "wakka0": 0.35, "wakka1": 0.35, "eatGhost": 0.55, "death": 0.6,
                "powerPellet": 0.5, "start": 0.45, "extraLife": 0.5,
                "siren": 0.22, "frightened": 0.28,
            }
            loaded = False
            for key, path in self.paths.items():
                try:
                    snd = pygame.mixer.Sound(path)
                    snd.set_volume(volumes.get(key, 0.5))
                    self.sounds[key] = snd
                    loaded = True
                except (pygame.error, NotImplementedError):
                    self.sounds[key] = None
            return loaded

        def initPaplay(self):
            """Fallback: PulseAudio paplay (works when pygame.mixer is missing)."""
            self.paplayBin = shutil.which("paplay")
            if not self.paplayBin:
                return False
            # Need at least the wav files on disk
            return all(os.path.isfile(p) for p in self.paths.values())

        def play(self, name):
            if not self.enabled:
                return
            if self.backend == "pygame":
                snd = self.sounds.get(name)
                if not snd:
                    return
                try:
                    snd.play()
                except (pygame.error, NotImplementedError):
                    pass
                return

            # paplay one-shot
            path = self.paths.get(name)
            if not path:
                return
            try:
                subprocess.Popen(
                    [self.paplayBin, path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        def playWakka(self):
            name = "wakka0" if self.wakkaToggle == 0 else "wakka1"
            self.wakkaToggle = 1 - self.wakkaToggle
            self.play(name)

        def startSiren(self, frightened=False):
            if not self.enabled:
                return
            self.stopLoops()
            key = "frightened" if frightened else "siren"
            self.loopKey = key
            if self.backend == "pygame":
                snd = self.sounds.get(key)
                if not snd:
                    self.loopKey = None
                    return
                try:
                    self.loopPlay = snd.play(loops=-1)
                except (pygame.error, NotImplementedError):
                    self.loopKey = None
                    self.loopPlay = None
                return

            # paplay: launch first loop iteration; updateLoops restarts it
            self.spawnPaplayLoop()

        def spawnPaplayLoop(self):
            path = self.paths.get(self.loopKey) if self.loopKey else None
            if not path:
                return
            try:
                self.loopPlay = subprocess.Popen(
                    [self.paplayBin, path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                self.loopPlay = None

        def updateLoops(self):
            """Restart paplay loop clips when they finish."""
            if not self.enabled or self.backend != "paplay" or not self.loopKey:
                return
            proc = self.loopPlay
            if proc is None or proc.poll() is not None:
                self.spawnPaplayLoop()

        def stopLoops(self):
            play = self.loopPlay
            self.loopKey = None
            self.loopPlay = None
            if not play:
                return
            try:
                if self.backend == "pygame":
                    play.stop()
                else:
                    play.terminate()
            except Exception:
                pass


    # ---------------------------------------------------------------------------
    # Entities
    # ---------------------------------------------------------------------------

    class PacMan:
        def __init__(self):
            self.tileX = 13
            self.tileY = 24  # Bottom center lane (walkable)
            self.pos = getTileCenter(self.tileX, self.tileY)
            self.direction = Vector2(-1, 0)  # Classic: starts facing left
            self.nextDirection = Vector2(-1, 0)
            self.radius = tileSize // 2 - 2
            self.mouthPhase = 0.0
            self.speed = pacmanSpeed

        def readInput(self, keys):
            # keys is a held-direction dict from the About host (not pygame key array)
            if keys.get("left"):
                self.nextDirection = Vector2(-1, 0)
            elif keys.get("right"):
                self.nextDirection = Vector2(1, 0)
            elif keys.get("up"):
                self.nextDirection = Vector2(0, -1)
            elif keys.get("down"):
                self.nextDirection = Vector2(0, 1)

        def alignToLane(self):
            """Keep Pac-Man centered in the corridor he is traveling."""
            if self.direction.x != 0:
                # Horizontal travel: lock Y to tile center
                ty = int(self.pos.y // tileSize)
                self.pos.y = ty * tileSize + tileSize // 2
            elif self.direction.y != 0:
                # Vertical travel: lock X to tile center
                tx = int(self.pos.x // tileSize)
                # Do not break tunnel wrap mid-tile
                if 0 <= self.pos.x < mazeCols * tileSize:
                    self.pos.x = tx * tileSize + tileSize // 2

        def canEnter(self, tx, ty):
            return not isWall(tx, ty)

        def tryTurn(self):
            """At tile centers, adopt nextDirection if the tile ahead is free."""
            if self.nextDirection.length_squared() == 0:
                return

            # Already moving that way — do not re-snap to center (that freezes movement)
            if (self.direction.x == self.nextDirection.x
                    and self.direction.y == self.nextDirection.y):
                return

            # Reverse is always allowed mid-tile (classic Pac-Man feel)
            if (self.direction.length_squared() > 0
                    and self.nextDirection.x == -self.direction.x
                    and self.nextDirection.y == -self.direction.y):
                self.direction = Vector2(self.nextDirection)
                return

            tx, ty = tileFromPos(self.pos)
            center = getTileCenter(tx, ty)
            dx = abs(self.pos.x - center.x)
            dy = abs(self.pos.y - center.y)
            # Must be near the center to take a perpendicular turn
            if dx > centerSnap or dy > centerSnap:
                return

            nextTx = tx + int(self.nextDirection.x)
            nextTy = ty + int(self.nextDirection.y)
            if self.canEnter(nextTx, nextTy):
                self.pos = Vector2(center)
                self.direction = Vector2(self.nextDirection)

        def update(self, dt, keys):
            self.readInput(keys)
            self.tryTurn()
            self.alignToLane()

            if self.direction.length_squared() == 0:
                self.mouthPhase = 0.0
                return

            move = self.direction * self.speed
            newPos = self.pos + move

            # Probe a point just ahead of the sprite
            probeX = newPos.x + self.direction.x * (self.radius + 1)
            probeY = newPos.y + self.direction.y * (self.radius + 1)
            probeTileX = int(math.floor(probeX / tileSize))
            probeTileY = int(math.floor(probeY / tileSize))

            if not isWall(probeTileX, probeTileY):
                self.pos = applyTunnelWrap(newPos)
                self.alignToLane()
            else:
                # Stop flush at the center of the current tile
                tx, ty = tileFromPos(self.pos)
                self.pos = getTileCenter(tx, ty)
                self.direction = Vector2(0, 0)

            # Mouth chomp animation
            self.mouthPhase += 14.0 * dt
            if self.mouthPhase > 1.0:
                self.mouthPhase -= 1.0

        def draw(self, screen):
            px, py = int(round(self.pos.x)), int(round(self.pos.y))
            pygame.draw.circle(screen, YELLOW, (px, py), self.radius)

            if self.direction.length_squared() > 0:
                angle = math.atan2(self.direction.y, self.direction.x)
            else:
                angle = 0.0

            # Mouth opens and closes (0 .. ~40 degrees)
            openAmount = abs(math.sin(self.mouthPhase * math.pi)) * math.radians(40)
            if openAmount < 0.05:
                return

            mouthStart = angle + openAmount
            mouthEnd = angle - openAmount
            points = [(px, py)]
            for i in range(12):
                a = mouthStart + (mouthEnd - mouthStart) * (i / 11)
                points.append((px + math.cos(a) * self.radius,
                               py + math.sin(a) * self.radius))
            pygame.draw.polygon(screen, BLACK, points)

        def getTile(self):
            return tileFromPos(self.pos)


    class Ghost:
        # Spawn tiles (all walkable open tiles in/near the house)
        spawnTiles = {
            "Blinky": (13, 9),
            "Pinky": (12, 9),
            "Inky": (14, 9),
            "Clyde": (15, 9),
        }
        houseTile = (13, 9)

        def __init__(self, color, name, scatterCorner):
            self.color = color
            self.name = name
            self.scatterCorner = scatterCorner
            self.radius = tileSize // 2 - 1
            self.reset()

        def reset(self, outside=False):
            if outside and self.name == "Blinky":
                # Door tiles on row 7 are open at x=12 and x=15
                tx, ty = 12, 7
            else:
                tx, ty = self.spawnTiles[self.name]
            self.pos = getTileCenter(tx, ty)
            self.direction = Vector2(-1, 0)
            self.mode = "scatter"
            self.frightenedTimer = 0.0
            self.speed = ghostSpeedBase
            self.eaten = False
            self.respawnTimer = 0.0
            self.decisionTile = None  # only pick a new heading once per tile

        def frighten(self, duration):
            if self.eaten:
                return
            if self.mode != "frightened":
                self.direction = Vector2(-self.direction.x, -self.direction.y)
                self.decisionTile = None
            self.mode = "frightened"
            self.frightenedTimer = duration

        def getTarget(self, pacman, blinkyPos):
            px, py = pacman.getTile()

            if self.mode == "frightened":
                return Vector2(
                    random.randint(0, mazeCols - 1) * tileSize + tileSize // 2,
                    random.randint(0, mazeRows - 1) * tileSize + tileSize // 2,
                )

            if self.mode == "scatter":
                return getTileCenter(*self.scatterCorner)

            # Chase personalities
            if self.name == "Blinky":
                return getTileCenter(px, py)

            if self.name == "Pinky":
                aheadX = px + int(pacman.direction.x * 4)
                aheadY = py + int(pacman.direction.y * 4)
                return getTileCenter(aheadX, aheadY)

            if self.name == "Inky":
                if blinkyPos is not None:
                    pacCenter = getTileCenter(px, py)
                    ahead = pacCenter + pacman.direction * (2 * tileSize)
                    vec = ahead - blinkyPos
                    return ahead + vec
                return getTileCenter(px, py)

            # Clyde: chase when far, scatter when close
            dist = (self.pos - getTileCenter(px, py)).length()
            if dist > 8 * tileSize:
                return getTileCenter(px, py)
            return getTileCenter(*self.scatterCorner)

        def validDirections(self, tx, ty, allowReverse=False):
            dirs = [Vector2(1, 0), Vector2(-1, 0), Vector2(0, 1), Vector2(0, -1)]
            valid = []
            reverse = Vector2(-self.direction.x, -self.direction.y)
            for d in dirs:
                if not allowReverse and self.direction.length_squared() > 0:
                    if d.x == reverse.x and d.y == reverse.y:
                        continue
                nextTx = tx + int(d.x)
                nextTy = ty + int(d.y)
                if not isWall(nextTx, nextTy):
                    valid.append(d)
            return valid

        def chooseDirection(self, target):
            tx, ty = tileFromPos(self.pos)
            valid = self.validDirections(tx, ty, allowReverse=False)

            # Dead end or corridor end: reverse is allowed
            if not valid:
                valid = self.validDirections(tx, ty, allowReverse=True)

            if not valid:
                return

            if self.mode == "frightened":
                self.direction = random.choice(valid)
                return

            bestDir = valid[0]
            bestDist = float("inf")
            for d in valid:
                nextCenter = getTileCenter(tx + int(d.x), ty + int(d.y))
                # Handle tunnel wrap distance roughly
                dist = (nextCenter - target).length_squared()
                if dist < bestDist:
                    bestDist = dist
                    bestDir = d
            self.direction = bestDir

        def alignToLane(self):
            if self.direction.x != 0:
                ty = int(self.pos.y // tileSize)
                self.pos.y = ty * tileSize + tileSize // 2
            elif self.direction.y != 0:
                if 0 <= self.pos.x < mazeCols * tileSize:
                    tx = int(self.pos.x // tileSize)
                    self.pos.x = tx * tileSize + tileSize // 2

        def update(self, dt, pacman, blinkyPos=None):
            if self.eaten:
                self.respawnTimer -= dt
                if self.respawnTimer <= 0:
                    self.eaten = False
                    self.mode = "chase"
                    self.pos = getTileCenter(*self.houseTile)
                    self.direction = Vector2(-1, 0)
                return

            if self.mode == "frightened":
                self.speed = ghostSpeedBase * 0.55
                self.frightenedTimer -= dt
                if self.frightenedTimer <= 0:
                    self.mode = "chase"
                    self.speed = ghostSpeedBase
            else:
                self.speed = ghostSpeedBase

            tx, ty = tileFromPos(self.pos)
            center = getTileCenter(tx, ty)
            distToCenter = (self.pos - center).length()
            target = self.getTarget(pacman, blinkyPos)

            # Decide once per tile, only when close enough to the center to turn cleanly.
            # Using decisionTile avoids snapping back to center every frame (which freezes ghosts).
            if distToCenter <= self.speed and self.decisionTile != (tx, ty):
                self.pos = Vector2(center)
                self.decisionTile = (tx, ty)
                self.chooseDirection(target)

            if self.direction.length_squared() == 0:
                self.pos = Vector2(center)
                self.decisionTile = (tx, ty)
                self.chooseDirection(target)
                if self.direction.length_squared() == 0:
                    return

            newPos = self.pos + self.direction * self.speed
            probeX = newPos.x + self.direction.x * (self.radius + 1)
            probeY = newPos.y + self.direction.y * (self.radius + 1)
            probeTx = int(math.floor(probeX / tileSize))
            probeTy = int(math.floor(probeY / tileSize))

            if not isWall(probeTx, probeTy):
                self.pos = applyTunnelWrap(newPos)
                self.alignToLane()
            else:
                # Hit a wall: snap to center and force a new decision (allow reverse)
                self.pos = Vector2(center)
                self.decisionTile = None
                self.chooseDirection(target)
                if self.direction.length_squared() > 0:
                    retry = self.pos + self.direction * self.speed
                    rTx = int(math.floor(
                        (retry.x + self.direction.x * (self.radius + 1)) / tileSize
                    ))
                    rTy = int(math.floor(
                        (retry.y + self.direction.y * (self.radius + 1)) / tileSize
                    ))
                    if not isWall(rTx, rTy):
                        self.pos = applyTunnelWrap(retry)
                        self.decisionTile = (tx, ty)
                        self.alignToLane()

        def draw(self, screen):
            if self.eaten:
                # Eyes only while returning home
                px, py = int(round(self.pos.x)), int(round(self.pos.y))
                pygame.draw.circle(screen, WHITE, (px - 4, py - 2), 3)
                pygame.draw.circle(screen, WHITE, (px + 4, py - 2), 3)
                pygame.draw.circle(screen, BLACK, (px - 4, py - 2), 1)
                pygame.draw.circle(screen, BLACK, (px + 4, py - 2), 1)
                return

            px, py = int(round(self.pos.x)), int(round(self.pos.y))

            if self.mode == "frightened":
                # Flash near end of frightened time
                if self.frightenedTimer < 2.0 and int(self.frightenedTimer * 6) % 2 == 0:
                    color = frightenedWhite
                else:
                    color = frightenedBlue
            else:
                color = self.color

            # Body
            pygame.draw.circle(screen, color, (px, py), self.radius)
            # Skirt
            skirtTop = py
            pygame.draw.rect(
                screen, color,
                pygame.Rect(px - self.radius, skirtTop, self.radius * 2, self.radius),
            )
            # Wavy bottom
            for i in range(3):
                cx = px - self.radius + 3 + i * 5
                pygame.draw.circle(screen, color, (cx, py + self.radius - 1), 3)

            # Eyes looking toward movement
            lookX = int(self.direction.x * 2)
            lookY = int(self.direction.y * 2)
            for ex in (-4, 4):
                pygame.draw.circle(screen, WHITE, (px + ex, py - 3), 3)
                pygame.draw.circle(screen, BLACK, (px + ex + lookX, py - 3 + lookY), 1)

        def eat(self):
            self.eaten = True
            self.mode = "eaten"
            self.respawnTimer = 1.5
            self.pos = getTileCenter(*self.houseTile)


    # ---------------------------------------------------------------------------
    # Game
    # ---------------------------------------------------------------------------

    class _CabinetPm:
        """Embedded session: renders into About via offscreen surface (no extra window)."""

        def __init__(self, host, markKey="pm"):
            self.host = host
            self._markKey = markKey
            self.running = True
            try:
                if not pygame.get_init():
                    pygame.init()
            except Exception:
                pygame.init()
            try:
                pygame.font.init()
            except Exception:
                pass
            try:
                if pygame.mixer.get_init() is None:
                    pygame.mixer.init(frequency=sampleRate, size=-16, channels=1, buffer=512)
            except Exception:
                pass

            # Offscreen only — never open a second OS window
            self.screen = pygame.Surface((windowWidth, windowHeight))
            fontPath = None
            try:
                fontPath = Logic.resourcePath("ui/fonts/PressStart2P-Regular.ttf")
            except Exception:
                fontPath = None
            if fontPath and os.path.isfile(fontPath):
                try:
                    self.font = pygame.font.Font(fontPath, 14)
                    self.bigFont = pygame.font.Font(fontPath, 22)
                except Exception:
                    self.font = pygame.font.Font(None, 32)
                    self.bigFont = pygame.font.Font(None, 56)
            else:
                self.font = pygame.font.Font(None, 32)
                self.bigFont = pygame.font.Font(None, 56)

            self.playSurface = pygame.Surface((mazePixelW, windowHeight))
            try:
                self.soundDir = Logic.resourcePath("ui/sounds")
            except Exception:
                self.soundDir = ""
            self.audio = SoundManager(self.soundDir)

            self.highScore = self.loadHighScore()
            self.resetGame()
            self.state = "MENU"
            self.anyGhostFrightened = False
            self._animTicks = 0

        def loadHighScore(self):
            return _readMark(self._markKey)

        def saveHighScore(self):
            _writeMark(self._markKey, self.highScore)

        def resetGame(self):
            global pacmanSpeed, ghostSpeedBase
            pacmanSpeed = 2.0 * speedScale
            ghostSpeedBase = 1.75 * speedScale

            self.score = 0
            self.level = 1
            self.lives = 3
            self.pacman = PacMan()
            self.ghosts = [
                Ghost(RED, "Blinky", (25, 1)),
                Ghost(PINK, "Pinky", (2, 1)),
                Ghost(CYAN, "Inky", (25, 24)),
                Ghost(ORANGE, "Clyde", (2, 24)),
            ]
            self.ghosts[0].reset(outside=True)
            self.pellets = list(initialPellets)
            self.powerPellets = list(initialPowerPellets)
            self.frightenedDuration = 7.0
            self.modeTimer = 0.0
            self.currentMode = "scatter"
            self.ghostEatenCombo = 0
            self.message = ""
            self.messageTimer = 0.0
            self.deathTimer = 0.0
            self.anyGhostFrightened = False
            self.audio.stopLoops()

        def startLevel(self):
            self.pacman = PacMan()
            for g in self.ghosts:
                g.reset(outside=(g.name == "Blinky"))
            self.pellets = list(initialPellets)
            self.powerPellets = list(initialPowerPellets)
            self.modeTimer = 0.0
            self.currentMode = "scatter"
            self.ghostEatenCombo = 0
            self.anyGhostFrightened = False
            self.audio.stopLoops()
            self.audio.startSiren(frightened=False)

        def respawnAfterDeath(self):
            self.pacman = PacMan()
            for g in self.ghosts:
                g.reset(outside=(g.name == "Blinky"))
            self.modeTimer = 0.0
            self.currentMode = "scatter"
            self.ghostEatenCombo = 0
            self.anyGhostFrightened = False
            self.audio.stopLoops()
            self.audio.startSiren(frightened=False)

        def updateSiren(self):
            frightened = any(g.mode == "frightened" and not g.eaten for g in self.ghosts)
            if frightened != self.anyGhostFrightened:
                self.anyGhostFrightened = frightened
                self.audio.startSiren(frightened=frightened)

        def update(self, dt, keys):
            if self.state != "PLAYING":
                return

            self.audio.updateLoops()

            if self.deathTimer > 0:
                self.deathTimer -= dt
                if self.deathTimer <= 0:
                    if self.lives <= 0:
                        self.state = "GAME_OVER"
                        if self.score > self.highScore:
                            self.highScore = self.score
                        self.saveHighScore()
                    else:
                        self.respawnAfterDeath()
                return

            self.pacman.update(dt, keys)

            self.modeTimer += dt
            if self.modeTimer > 25.0:
                self.currentMode = "chase" if self.currentMode == "scatter" else "scatter"
                self.modeTimer = 0.0
                for g in self.ghosts:
                    if g.mode not in ("frightened", "eaten") and not g.eaten:
                        g.mode = self.currentMode
                        g.direction = Vector2(-g.direction.x, -g.direction.y)
                        g.decisionTile = None

            blinky = next((g for g in self.ghosts if g.name == "Blinky"), None)
            for ghost in self.ghosts:
                ghost.update(dt, self.pacman, blinky.pos if blinky else None)

            self.updateSiren()

            pTile = self.pacman.getTile()
            if pTile in self.pellets:
                self.pellets.remove(pTile)
                self.score += pelletPoints
                self.audio.playWakka()

            if pTile in self.powerPellets:
                self.powerPellets.remove(pTile)
                self.score += powerPelletPoints
                self.ghostEatenCombo = 0
                self.audio.play("powerPellet")
                for g in self.ghosts:
                    g.frighten(self.frightenedDuration)

            for ghost in self.ghosts:
                if ghost.eaten:
                    continue
                dist = (ghost.pos - self.pacman.pos).length()
                if dist < tileSize * 0.7:
                    if ghost.mode == "frightened":
                        points = ghostPoints[min(self.ghostEatenCombo, 3)]
                        self.score += points
                        self.ghostEatenCombo += 1
                        ghost.eat()
                        self.audio.play("eatGhost")
                    else:
                        self.lives -= 1
                        self.audio.stopLoops()
                        self.audio.play("death")
                        self.deathTimer = 1.5
                        break

            if len(self.pellets) == 0 and len(self.powerPellets) == 0:
                global pacmanSpeed, ghostSpeedBase
                self.level += 1
                pacmanSpeed = min(pacmanSpeed + 0.1 * speedScale, 3.5 * speedScale)
                ghostSpeedBase = min(ghostSpeedBase + 0.08 * speedScale, 2.8 * speedScale)
                self.frightenedDuration = max(3.0, self.frightenedDuration - 0.8)
                self.audio.play("extraLife")
                self.startLevel()
                self.message = f"LEVEL {self.level}"
                self.messageTimer = 2.0

            if self.messageTimer > 0:
                self.messageTimer -= dt

            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHighScore()

        def drawMaze(self, surface):
            inset = max(2, tileSize // 4)
            for y in range(mazeRows):
                for x in range(mazeCols):
                    if maze[y][x] == 1:
                        rect = pygame.Rect(x * tileSize, y * tileSize, tileSize, tileSize)
                        pygame.draw.rect(surface, BLUE, rect)
                        pygame.draw.rect(surface, (0, 0, 150), rect.inflate(-inset, -inset))

        def draw(self):
            self.screen.fill(BLACK)
            surf = self.playSurface
            surf.fill(BLACK)
            self.drawMaze(surf)

            pelletR = max(2, tileSize // 8)
            for px, py in self.pellets:
                cx = px * tileSize + tileSize // 2
                cy = py * tileSize + tileSize // 2
                pygame.draw.circle(surf, WHITE, (cx, cy), pelletR)

            pulse = max(5, tileSize // 3) + int(math.sin(self._animTicks / 12.0) * 2)
            for px, py in self.powerPellets:
                cx = px * tileSize + tileSize // 2
                cy = py * tileSize + tileSize // 2
                pygame.draw.circle(surf, WHITE, (cx, cy), pulse)

            if self.deathTimer <= 0 or self.state != "PLAYING":
                self.pacman.draw(surf)
            for ghost in self.ghosts:
                ghost.draw(surf)

            self.screen.blit(surf, (offsetX, offsetY))

            hudY = mazePixelH + max(2, (hudHeight - 24) // 2)
            scoreText = self.font.render(f"SCORE: {self.score:06d}", True, WHITE)
            self.screen.blit(scoreText, (16, hudY))

            lifeR = max(6, tileSize // 3)
            lifeX = 16 + scoreText.get_width() + 14
            lifeCy = hudY + scoreText.get_height() // 2
            for i in range(self.lives):
                lx = lifeX + i * (lifeR * 2 + 6)
                pygame.draw.circle(self.screen, YELLOW, (lx + lifeR, lifeCy), lifeR)
                pygame.draw.circle(
                    self.screen, BLACK, (lx + lifeR + 2, lifeCy), max(2, lifeR // 3)
                )

            hsText = self.font.render(f"HIGH: {self.highScore:06d}", True, CYAN)
            self.screen.blit(hsText, (windowWidth // 2 - hsText.get_width() // 2, hudY))

            levelText = self.font.render(f"LEVEL {self.level}", True, CYAN)
            self.screen.blit(levelText, (windowWidth - levelText.get_width() - 16, hudY))

            if self.state == "MENU":
                title = self.bigFont.render("PAC-MAN", True, YELLOW)
                self.screen.blit(title, (windowWidth // 2 - title.get_width() // 2, 150))
                start = self.font.render("PRESS SPACE OR CLICK TO START", True, WHITE)
                self.screen.blit(start, (windowWidth // 2 - start.get_width() // 2, 250))
                hs = self.font.render(f"HIGH SCORE: {self.highScore}", True, CYAN)
                self.screen.blit(hs, (windowWidth // 2 - hs.get_width() // 2, 320))

            elif self.state == "PAUSED":
                pause = self.bigFont.render("PAUSED", True, CYAN)
                self.screen.blit(
                    pause,
                    (windowWidth // 2 - pause.get_width() // 2, windowHeight // 2 - 50),
                )

            elif self.state == "GAME_OVER":
                go = self.bigFont.render("GAME OVER", True, RED)
                self.screen.blit(go, (windowWidth // 2 - go.get_width() // 2, 160))
                sc = self.font.render(f"FINAL SCORE: {self.score}", True, WHITE)
                self.screen.blit(sc, (windowWidth // 2 - sc.get_width() // 2, 240))
                if self.score >= self.highScore and self.highScore > 0:
                    nhs = self.font.render("NEW HIGH SCORE!", True, YELLOW)
                    self.screen.blit(nhs, (windowWidth // 2 - nhs.get_width() // 2, 280))
                again = self.font.render("PRESS R or SPACE TO RESTART", True, WHITE)
                self.screen.blit(again, (windowWidth // 2 - again.get_width() // 2, 360))

            if self.messageTimer > 0 and self.message:
                msg = self.font.render(self.message, True, YELLOW)
                self.screen.blit(msg, (windowWidth // 2 - msg.get_width() // 2, 80))

        def beginPlay(self):
            self.resetGame()
            self.state = "PLAYING"
            self.audio.play("start")
            self.audio.startSiren(frightened=False)

        def handlePulses(self, pulses):
            for p in pulses:
                if p == "escape":
                    if self.state == "PLAYING":
                        self.audio.stopLoops()
                        self.state = "MENU"
                    else:
                        # Leave embedded session → catalog
                        self.running = False
                elif p == "p":
                    if self.state == "PLAYING":
                        self.audio.stopLoops()
                        self.state = "PAUSED"
                    elif self.state == "PAUSED":
                        self.state = "PLAYING"
                        self.audio.startSiren(frightened=self.anyGhostFrightened)
                elif p in ("space", "click"):
                    if self.state in ("MENU", "GAME_OVER"):
                        self.beginPlay()
                elif p == "r":
                    if self.state == "GAME_OVER":
                        self.beginPlay()

        def toImage(self):
            # Ensure contiguous RGB bytes for QImage
            rgb = self.screen
            if rgb.get_bytesize() != 3:
                rgb = self.screen.convert(24)
            raw = pygame.image.tobytes(rgb, "RGB")
            qimg = QImage(raw, windowWidth, windowHeight, windowWidth * 3, QImage.Format.Format_RGB888)
            return qimg.copy()

        def tick(self, dt, keys, pulses):
            self._animTicks += 1
            self.handlePulses(pulses or [])
            if not self.running:
                return None
            self.update(dt, keys or {})
            self.draw()
            return self.toImage()

        def stop(self):
            self.running = False
            try:
                self.audio.stopLoops()
            except Exception:
                pass

    def _factoryPm(host, markKey="pm"):
        return _CabinetPm(host, markKey)

    _addTitle(
        "PAC-MAN",
        "PAC-MAN  1980  RECREATION",
        _factoryPm,
        "pm",
    )

else:
    def _factoryPm(host, markKey="pm"):
        return None

