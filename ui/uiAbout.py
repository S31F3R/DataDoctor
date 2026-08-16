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

    class _Sfx:
        def __init__(self):
            self.ok = False
            self.sounds = {}
            try:
                if pygame.mixer.get_init() is None:
                    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
                names = {
                    "shoot": "c0.wav",
                    "boomE": "c1.wav",
                    "boomP": "c2.wav",
                    "hit": "c3.wav",
                    "ufo": "c4.wav",
                    "life": "c5.wav",
                    "clear": "c6.wav",
                    "over": "c7.wav",
                }
                for key, fn in names.items():
                    path = Logic.resourcePath(f"ui/fx/{fn}")
                    if path and os.path.isfile(path):
                        self.sounds[key] = pygame.mixer.Sound(path)
                self.ok = True
            except Exception:
                self.ok = False
            self._ufoCh = None

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

        def startUfo(self):
            if not self.ok:
                return
            snd = self.sounds.get("ufo")
            if snd is None:
                return
            try:
                self.stopUfo()
                self._ufoCh = snd.play()
            except Exception:
                self._ufoCh = None

        def stopUfo(self):
            ch = self._ufoCh
            self._ufoCh = None
            if ch is None:
                return
            try:
                ch.stop()
            except Exception:
                pass

    def _fxPath(name):
        try:
            return Logic.resourcePath(f"ui/fx/{name}")
        except Exception:
            return ""

    def _ensureDisplay():
        """Offscreen format only — never open a visible pygame window."""
        try:
            hidden = getattr(pygame, "HIDDEN", None)
            if hidden is None:
                return
            if not pygame.display.get_init():
                pygame.display.init()
            if pygame.display.get_surface() is None:
                pygame.display.set_mode((1, 1), hidden)
        except Exception:
            pass

    def _loadSurf(name):
        path = _fxPath(name)
        if not path or not os.path.isfile(path):
            return None
        try:
            img = pygame.image.load(path)
        except Exception:
            return None
        try:
            return img.convert_alpha()
        except Exception:
            try:
                return img.convert()
            except Exception:
                return img

    def _fitSurf(img, maxW, maxH):
        if img is None:
            return None
        iw, ih = img.get_size()
        if iw < 1 or ih < 1:
            return img
        s = min(maxW / float(iw), maxH / float(ih))
        nw = max(1, int(round(iw * s)))
        nh = max(1, int(round(ih * s)))
        if (nw, nh) == (iw, ih):
            return img
        try:
            return pygame.transform.smoothscale(img, (nw, nh))
        except Exception:
            return pygame.transform.scale(img, (nw, nh))

    def _coverSurf(img, tw, th):
        if img is None:
            return None
        iw, ih = img.get_size()
        s = max(tw / float(iw), th / float(ih))
        nw = max(1, int(round(iw * s)))
        nh = max(1, int(round(ih * s)))
        try:
            scaled = pygame.transform.smoothscale(img, (nw, nh))
        except Exception:
            scaled = pygame.transform.scale(img, (nw, nh))
        x = (nw - tw) // 2
        y = (nh - th) // 2
        surf = pygame.Surface((tw, th)).convert()
        surf.blit(scaled, (-x, -y))
        return surf

    class _CabinetSh:
        """Original space-defense sessions (formation + dive variants)."""

        _EXP = {
            "player": ("b8.png", "b9.png"),
            "e2": ("b8.png", "b9.png"),
            "e1": ("b10.png", "b11.png"),
            "e3": ("b12.png", "b13.png"),
            "ufo": ("b14.png", "b15.png"),
        }

        def __init__(self, host, markKey="ab", mode="ab"):
            self.host = host
            self._markKey = markKey
            self.mode = mode  # "ab" formation-march; "ls" inbound/dive
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
            _ensureDisplay()

            self.screen = pygame.Surface((W, H))
            fontPath = None
            try:
                fontPath = Logic.resourcePath("ui/fonts/PressStart2P-Regular.ttf")
            except Exception:
                fontPath = None
            if fontPath and os.path.isfile(fontPath):
                try:
                    self.font = pygame.font.Font(fontPath, 10)
                    self.bigFont = pygame.font.Font(fontPath, 16)
                except Exception:
                    self.font = pygame.font.Font(None, 22)
                    self.bigFont = pygame.font.Font(None, 36)
            else:
                self.font = pygame.font.Font(None, 22)
                self.bigFont = pygame.font.Font(None, 36)

            self.bg = _coverSurf(_loadSurf("b0.png"), W, H)
            self.stars = _loadSurf("b23.png")
            if self.stars is not None and self.stars.get_size() != (W, H):
                try:
                    self.stars = pygame.transform.scale(self.stars, (W, H))
                except Exception:
                    pass
            self.playerImg = _fitSurf(_loadSurf("b1.png"), 52, 70)
            self.pBullet = _fitSurf(_loadSurf("b2.png"), 7, 18)
            self.eImg = {
                1: _fitSurf(_loadSurf("b3.png"), 34, 32),
                2: _fitSurf(_loadSurf("b4.png"), 36, 34),
                3: _fitSurf(_loadSurf("b5.png"), 30, 40),
            }
            self.eIdle = {
                1: _fitSurf(_loadSurf("b18.png"), 34, 32),
                2: _fitSurf(_loadSurf("b19.png"), 36, 34),
                3: _fitSurf(_loadSurf("b20.png"), 30, 40),
            }
            self.eBullet = _fitSurf(_loadSurf("b6.png"), 7, 18)
            self.barrierSrc = _fitSurf(_loadSurf("b7.png"), 108, 42)
            self.ufoImg = _fitSurf(_loadSurf("b16.png"), 52, 36)
            self.lifeImg = _fitSurf(_loadSurf("b17.png"), 16, 16)
            self.muzzle = [
                _fitSurf(_loadSurf("b21.png"), 18, 18),
                _fitSurf(_loadSurf("b22.png"), 20, 20),
            ]
            self.expFrames = {}
            for key, pair in self._EXP.items():
                frames = []
                for fn in pair:
                    frames.append(_fitSurf(_loadSurf(fn), 40, 40))
                self.expFrames[key] = frames

            self.audio = _Sfx()
            self.highScore = _readMark(self._markKey)
            self.state = "MENU"
            self.score = 0
            self.lives = 3
            self.wave = 1
            self.extraAwarded = False
            self.starOff = 0.0
            self.idleT = 0.0
            self.idleFrame = 0
            self.flashT = 0.0
            self.invuln = 0.0
            self.message = ""
            self.messageT = 0.0
            self.title = "ALIEN BLASTER" if mode == "ab" else "LAST STAND"

            self.playerX = W * 0.5
            self.playerY = 428.0
            self.playerDead = False
            self.dieWait = 0.0
            self.pShots = []
            self.eShots = []
            self.enemies = []
            self.barriers = []
            self.fx = []
            self.ufo = None
            self.ufoTimer = 18.0
            self.formDx = 1
            self.formStepT = 0.0
            self.formInterval = 0.55
            self.eShootT = 0.0
            self.diveT = 0.0
            self.inboundLeft = 0
            self.maxPShots = 1 if mode == "ab" else 2
            self.playerSpeed = 260.0

        def loadHigh(self):
            return _readMark(self._markKey)

        def saveHigh(self):
            _writeMark(self._markKey, self.highScore)

        def playS(self, name):
            self.audio.play(name)

        def _playerSize(self):
            if self.playerImg is not None:
                return self.playerImg.get_size()
            return (48, 64)

        def _etypeSize(self, kind):
            img = self.eImg.get(kind)
            if img is not None:
                return img.get_size()
            return (32, 32)

        def beginPlay(self):
            self.score = 0
            self.lives = 3
            self.wave = 1
            self.extraAwarded = False
            self.highScore = self.loadHigh()
            self.playerX = W * 0.5
            self.playerY = 428.0
            self.playerDead = False
            self.dieWait = 0.0
            self.invuln = 0.0
            self.pShots = []
            self.eShots = []
            self.fx = []
            self.ufo = None
            self.audio.stopUfo()
            self.ufoTimer = 16.0 + random.random() * 8.0
            self.state = "PLAYING"
            self.message = ""
            self.messageT = 0.0
            self._setupWave()

        def _setupWave(self):
            self.pShots = []
            self.eShots = []
            self.enemies = []
            self.formDx = 1
            self.formStepT = 0.0
            self.formInterval = max(0.12, 0.56 - (self.wave - 1) * 0.05)
            self.eShootT = 0.8
            self.diveT = 1.6
            cols, rows = 8, 4
            gapX, gapY = 78, 38
            originX = 86.0
            originY = 58.0
            kinds = [3, 2, 1, 1]
            delay = 0.0
            for r in range(rows):
                kind = kinds[r]
                for c in range(cols):
                    slotX = originX + c * gapX
                    slotY = originY + r * gapY
                    if self.mode == "ls":
                        side = -1 if (c + r) % 2 == 0 else 1
                        startX = -40 if side < 0 else W + 40
                        startY = 30 + r * 18 + random.random() * 20
                        st = "IN"
                        delay += 0.09
                    else:
                        startX, startY = slotX, slotY
                        st = "FORM"
                    self.enemies.append({
                        "kind": kind,
                        "x": startX,
                        "y": startY,
                        "slotX": slotX,
                        "slotY": slotY,
                        "st": st,
                        "t": -delay if self.mode == "ls" else 0.0,
                        "phase": random.random() * 6.28,
                        "shot": False,
                    })
            self.inboundLeft = sum(1 for e in self.enemies if e["st"] == "IN")
            self.barriers = []
            if self.mode == "ab" and self.barrierSrc is not None:
                bw, bh = self.barrierSrc.get_size()
                for i, bx in enumerate((118, 304, 490, 676)):
                    surf = self.barrierSrc.copy()
                    self.barriers.append({
                        "x": bx,
                        "y": 366,
                        "surf": surf,
                        "mask": pygame.mask.from_surface(surf),
                        "w": bw,
                        "h": bh,
                    })

        def _addScore(self, n):
            self.score += int(n)
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()
            if (not self.extraAwarded) and self.score >= 1500:
                self.extraAwarded = True
                self.lives += 1
                self.playS("life")
                self.message = "EXTRA LIFE"
                self.messageT = 1.4

        def _spawnFx(self, kind, x, y):
            frames = self.expFrames.get(kind) or self.expFrames.get("e1") or []
            self.fx.append({"x": x, "y": y, "frames": frames, "i": 0, "t": 0.0})

        def _playerRect(self):
            pw, ph = self._playerSize()
            return (self.playerX - pw * 0.5, self.playerY - ph * 0.5, pw, ph)

        def _enemyRect(self, e):
            ew, eh = self._etypeSize(e["kind"])
            return (e["x"] - ew * 0.5, e["y"] - eh * 0.5, ew, eh)

        def _overlap(self, a, b):
            return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]

        def _firePlayer(self):
            if self.playerDead or self.state != "PLAYING":
                return
            if len(self.pShots) >= self.maxPShots:
                return
            pw, ph = self._playerSize()
            self.pShots.append({
                "x": self.playerX,
                "y": self.playerY - ph * 0.5,
            })
            self.flashT = 0.08
            self.playS("shoot")

        def _killPlayer(self):
            if self.playerDead or self.invuln > 0:
                return
            self.playerDead = True
            self.dieWait = 1.35
            self._spawnFx("player", self.playerX, self.playerY)
            self.playS("boomP")
            self.audio.stopUfo()
            self.lives -= 1
            self.pShots = []
            if self.lives <= 0:
                self.saveHigh()

        def _nextLifeOrOver(self):
            if self.lives <= 0:
                self.state = "GAME_OVER"
                self.playS("over")
                self.saveHigh()
                return
            self.playerDead = False
            self.playerX = W * 0.5
            self.invuln = 1.6
            self.eShots = []
            if self.mode == "ls":
                for e in self.enemies:
                    if e["st"] == "DIVE":
                        e["st"] = "FORM"
                        e["x"] = e["slotX"]
                        e["y"] = e["slotY"]
                        e["shot"] = False

        def _clearWave(self):
            self.playS("clear")
            self.wave += 1
            self.message = f"WAVE {self.wave}"
            self.messageT = 1.5
            self.ufo = None
            self.audio.stopUfo()
            self._setupWave()

        def _spawnUfo(self):
            if self.ufo is not None:
                return
            goingRight = random.random() < 0.5
            self.ufo = {
                "x": -30.0 if goingRight else float(W + 30),
                "y": 30.0,
                "vx": 95.0 if goingRight else -95.0,
                "pts": random.choice((50, 100, 150, 200)),
            }
            self.audio.startUfo()

        def _punchBarrier(self, bar, wx, wy, radius=7):
            lx = int(wx - bar["x"])
            ly = int(wy - bar["y"])
            try:
                pygame.draw.circle(bar["surf"], (0, 0, 0, 0), (lx, ly), radius)
                bar["mask"] = pygame.mask.from_surface(bar["surf"])
            except Exception:
                return
            if bar["mask"].count() < 40:
                bar["dead"] = True

        def _hitBarriers(self, x, y, fromPlayer):
            for bar in self.barriers:
                if bar.get("dead"):
                    continue
                if x < bar["x"] or y < bar["y"] or x >= bar["x"] + bar["w"] or y >= bar["y"] + bar["h"]:
                    continue
                try:
                    if bar["mask"].get_at((int(x - bar["x"]), int(y - bar["y"]))):
                        self._punchBarrier(bar, x, y, 8 if fromPlayer else 7)
                        self.playS("hit")
                        return True
                except Exception:
                    continue
            return False

        def handlePulses(self, pulses, keys):
            for p in pulses:
                if p == "escape":
                    if self.state == "PLAYING":
                        self.state = "MENU"
                        self.audio.stopUfo()
                    elif self.state == "PAUSED":
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
                    elif self.state == "PLAYING":
                        self._firePlayer()
                elif p == "r":
                    if self.state in ("GAME_OVER", "MENU"):
                        self.beginPlay()

        def update(self, dt, keys):
            if self.state != "PLAYING":
                return
            if self.messageT > 0:
                self.messageT -= dt
            self.idleT += dt
            if self.idleT >= 0.38:
                self.idleT = 0.0
                self.idleFrame = 1 - self.idleFrame
            self.starOff = (self.starOff + dt * 18.0) % H
            if self.flashT > 0:
                self.flashT -= dt
            if self.invuln > 0:
                self.invuln -= dt

            if self.playerDead:
                self.dieWait -= dt
                self._updateFx(dt)
                if self.dieWait <= 0:
                    self._nextLifeOrOver()
                return

            pw, _ph = self._playerSize()
            move = 0.0
            if keys.get("left"):
                move -= 1.0
            if keys.get("right"):
                move += 1.0
            self.playerX += move * self.playerSpeed * dt
            half = pw * 0.5
            self.playerX = max(half + 8, min(W - half - 8, self.playerX))

            speedP = -340.0
            for s in self.pShots:
                s["y"] += speedP * dt
            self.pShots = [s for s in self.pShots if s["y"] > -12]

            speedE = 150.0 + self.wave * 8
            for s in self.eShots:
                s["y"] += speedE * dt
            self.eShots = [s for s in self.eShots if s["y"] < H + 12]

            if self.ufo is not None:
                self.ufo["x"] += self.ufo["vx"] * dt
                if self.ufo["x"] < -50 or self.ufo["x"] > W + 50:
                    self.ufo = None
                    self.audio.stopUfo()
            else:
                self.ufoTimer -= dt
                if self.ufoTimer <= 0:
                    self._spawnUfo()
                    self.ufoTimer = 18.0 + random.random() * 10.0

            if self.mode == "ab":
                self._updateFormation(dt)
            else:
                self._updateDive(dt)

            self._collide()
            self._updateFx(dt)

            if not self.playerDead and not any(True for _ in self.enemies):
                self._clearWave()

        def _aliveForm(self):
            return [e for e in self.enemies if e["st"] in ("FORM",)]

        def _updateFormation(self, dt):
            self.formStepT += dt
            living = [e for e in self.enemies]
            if not living:
                return
            n = max(1, len(living))
            interval = max(0.07, self.formInterval * (n / 32.0) + 0.04)
            if self.formStepT >= interval:
                self.formStepT = 0.0
                minX = min(e["x"] for e in living)
                maxX = max(e["x"] for e in living)
                drop = False
                step = 10.0
                if self.formDx > 0 and maxX + step > W - 28:
                    drop = True
                elif self.formDx < 0 and minX - step < 28:
                    drop = True
                if drop:
                    self.formDx *= -1
                    for e in living:
                        e["y"] += 14.0
                        e["slotY"] += 14.0
                else:
                    for e in living:
                        e["x"] += self.formDx * step
                        e["slotX"] += self.formDx * step

            self.eShootT -= dt
            if self.eShootT <= 0 and living:
                self.eShootT = max(0.35, 1.05 - self.wave * 0.07)
                cols = {}
                for e in living:
                    key = int(round(e["x"] / 20.0))
                    prev = cols.get(key)
                    if prev is None or e["y"] > prev["y"]:
                        cols[key] = e
                shooter = random.choice(list(cols.values()))
                self.eShots.append({"x": shooter["x"], "y": shooter["y"] + 14})

            floorY = self.playerY - 36
            for e in living:
                if e["y"] >= floorY:
                    self._killPlayer()
                    break

        def _updateDive(self, dt):
            stillIn = 0
            for e in self.enemies:
                if e["st"] == "IN":
                    e["t"] += dt
                    if e["t"] < 0:
                        stillIn += 1
                        continue
                    tx, ty = e["slotX"], e["slotY"]
                    dx, dy = tx - e["x"], ty - e["y"]
                    dist = math.hypot(dx, dy) or 1.0
                    spd = 220.0
                    step = spd * dt
                    if dist <= step + 2:
                        e["x"], e["y"] = tx, ty
                        e["st"] = "FORM"
                    else:
                        e["x"] += dx / dist * step
                        e["y"] += dy / dist * step + math.sin(e["t"] * 8 + e["phase"]) * 18 * dt
                    stillIn += 1
            self.inboundLeft = stillIn

            parked = [e for e in self.enemies if e["st"] == "FORM"]
            diving = [e for e in self.enemies if e["st"] == "DIVE"]
            if stillIn == 0:
                self.diveT -= dt
                want = 1 + (1 if self.wave >= 3 else 0)
                if self.diveT <= 0 and parked and len(diving) < want + 1:
                    self.diveT = max(0.7, 1.7 - self.wave * 0.08)
                    pick = random.choice(parked)
                    pick["st"] = "DIVE"
                    pick["t"] = 0.0
                    pick["shot"] = False
                    pick["phase"] = random.choice((-1.0, 1.0)) * (70 + random.random() * 50)

            for e in list(self.enemies):
                if e["st"] != "DIVE":
                    continue
                e["t"] += dt
                e["y"] += (95 + self.wave * 10) * dt
                e["x"] += math.sin(e["t"] * 3.2) * e["phase"] * dt * 0.08 + (self.playerX - e["x"]) * 0.55 * dt
                if (not e["shot"]) and e["y"] > 160:
                    e["shot"] = True
                    self.eShots.append({"x": e["x"], "y": e["y"] + 12})
                if e["y"] > H + 20:
                    # recycle to top of slot
                    e["y"] = -20
                    e["x"] = e["slotX"]
                    e["st"] = "FORM"
                    e["shot"] = False

            self.eShootT -= dt
            if self.eShootT <= 0 and parked and stillIn == 0:
                self.eShootT = max(0.45, 1.3 - self.wave * 0.08)
                shooter = random.choice(parked)
                self.eShots.append({"x": shooter["x"], "y": shooter["y"] + 14})

        def _collide(self):
            pbw, pbh = (6, 16)
            if self.pBullet is not None:
                pbw, pbh = self.pBullet.get_size()
            ebw, ebh = (6, 16)
            if self.eBullet is not None:
                ebw, ebh = self.eBullet.get_size()

            keepP = []
            for s in self.pShots:
                sr = (s["x"] - pbw * 0.5, s["y"] - pbh * 0.5, pbw, pbh)
                hit = False
                if self.ufo is not None:
                    uw, uh = (48, 32)
                    if self.ufoImg is not None:
                        uw, uh = self.ufoImg.get_size()
                    ur = (self.ufo["x"] - uw * 0.5, self.ufo["y"] - uh * 0.5, uw, uh)
                    if self._overlap(sr, ur):
                        self._spawnFx("ufo", self.ufo["x"], self.ufo["y"])
                        self._addScore(self.ufo["pts"])
                        self.playS("boomE")
                        self.ufo = None
                        self.audio.stopUfo()
                        hit = True
                if not hit:
                    for e in list(self.enemies):
                        if self._overlap(sr, self._enemyRect(e)):
                            kind = {1: "e1", 2: "e2", 3: "e3"}.get(e["kind"], "e1")
                            self._spawnFx(kind, e["x"], e["y"])
                            pts = {1: 10, 2: 20, 3: 30}.get(e["kind"], 10)
                            if e["st"] == "DIVE":
                                pts += 20
                            self._addScore(pts)
                            self.playS("boomE")
                            self.enemies.remove(e)
                            hit = True
                            break
                if not hit and self.mode == "ab":
                    if self._hitBarriers(s["x"], s["y"], True):
                        hit = True
                if not hit:
                    keepP.append(s)
            self.pShots = keepP

            if self.mode == "ab":
                self.barriers = [b for b in self.barriers if not b.get("dead")]

            keepE = []
            pr = self._playerRect()
            for s in self.eShots:
                sr = (s["x"] - ebw * 0.5, s["y"] - ebh * 0.5, ebw, ebh)
                hit = False
                if self.mode == "ab" and self._hitBarriers(s["x"], s["y"], False):
                    hit = True
                if (not hit) and (not self.playerDead) and self._overlap(sr, pr):
                    self._killPlayer()
                    hit = True
                if not hit:
                    keepE.append(s)
            self.eShots = keepE

            if not self.playerDead:
                for e in self.enemies:
                    if self._overlap(self._enemyRect(e), pr):
                        kind = {1: "e1", 2: "e2", 3: "e3"}.get(e["kind"], "e1")
                        self._spawnFx(kind, e["x"], e["y"])
                        self.playS("boomE")
                        try:
                            self.enemies.remove(e)
                        except ValueError:
                            pass
                        self._killPlayer()
                        break

        def _updateFx(self, dt):
            live = []
            for f in self.fx:
                f["t"] += dt
                if f["t"] >= 0.09:
                    f["t"] = 0.0
                    f["i"] += 1
                if f["i"] < len(f["frames"]):
                    live.append(f)
            self.fx = live

        def _blitC(self, img, x, y):
            if img is None:
                return
            r = img.get_rect(center=(int(x), int(y)))
            self.screen.blit(img, r)

        def _drawHud(self):
            score = self.font.render(f"{self.score:05d}", True, WHITE)
            hi = self.font.render(f"HI {self.highScore:05d}", True, YELLOW)
            wave = self.font.render(f"W{self.wave}", True, CYAN)
            self.screen.blit(score, (16, 8))
            self.screen.blit(hi, (W // 2 - hi.get_width() // 2, 8))
            self.screen.blit(wave, (W - 70, 8))
            if self.lifeImg is not None:
                for i in range(max(0, self.lives)):
                    self.screen.blit(self.lifeImg, (16 + i * 20, H - 22))
            if self.messageT > 0 and self.message:
                msg = self.bigFont.render(self.message, True, YELLOW)
                self.screen.blit(msg, (W // 2 - msg.get_width() // 2, 220))

        def draw(self):
            if self.bg is not None:
                self.screen.blit(self.bg, (0, 0))
            else:
                self.screen.fill((4, 2, 12))
            if self.stars is not None:
                y = int(self.starOff)
                self.screen.blit(self.stars, (0, y - H))
                self.screen.blit(self.stars, (0, y))

            if self.state == "MENU":
                title = self.bigFont.render(self.title, True, CYAN)
                hint = self.font.render("SPACE", True, WHITE)
                esc = self.font.render("ESC", True, (160, 160, 180))
                hi = self.font.render(f"HI {self.highScore:05d}", True, YELLOW)
                self.screen.blit(title, (W // 2 - title.get_width() // 2, 170))
                self.screen.blit(hint, (W // 2 - hint.get_width() // 2, 230))
                self.screen.blit(esc, (W // 2 - esc.get_width() // 2, 262))
                self.screen.blit(hi, (W // 2 - hi.get_width() // 2, 310))
                return

            if self.state == "PAUSED":
                msg = self.bigFont.render("PAUSED", True, YELLOW)
                self.screen.blit(msg, (W // 2 - msg.get_width() // 2, 210))
                self._drawHud()
                return

            if self.state == "GAME_OVER":
                msg = self.bigFont.render("GAME OVER", True, MAGENTA)
                hint = self.font.render("SPACE", True, WHITE)
                self.screen.blit(msg, (W // 2 - msg.get_width() // 2, 190))
                self.screen.blit(hint, (W // 2 - hint.get_width() // 2, 240))
                self._drawHud()
                return

            for bar in self.barriers:
                if not bar.get("dead"):
                    self.screen.blit(bar["surf"], (bar["x"], bar["y"]))

            for e in self.enemies:
                kind = e["kind"]
                img = self.eImg.get(kind)
                if self.idleFrame and self.eIdle.get(kind) is not None:
                    img = self.eIdle.get(kind)
                self._blitC(img, e["x"], e["y"])

            if self.ufo is not None:
                self._blitC(self.ufoImg, self.ufo["x"], self.ufo["y"])

            if self.pBullet is not None:
                for s in self.pShots:
                    self._blitC(self.pBullet, s["x"], s["y"])
            if self.eBullet is not None:
                for s in self.eShots:
                    self._blitC(self.eBullet, s["x"], s["y"])

            if not self.playerDead:
                blink = self.invuln > 0 and int(self.invuln * 12) % 2 == 0
                if not blink:
                    self._blitC(self.playerImg, self.playerX, self.playerY)
                if self.flashT > 0:
                    pw, ph = self._playerSize()
                    frame = self.muzzle[0] if self.flashT > 0.04 else self.muzzle[1]
                    self._blitC(frame, self.playerX, self.playerY - ph * 0.5 - 4)

            for f in self.fx:
                frames = f["frames"]
                i = f["i"]
                if 0 <= i < len(frames) and frames[i] is not None:
                    self._blitC(frames[i], f["x"], f["y"])

            self._drawHud()

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
            self.update(dt, keys)
            self.draw()
            return self.toImage()

        def stop(self):
            self.running = False
            try:
                self.audio.stopUfo()
            except Exception:
                pass
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()

    def _factoryAb(host, markKey="ab"):
        return _CabinetSh(host, markKey, "ab")

    def _factoryLs(host, markKey="ls"):
        return _CabinetSh(host, markKey, "ls")

    _addTitle("ALIEN BLASTER", _factoryAb, "ab")
    _addTitle("LAST STAND", _factoryLs, "ls")

else:
    def _factoryAb(host, markKey="ab"):
        return None

    def _factoryLs(host, markKey="ls"):
        return None
