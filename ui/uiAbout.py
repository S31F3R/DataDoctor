# uiAbout.py

import json
import math
import os
import random
import struct
import time

from PyQt6.QtWidgets import (
    QDialog, QLabel, QTextBrowser, QPushButton, QMessageBox,
    QListWidget, QListWidgetItem, QApplication, QAbstractItemView,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QUrl, QSize, QObject, QEvent, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QFont, QIcon, QImage, QColor, QPainter
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


# Populated by _addTitle further down. title / factory(host, key) / key
_CATALOG = []


def _addTitle(title, factory, markKey):
    _CATALOG.append({"title": title, "factory": factory, "key": markKey})


def _starfieldPixmap(width=900, height=479, seed=31415):
    """Plain starfield for SELECT mode — no app logo / wordmark."""
    pm = QPixmap(width, height)
    pm.fill(QColor(0, 0, 0))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    rng = random.Random(seed)
    for _ in range(180):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        bright = rng.randint(140, 255)
        size = 1 if rng.random() < 0.85 else 2
        painter.fillRect(x, y, size, size, QColor(bright, bright, min(255, bright + 20)))
    # A few cyan/magenta glints for coin-op feel
    for _ in range(24):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        if rng.random() < 0.5:
            painter.fillRect(x, y, 1, 1, QColor(80, 220, 255))
        else:
            painter.fillRect(x, y, 1, 1, QColor(255, 80, 200))
    painter.end()
    return pm


class uiAbout(QDialog):
    """About dialog: Retro PNG bg with transparent info overlay and looping music."""

    _TITLE_DEFAULT = "About Data Doctor"
    _TITLE_CABINET = "S31F3R's Secret"

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
        self._cabBackdrop = None
        self._playLabel = None
        self._splashBg = None
        self._splashCredits = None
        self._splashCreditsFx = None
        self._splashAnim = None
        self._splashHoldTimer = None
        self._splashCreditTimer = None
        self._gameTimer = None
        self._session = None
        self._pendingEntry = None
        self._lastTick = 0.0
        self._playKeys = {
            "left": False, "right": False, "up": False, "down": False,
        }
        self._playPulses = []

        self.backgroundLabel = self.findChild(QLabel, 'backgroundLabel')
        self.textInfo = self.findChild(QTextBrowser, 'textInfo')
        self.buttonSecret = self.findChild(QPushButton, 'buttonSecret')
        self.setFixedSize(900, 479)
        self.setWindowTitle(self._TITLE_DEFAULT)

        pngPath = Logic.resourcePath('ui/DataDoctor.png')
        pixmap = QPixmap(pngPath)
        scaledPixmap = pixmap.scaled(900, 479, Qt.AspectRatioMode.KeepAspectRatio)
        self.backgroundLabel.setPixmap(scaledPixmap)
        self.backgroundLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        aboutFont = Utils.makeFontForRole('about')
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
        self.mediaPlayer = None
        self.audioOutput = None
        self.setupMusic()
        self._ensureCabinetWidgets()
        self._ensurePlayHost()

    def setupMusic(self):
        try:
            wavPath = Logic.resourcePath('ui/sounds/8-Bit-Perplexion.wav')
            self.audioOutput = QAudioOutput(self)
            self.audioOutput.setVolume(0.8)
            self.mediaPlayer = QMediaPlayer(self)
            self.mediaPlayer.setAudioOutput(self.audioOutput)
            self.mediaPlayer.setSource(QUrl.fromLocalFile(wavPath))
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
        self.mediaPlayer.setPosition(0)
        self.mediaPlayer.play()

    def stopMusic(self):
        if self.mediaPlayer:
            self.mediaPlayer.stop()

    def setupSecretButton(self):
        if not self.buttonSecret:
            return
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
        iconPath = Logic.resourcePath('ui/icons/pi.png')
        if os.path.exists(iconPath):
            self.buttonSecret.setIcon(QIcon(iconPath))
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
        for child in dlg.findChildren(QObject):
            try:
                child.installEventFilter(filterObj)
            except Exception:
                pass
        dlg.exec()

    def _ensureCabinetWidgets(self):
        fam = getattr(self, "_retroFam", "monospace")
        pt = getattr(self, "_retroPt", 9)

        # Covers About art (logo/wordmark) while SELECT / cabinet is active
        backdrop = QLabel(self)
        backdrop.setObjectName("cabBackdrop")
        backdrop.setGeometry(0, 0, 900, 479)
        backdrop.setPixmap(_starfieldPixmap(900, 479))
        backdrop.setScaledContents(False)
        backdrop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        backdrop.setStyleSheet("background-color: black;")
        backdrop.hide()
        self._cabBackdrop = backdrop

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

        # Shared splash: CREDITS 0 → CREDITS 1 (no per-title line)
        credits = QLabel(self)
        credits.setObjectName("splashCredits")
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setGeometry(40, 200, 820, 60)
        credits.setText("CREDITS 0")
        credits.setStyleSheet(
            f"color: #66ffff; background: transparent; "
            f"font-family: '{fam}'; font-size: {pt + 3}pt;"
        )
        fx = QGraphicsOpacityEffect(credits)
        fx.setOpacity(0.0)
        credits.setGraphicsEffect(fx)
        credits.hide()
        self._splashCredits = credits
        self._splashCreditsFx = fx

        self._gameTimer = QTimer(self)
        self._gameTimer.setInterval(16)
        self._gameTimer.timeout.connect(self._onGameTick)

        self._splashHoldTimer = QTimer(self)
        self._splashHoldTimer.setSingleShot(True)
        self._splashHoldTimer.timeout.connect(self._onSplashHoldDone)

        self._splashCreditTimer = QTimer(self)
        self._splashCreditTimer.setSingleShot(True)
        self._splashCreditTimer.timeout.connect(self._onSplashCreditInsert)

    def eventFilter(self, obj, event):
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
            Qt.Key.Key_Left: "left", Qt.Key.Key_A: "left", Qt.Key.Key_Z: "left",
            Qt.Key.Key_Right: "right", Qt.Key.Key_D: "right", Qt.Key.Key_Slash: "right",
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
        elif key == Qt.Key.Key_P:
            self._playPulses.append("p")
        elif key == Qt.Key.Key_R:
            self._playPulses.append("r")

    def _applyCabinetShell(self, active):
        """
        Cabinet presentation: clean starfield (no About logo) + secret window title.
        Reverts both when leaving cabinet mode entirely.
        """
        if active:
            self.setWindowTitle(self._TITLE_CABINET)
            if self.backgroundLabel is not None:
                self.backgroundLabel.hide()
            if self._cabBackdrop is not None:
                self._cabBackdrop.show()
                # Under list chrome / play / splash, above empty dialog
                self._cabBackdrop.lower()
                if self.backgroundLabel is not None:
                    self.backgroundLabel.lower()
        else:
            self.setWindowTitle(self._TITLE_DEFAULT)
            if self._cabBackdrop is not None:
                self._cabBackdrop.hide()
            if self.backgroundLabel is not None:
                self.backgroundLabel.show()
                self.backgroundLabel.lower()

    def _openCabinet(self):
        if self.textInfo is not None:
            self.textInfo.hide()
        if self.buttonSecret is not None:
            self.buttonSecret.hide()
        self._cabinetMode = True
        self._applyCabinetShell(True)
        self._refreshCatalog()
        self._showCatalogChrome(True)
        if self._cabList is not None:
            self._cabList.setFocus(Qt.FocusReason.OtherFocusReason)

    def _showCatalogChrome(self, visible):
        if visible and self._cabBackdrop is not None:
            self._cabBackdrop.show()
            self._cabBackdrop.raise_()
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
        self._applyCabinetShell(False)
        if self.textInfo is not None:
            self.textInfo.show()
        if self.buttonSecret is not None:
            self.buttonSecret.show()
            self.buttonSecret.raise_()

    def _resetToDefaultAbout(self):
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
        self._applyCabinetShell(False)
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
        """Shared intro: fade CREDITS 0, flip to CREDITS 1, hold, then play."""
        self._stopEmbeddedSession()
        self._pendingEntry = entry
        self._splashMode = True
        self._playMode = False
        if self._splashCredits is not None:
            self._splashCredits.setText("CREDITS 0")
        if self._splashCreditsFx is not None:
            self._splashCreditsFx.setOpacity(0.0)
        for w in (self._splashBg, self._splashCredits):
            if w is not None:
                w.show()
                w.raise_()
        if self._splashAnim is not None:
            try:
                self._splashAnim.stop()
            except Exception:
                pass
            self._splashAnim = None
        if self._splashHoldTimer is not None:
            self._splashHoldTimer.stop()
        if self._splashCreditTimer is not None:
            self._splashCreditTimer.stop()
        if self._splashCreditsFx is not None:
            anim = QPropertyAnimation(self._splashCreditsFx, b"opacity", self)
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
        if self._splashCreditTimer is not None:
            self._splashCreditTimer.start(700)
        else:
            self._onSplashCreditInsert()

    def _onSplashCreditInsert(self):
        if not self._splashMode:
            return
        if self._splashCredits is not None:
            self._splashCredits.setText("CREDITS 1")
        self._playCreditTone()
        if self._splashHoldTimer is not None:
            self._splashHoldTimer.start(1500)

    def _playCreditTone(self):
        if pygame is None:
            return
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            snd = _synthTone(1180, 80, 0.28)
            if snd is not None:
                snd.play()
        except Exception:
            pass

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
        if self._splashCreditTimer is not None:
            self._splashCreditTimer.stop()
        for w in (self._splashBg, self._splashCredits):
            if w is not None:
                w.hide()
        if self._splashCredits is not None:
            self._splashCredits.setText("CREDITS 0")
        if self._splashCreditsFx is not None:
            self._splashCreditsFx.setOpacity(0.0)

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
            self.startMusic()
        else:
            self.startMusic()

    def keyPressEvent(self, event):
        if self._splashMode:
            if event.key() == Qt.Key.Key_Escape:
                self._hideSplash()
                self._returnToCatalog()
                return
            if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._splashCreditsFx is not None and self._splashCreditsFx.opacity() >= 0.99:
                    if self._splashHoldTimer is not None:
                        self._splashHoldTimer.stop()
                    if self._splashCreditTimer is not None:
                        self._splashCreditTimer.stop()
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
        self._need = [
            Qt.Key.Key_Up, Qt.Key.Key_Up,
            Qt.Key.Key_Down, Qt.Key.Key_Down,
            Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_B, Qt.Key.Key_A,
        ]
        self._done = False

    def _mapKey(self, key, text):
        if key in (Qt.Key.Key_W,):
            return Qt.Key.Key_Up
        if key in (Qt.Key.Key_S,):
            return Qt.Key.Key_Down
        if key in (Qt.Key.Key_A,):
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
            self._buf = []
            return True
        mapped = self._mapKey(key, event.text())
        if mapped is None:
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
            if mapped == self._need[0]:
                self._buf = [mapped]
            else:
                self._buf = []
        return True


# ===========================================================================
# Cabinet titles — original content only (see secret.grok)
# ===========================================================================

if pygame is not None:
    W, H = 900, 479
    CYAN = (0, 255, 255)
    MAGENTA = (255, 0, 200)
    WHITE = (255, 255, 255)
    YELLOW = (255, 255, 100)
    BLACK = (0, 0, 0)

    def _synthTone(freq, ms, vol=0.35, decay=True):
        """Tiny original beep as pygame Sound (no external samples)."""
        try:
            rate = 22050
            n = max(1, int(rate * ms / 1000.0))
            buf = bytearray()
            for i in range(n):
                t = i / rate
                env = (1.0 - i / n) if decay else 1.0
                sample = int(vol * env * 32767 * math.sin(2 * math.pi * freq * t))
                sample = max(-32767, min(32767, sample))
                buf += struct.pack("<h", sample)
            return pygame.mixer.Sound(buffer=bytes(buf))
        except Exception:
            return None

    class _ToneBox:
        def __init__(self):
            self.ok = False
            self.sounds = {}
            try:
                if pygame.mixer.get_init() is None:
                    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
                self.sounds = {
                    "flip": _synthTone(220, 40, 0.3),
                    "bump": _synthTone(480, 70, 0.35),
                    "wall": _synthTone(160, 30, 0.2),
                    "score": _synthTone(660, 90, 0.3),
                    "drain": _synthTone(90, 280, 0.4),
                    "launch": _synthTone(320, 120, 0.35),
                }
                self.ok = True
            except Exception:
                self.ok = False

        def play(self, name):
            if not self.ok:
                return
            snd = self.sounds.get(name)
            if snd is None:
                return
            try:
                snd.play()
            except Exception:
                pass

    class _CabinetPb:
        """Original cyberpunk pinball — embedded in About (no extra window)."""

        def __init__(self, host, markKey="pb"):
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
                    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            except Exception:
                pass

            self.screen = pygame.Surface((W, H))
            fontPath = None
            try:
                fontPath = Logic.resourcePath("ui/fonts/PressStart2P-Regular.ttf")
            except Exception:
                fontPath = None
            if fontPath and os.path.isfile(fontPath):
                try:
                    self.font = pygame.font.Font(fontPath, 12)
                    self.bigFont = pygame.font.Font(fontPath, 18)
                except Exception:
                    self.font = pygame.font.Font(None, 28)
                    self.bigFont = pygame.font.Font(None, 44)
            else:
                self.font = pygame.font.Font(None, 28)
                self.bigFont = pygame.font.Font(None, 44)

            self.tableImg = None
            self.ballImg = None
            self.flipImg = None
            try:
                tpath = Logic.resourcePath("ui/fx/a0.png")
                bpath = Logic.resourcePath("ui/fx/a1.png")
                fpath = Logic.resourcePath("ui/fx/a2.png")
                if os.path.isfile(tpath):
                    self.tableImg = pygame.image.load(tpath).convert()
                    if self.tableImg.get_size() != (W, H):
                        self.tableImg = pygame.transform.smoothscale(self.tableImg, (W, H))
                if os.path.isfile(bpath):
                    self.ballImg = pygame.image.load(bpath).convert_alpha()
                if os.path.isfile(fpath):
                    self.flipImg = pygame.image.load(fpath).convert_alpha()
            except Exception:
                pass

            self.audio = _ToneBox()
            self.highScore = _readMark(self._markKey)
            self.state = "MENU"  # MENU, PLAYING, PAUSED, GAME_OVER
            self.score = 0
            self.ballsLeft = 3
            self.message = ""
            self.messageTimer = 0.0

            # Physics layout (tuned for 900x479 art)
            self.ballR = 9
            self.gravity = 520.0
            self.damping = 0.999
            self.maxSpeed = 780.0

            # Flippers: pivot positions near drain
            self.leftPivot = Vector2(310, 420)
            self.rightPivot = Vector2(590, 420)
            self.flipLen = 78
            self.flipRestL = math.radians(28)
            self.flipUpL = math.radians(-28)
            self.flipRestR = math.radians(152)
            self.flipUpR = math.radians(208)
            self.leftAng = self.flipRestL
            self.rightAng = self.flipRestR
            self.leftAngPrev = self.leftAng
            self.rightAngPrev = self.rightAng
            self.flipSpeed = 14.0

            # Bumpers (approx glowing circles on art)
            self.bumpers = [
                {"pos": Vector2(340, 170), "r": 28, "pts": 100, "flash": 0.0},
                {"pos": Vector2(450, 130), "r": 30, "pts": 150, "flash": 0.0},
                {"pos": Vector2(560, 170), "r": 28, "pts": 100, "flash": 0.0},
                {"pos": Vector2(450, 230), "r": 22, "pts": 200, "flash": 0.0},
            ]

            # Static segments: outer walls + sling-ish rails
            self.segments = [
                # left wall
                (Vector2(70, 30), Vector2(70, 400)),
                # right inner (gap at top lets ball leave plunger into field)
                (Vector2(800, 100), Vector2(800, 360)),
                # top
                (Vector2(70, 30), Vector2(800, 30)),
                # plunger lane walls
                (Vector2(820, 40), Vector2(820, 430)),
                (Vector2(875, 40), Vector2(875, 450)),
                (Vector2(820, 40), Vector2(875, 40)),
                # lane roof open toward field (angled entry)
                (Vector2(800, 100), Vector2(820, 70)),
                # bottom left / right floors flanking drain
                (Vector2(70, 400), Vector2(280, 450)),
                (Vector2(620, 450), Vector2(800, 400)),
                # upper curve suggestions
                (Vector2(100, 80), Vector2(200, 50)),
                (Vector2(700, 50), Vector2(780, 90)),
            ]

            self.drainRect = pygame.Rect(360, 445, 180, 40)
            self.plungerX = 847
            self.plungerYMin = 120
            self.plungerYMax = 420
            self.plungerPower = 0.0
            self.charging = False

            self.ball = Vector2(self.plungerX, 380)
            self.vel = Vector2(0, 0)
            self.onPlunger = True
            self.combo = 0

        def loadHigh(self):
            return _readMark(self._markKey)

        def saveHigh(self):
            _writeMark(self._markKey, self.highScore)

        def resetBall(self):
            self.ball = Vector2(self.plungerX, 380)
            self.vel = Vector2(0, 0)
            self.onPlunger = True
            self.plungerPower = 0.0
            self.charging = False
            self.combo = 0

        def beginPlay(self):
            self.score = 0
            self.ballsLeft = 3
            self.highScore = self.loadHigh()
            self.resetBall()
            self.state = "PLAYING"
            self.message = ""
            self.messageTimer = 0.0

        def flipperTip(self, pivot, ang):
            return pivot + Vector2(math.cos(ang), math.sin(ang)) * self.flipLen

        def _segBounce(self, a, b, elasticity=0.85, flipVel=None):
            """Bounce ball off segment a-b if intersecting."""
            ab = b - a
            abLen2 = ab.length_squared()
            if abLen2 < 1e-6:
                return False
            t = max(0.0, min(1.0, (self.ball - a).dot(ab) / abLen2))
            closest = a + ab * t
            delta = self.ball - closest
            dist = delta.length()
            if dist >= self.ballR or dist < 1e-6:
                return False
            n = delta / dist
            # push out
            self.ball = closest + n * (self.ballR + 0.5)
            vn = self.vel.dot(n)
            if vn < 0:
                self.vel -= n * (1.0 + elasticity) * vn
            if flipVel is not None:
                self.vel += flipVel * 0.55
            speed = self.vel.length()
            if speed > self.maxSpeed:
                self.vel.scale_to_length(self.maxSpeed)
            return True

        def _circleBounce(self, center, radius, pts):
            delta = self.ball - center
            dist = delta.length()
            minD = radius + self.ballR
            if dist >= minD or dist < 1e-6:
                return False
            n = delta / dist
            self.ball = center + n * (minD + 0.5)
            vn = self.vel.dot(n)
            if vn < 0:
                self.vel -= n * 1.9 * vn
            # kick outward
            self.vel += n * 120
            if self.vel.length() > self.maxSpeed:
                self.vel.scale_to_length(self.maxSpeed)
            self.score += pts
            self.combo += 1
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()
            self.audio.play("bump")
            return True

        def updateFlippers(self, dt, keys):
            self.leftAngPrev = self.leftAng
            self.rightAngPrev = self.rightAng
            leftWant = self.flipUpL if keys.get("left") else self.flipRestL
            rightWant = self.flipUpR if keys.get("right") else self.flipRestR
            self.leftAng += (leftWant - self.leftAng) * min(1.0, self.flipSpeed * dt)
            self.rightAng += (rightWant - self.rightAng) * min(1.0, self.flipSpeed * dt)

        def flipperAngularVel(self, ang, angPrev, dt):
            if dt <= 1e-6:
                return 0.0
            return (ang - angPrev) / dt

        def update(self, dt, keys):
            if self.state != "PLAYING":
                return
            if self.messageTimer > 0:
                self.messageTimer -= dt

            self.updateFlippers(dt, keys)

            # Plunger charge / launch
            if self.onPlunger:
                if keys.get("down") or keys.get("up"):
                    # up/down or we'll also use space via pulses separately
                    self.charging = True
                    self.plungerPower = min(1.0, self.plungerPower + dt * 1.2)
                    self.ball.y = self.plungerYMax - self.plungerPower * (self.plungerYMax - self.plungerYMin) * 0.35
                return

            # Gravity
            self.vel.y += self.gravity * dt
            self.vel *= self.damping
            self.ball += self.vel * dt

            # Walls
            hitWall = False
            for a, b in self.segments:
                if self._segBounce(a, b, 0.8):
                    hitWall = True
            if hitWall:
                self.audio.play("wall")

            # Flippers as segments with angular kick
            for pivot, ang, angPrev, rest in (
                (self.leftPivot, self.leftAng, self.leftAngPrev, self.flipRestL),
                (self.rightPivot, self.rightAng, self.rightAngPrev, self.flipRestR),
            ):
                tip = self.flipperTip(pivot, ang)
                w = self.flipperAngularVel(ang, angPrev, dt)
                # tangential direction at contact approx tip motion
                tang = Vector2(-math.sin(ang), math.cos(ang)) * (w * self.flipLen)
                if self._segBounce(pivot, tip, 0.55, flipVel=tang if abs(w) > 0.5 else Vector2(0, 0)):
                    if abs(w) > 1.0:
                        self.audio.play("flip")
                        self.score += 10

            # Bumpers
            for b in self.bumpers:
                if b["flash"] > 0:
                    b["flash"] -= dt
                if self._circleBounce(b["pos"], b["r"], b["pts"]):
                    b["flash"] = 0.12

            # Keep in bounds soft
            if self.ball.x < 50:
                self.ball.x = 50
                self.vel.x = abs(self.vel.x) * 0.7
            if self.ball.x > 890:
                self.ball.x = 890
                self.vel.x = -abs(self.vel.x) * 0.7
            if self.ball.y < 20:
                self.ball.y = 20
                self.vel.y = abs(self.vel.y) * 0.7

            # Drain
            if self.ball.y > 470 or (
                self.drainRect.collidepoint(int(self.ball.x), int(self.ball.y)) and self.ball.y > 440
            ):
                self.audio.play("drain")
                self.ballsLeft -= 1
                if self.score > self.highScore:
                    self.highScore = self.score
                    self.saveHigh()
                if self.ballsLeft <= 0:
                    self.state = "GAME_OVER"
                    self.saveHigh()
                else:
                    self.resetBall()
                    self.message = f"BALL {4 - self.ballsLeft}"
                    self.messageTimer = 1.5

        def launch(self):
            if not self.onPlunger:
                return
            power = max(0.25, self.plungerPower)
            self.onPlunger = False
            self.charging = False
            # Shoot up the lane, then into the upper field
            self.ball = Vector2(self.plungerX, 90)
            self.vel = Vector2(-180 - 220 * power, -280 - 360 * power)
            self.plungerPower = 0.0
            self.audio.play("launch")

        def handlePulses(self, pulses, keys):
            for p in pulses:
                if p == "escape":
                    if self.state == "PLAYING":
                        self.state = "MENU"
                    else:
                        self.running = False
                elif p == "p":
                    if self.state == "PLAYING":
                        self.state = "PAUSED"
                    elif self.state == "PAUSED":
                        self.state = "PLAYING"
                elif p in ("space", "click"):
                    if self.state == "MENU":
                        self.beginPlay()
                    elif self.state == "GAME_OVER":
                        self.beginPlay()
                    elif self.state == "PLAYING" and self.onPlunger:
                        self.launch()
                elif p == "r":
                    if self.state in ("GAME_OVER", "MENU"):
                        self.beginPlay()

            # Hold space while on plunger: charge (pulse is one-shot — use keys.down)
            # Space mapped only as pulse; charge with down/s
            if self.state == "PLAYING" and self.onPlunger and keys.get("down"):
                self.charging = True

        def drawFlipper(self, pivot, ang, mirror=False):
            # Procedural neon flipper for reliable rotation; optional sprite underlay
            tip = self.flipperTip(pivot, ang)
            mid = (pivot + tip) * 0.5
            # fat line
            pygame.draw.line(self.screen, (0, 200, 255), pivot, tip, 14)
            pygame.draw.line(self.screen, (180, 255, 255), pivot, tip, 6)
            pygame.draw.circle(self.screen, CYAN, (int(pivot.x), int(pivot.y)), 8)
            pygame.draw.circle(self.screen, WHITE, (int(tip.x), int(tip.y)), 5)
            if self.flipImg is not None:
                try:
                    deg = -math.degrees(ang)
                    img = self.flipImg
                    if mirror:
                        img = pygame.transform.flip(img, True, False)
                        deg = -math.degrees(math.pi - ang)
                    rot = pygame.transform.rotozoom(img, deg, 0.55)
                    rect = rot.get_rect(center=(int(mid.x), int(mid.y)))
                    self.screen.blit(rot, rect)
                except Exception:
                    pass

        def draw(self):
            if self.tableImg is not None:
                self.screen.blit(self.tableImg, (0, 0))
            else:
                self.screen.fill((10, 0, 20))
                pygame.draw.rect(self.screen, (40, 0, 60), (60, 20, 780, 440), 2)

            # Dim overlay for HUD readability on neon art
            hud = pygame.Surface((W, 36), pygame.SRCALPHA)
            hud.fill((0, 0, 0, 140))
            self.screen.blit(hud, (0, 0))

            # Bumper flashes
            for b in self.bumpers:
                if b["flash"] > 0:
                    pygame.draw.circle(
                        self.screen, (255, 100, 255),
                        (int(b["pos"].x), int(b["pos"].y)), int(b["r"] + 6), 2
                    )

            # Flippers
            self.drawFlipper(self.leftPivot, self.leftAng, mirror=False)
            self.drawFlipper(self.rightPivot, self.rightAng, mirror=True)

            # Plunger spring indicator
            if self.onPlunger or self.state == "MENU":
                py = int(self.plungerYMax - self.plungerPower * 80)
                pygame.draw.line(self.screen, MAGENTA, (self.plungerX, py), (self.plungerX, 450), 4)
                pygame.draw.circle(self.screen, CYAN, (self.plungerX, py), 6)

            # Ball
            bx, by = int(self.ball.x), int(self.ball.y)
            if self.ballImg is not None:
                r = self.ballImg.get_rect(center=(bx, by))
                self.screen.blit(self.ballImg, r)
            else:
                pygame.draw.circle(self.screen, WHITE, (bx, by), self.ballR)
                pygame.draw.circle(self.screen, CYAN, (bx, by), self.ballR, 2)

            # HUD
            sc = self.font.render(f"SCORE {self.score:06d}", True, CYAN)
            self.screen.blit(sc, (16, 10))
            hs = self.font.render(f"HI {self.highScore:06d}", True, MAGENTA)
            self.screen.blit(hs, (W // 2 - hs.get_width() // 2, 10))
            bl = self.font.render(f"BALLS {self.ballsLeft}", True, YELLOW)
            self.screen.blit(bl, (W - bl.get_width() - 16, 10))

            if self.state == "MENU":
                title = self.bigFont.render("PINBALL", True, CYAN)
                self.screen.blit(title, (W // 2 - title.get_width() // 2, 160))
                sub = self.font.render("CYBER TABLE", True, MAGENTA)
                self.screen.blit(sub, (W // 2 - sub.get_width() // 2, 200))
                go = self.font.render("SPACE TO START", True, WHITE)
                self.screen.blit(go, (W // 2 - go.get_width() // 2, 260))
                ctrl = self.font.render("Z/LEFT  /  RIGHT  |  DOWN CHARGE  SPACE LAUNCH", True, (180, 180, 200))
                self.screen.blit(ctrl, (W // 2 - ctrl.get_width() // 2, 320))

            elif self.state == "PAUSED":
                t = self.bigFont.render("PAUSED", True, YELLOW)
                self.screen.blit(t, (W // 2 - t.get_width() // 2, H // 2 - 20))

            elif self.state == "GAME_OVER":
                t = self.bigFont.render("GAME OVER", True, MAGENTA)
                self.screen.blit(t, (W // 2 - t.get_width() // 2, 170))
                s = self.font.render(f"SCORE {self.score}", True, WHITE)
                self.screen.blit(s, (W // 2 - s.get_width() // 2, 230))
                a = self.font.render("SPACE / R  RETRY", True, CYAN)
                self.screen.blit(a, (W // 2 - a.get_width() // 2, 290))

            if self.messageTimer > 0 and self.message:
                m = self.font.render(self.message, True, YELLOW)
                self.screen.blit(m, (W // 2 - m.get_width() // 2, 50))

            # Always show light controls while playing
            if self.state == "PLAYING" and self.onPlunger:
                tip = self.font.render("HOLD DOWN TO CHARGE  ·  SPACE TO LAUNCH", True, WHITE)
                self.screen.blit(tip, (W // 2 - tip.get_width() // 2, H - 28))

        def toImage(self):
            rgb = self.screen
            if rgb.get_bytesize() != 3:
                rgb = self.screen.convert(24)
            raw = pygame.image.tobytes(rgb, "RGB")
            qimg = QImage(raw, W, H, W * 3, QImage.Format.Format_RGB888)
            return qimg.copy()

        def tick(self, dt, keys, pulses):
            keys = keys or {}
            self.handlePulses(pulses or [], keys)
            if not self.running:
                return None
            # continuous charge
            if self.state == "PLAYING" and self.onPlunger and keys.get("down"):
                self.plungerPower = min(1.0, self.plungerPower + dt * 1.15)
                self.ball.y = self.plungerYMax - self.plungerPower * 70
            self.update(dt, keys)
            self.draw()
            return self.toImage()

        def stop(self):
            self.running = False
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()

    def _factoryPb(host, markKey="pb"):
        return _CabinetPb(host, markKey)

    _addTitle("PINBALL", _factoryPb, "pb")

else:
    def _factoryPb(host, markKey="pb"):
        return None
