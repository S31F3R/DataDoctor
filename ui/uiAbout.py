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


def _pygameMixer():
    """pygame.mixer is optional — do not touch pygame.mixer if the module is absent."""
    if pygame is None:
        return None
    try:
        import pygame.mixer as mix
        return mix
    except Exception:
        return None


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


def _logicalPlaySize(lw, lh, baseH=479, minW=640, maxW=3200):
    """Play buffer matches the window aspect at stock height — fill has no bars."""
    lw = max(1, int(lw))
    lh = max(1, int(lh))
    pw = int(round(baseH * (lw / float(lh))))
    return max(minW, min(pw, maxW)), int(baseH)


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
    _BASE_W = 900
    _BASE_H = 479

    def __init__(self, winMain=None):
        # No Qt parent: a child QDialog is transient and GNOME shade-minimizes
        # it to a tiny title bar. Same pattern as Data Dictionary / Query.
        super().__init__(None)
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
        self._backdropSize = None
        self._aboutBgSrc = None
        self._aboutBgSize = None
        self._aboutLaidSize = None
        self._closing = False

        self.backgroundLabel = self.findChild(QLabel, 'backgroundLabel')
        self.textInfo = self.findChild(QTextBrowser, 'textInfo')
        self.buttonSecret = self.findChild(QPushButton, 'buttonSecret')
        # Flags only here (before first show). Toggling them on a live window
        # hides it and can duplicate title-bar buttons on some WMs.
        Utils.bindIndependentWindow(self, owner=winMain, allowMaximize=True)
        # Force NonModal even if an older .ui still says ApplicationModal
        # (modal About shade-minimizes and blocks the main window).
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        # Always resizable. setFixedSize after a larger frame is what left
        # the grey strip and made min/max buttons flicker.
        self.setMinimumSize(720, 383)
        self.resize(self._BASE_W, self._BASE_H)
        self.setWindowTitle(self._TITLE_DEFAULT)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(0, 0, 0))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        pngPath = Logic.resourcePath('ui/DataDoctor.png')
        self._aboutBgSrc = QPixmap(pngPath)
        if self.backgroundLabel is not None:
            self.backgroundLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.backgroundLabel.setStyleSheet("background-color: black;")
        aboutFont = Utils.makeFontForRole('about')
        fam = Utils.ensureRetroFontLoaded() or aboutFont.family()
        pt = Utils.rolePointSize('about', retro=True)
        retroFontObj = QFont(fam, pt)
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self._retroFam = fam
        self._retroPt = pt
        self._aboutInfo = [
            ('Version', Version.displayVersion()),
            ('GitHub', f'https://github.com/{Version.GITHUB_REPO}'),
            ('Author', 'S31F3R'),
            ('License', 'GPL-3.0'),
            ('Music', 'By Eric Matyas at www.soundimage.org')
        ]
        if self.textInfo is not None:
            self.textInfo.setFont(retroFontObj)
            self.textInfo.setOpenExternalLinks(True)
            self.textInfo.setStyleSheet("background-color: transparent; border: none;")
        self.setupSecretButton()
        self.mediaPlayer = None
        self.audioOutput = None
        self.setupMusic()
        self._ensureCabinetWidgets()
        self._ensurePlayHost()
        self._layoutAboutChrome()

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
        self.buttonSecret.setGeometry(self._BASE_W - 26, self._BASE_H - 26, 22, 22)
        self.buttonSecret.setText("")
        self.buttonSecret.setFlat(True)
        # Click only — QDialog would otherwise treat this as the Enter default.
        self.buttonSecret.setAutoDefault(False)
        self.buttonSecret.setDefault(False)
        self.buttonSecret.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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

    def _aboutInfoHtml(self, pt):
        fam = getattr(self, "_retroFam", "monospace")
        pad = max(24, int(round(50 * (pt / float(max(1, self._retroPt))))))
        html = (
            f'<html><body style="color: white; font-family: \'{fam}\'; '
            f'font-size: {pt}pt; padding-left: {pad}px; white-space: nowrap; line-height: 2.2;">'
        )
        for label, content in getattr(self, "_aboutInfo", []):
            if "GitHub" in label:
                html += f'{label}: <a href="{content}" style="color: white;">{content}</a><br>'
            else:
                html += f'{label}: {content}<br>'
        html += '</body></html>'
        return html

    def _layoutAboutChrome(self):
        """Fit the designed 900×479 About frame in the window.

        Cover-crop (like play) ate the ASCII title on wide maximize. Contain
        keeps the whole poster; leftover is the dialog's black fill.
        """
        w = max(1, self.width())
        h = max(1, self.height())
        fit = min(w / float(self._BASE_W), h / float(self._BASE_H))
        fw = max(1, int(round(self._BASE_W * fit)))
        fh = max(1, int(round(self._BASE_H * fit)))
        ox = (w - fw) // 2
        oy = (h - fh) // 2
        if self.backgroundLabel is not None:
            self.backgroundLabel.setGeometry(ox, oy, fw, fh)
            src = self._aboutBgSrc
            key = (fw, fh)
            if src is not None and not src.isNull() and self._aboutBgSize != key:
                self.backgroundLabel.setPixmap(src.scaled(
                    fw, fh,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                self._aboutBgSize = key
        if self.textInfo is not None and not self._cabinetActive():
            pt = max(self._retroPt, int(round(self._retroPt * min(fit, 2.4))))
            self.textInfo.setGeometry(
                ox + int(70 * fit), oy + int(140 * fit),
                max(200, int(800 * fit)), max(80, int(200 * fit)),
            )
            if self._aboutLaidSize != (fw, fh, pt):
                retroFontObj = QFont(self._retroFam, pt)
                retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
                self.textInfo.setFont(retroFontObj)
                self.textInfo.setHtml(self._aboutInfoHtml(pt))
                self._aboutLaidSize = (fw, fh, pt)
        if self.buttonSecret is not None and not self._cabinetActive():
            bs = max(22, int(round(22 * min(fit, 2.0))))
            self.buttonSecret.setGeometry(ox + fw - bs - 4, oy + fh - bs - 4, bs, bs)
            self.buttonSecret.setIconSize(QSize(max(16, bs - 6), max(16, bs - 6)))
            self.buttonSecret.raise_()

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
        hint.setText("ENTER  ·  ESC  ·  F11")
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

    def _cabinetActive(self):
        return bool(self._cabinetMode or self._playMode or self._splashMode)

    def _unlockCabinetSize(self):
        # Size policy is already free. Do not touch flags or setFixedSize.
        self._layoutCabinetChrome()
        if not getattr(self, "_closing", False) and not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()

    def _lockStockSize(self):
        # Keep the current frame (including maximize). Forcing 900×479 here
        # after a larger play window left a grey strip on the right.
        closing = getattr(self, "_closing", False)
        self._aboutBgSize = None
        self._aboutLaidSize = None
        if closing:
            if self.isFullScreen() or self.isMaximized():
                self.showNormal()
            self.resize(self._BASE_W, self._BASE_H)
            return
        self._layoutAboutChrome()
        if self.isVisible():
            self.raise_()
            self.activateWindow()

    def _toggleCabinetFill(self):
        if self.isFullScreen() or self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(0, self._afterFillToggle)

    def _afterFillToggle(self):
        if self._cabinetActive():
            self._layoutCabinetChrome()
            self._syncSessionSize()
        else:
            self._layoutAboutChrome()

    def _layoutCabinetChrome(self):
        w = max(1, self.width())
        h = max(1, self.height())
        scale = max(1.0, h / float(self._BASE_H))
        fam = getattr(self, "_retroFam", "monospace")
        basePt = getattr(self, "_retroPt", 9)
        pt = max(basePt, int(round(basePt * min(scale, 2.4))))

        if self._cabBackdrop is not None:
            self._cabBackdrop.setGeometry(0, 0, w, h)
            if self._backdropSize != (w, h):
                self._cabBackdrop.setPixmap(_starfieldPixmap(w, h))
                self._backdropSize = (w, h)
        if self._cabHeader is not None:
            self._cabHeader.setGeometry(0, int(h * 0.13), w, max(36, int(40 * min(scale, 2.0))))
            self._cabHeader.setStyleSheet(
                f"color: white; background: transparent; font-family: '{fam}'; font-size: {pt + 2}pt;"
            )
        if self._cabList is not None:
            lw = min(720, max(420, int(w * 0.52)))
            lh = max(180, int(h * 0.52))
            self._cabList.setGeometry((w - lw) // 2, int(h * 0.24), lw, lh)
            self._cabList.setStyleSheet(
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
        if self._cabHint is not None:
            self._cabHint.setGeometry(0, h - max(28, int(32 * min(scale, 2.0))), w, max(24, int(30 * min(scale, 2.0))))
            self._cabHint.setStyleSheet(
                f"color: rgba(255,255,255,180); background: transparent; "
                f"font-family: '{fam}'; font-size: {max(6, pt - 2)}pt;"
            )
        if self._playLabel is not None:
            self._playLabel.setGeometry(0, 0, w, h)
        if self._splashBg is not None:
            self._splashBg.setGeometry(0, 0, w, h)
        if self._splashCredits is not None:
            self._splashCredits.setGeometry(40, h // 2 - 30, w - 80, max(50, int(60 * min(scale, 2.0))))
            self._splashCredits.setStyleSheet(
                f"color: #66ffff; background: transparent; "
                f"font-family: '{fam}'; font-size: {pt + 3}pt;"
            )

    def _playLogicalSize(self):
        label = self._playLabel
        lw = max(1, label.width() if label is not None else self.width())
        lh = max(1, label.height() if label is not None else self.height())
        return _logicalPlaySize(lw, lh, self._BASE_H)

    def _syncSessionSize(self):
        sess = self._session
        if sess is None:
            return
        applySize = getattr(sess, "applySize", None)
        if not callable(applySize):
            return
        pw, ph = self._playLogicalSize()
        try:
            applySize(pw, ph)
        except Exception as e:
            Logic.logMessage("WARN", f"Optional view resize failed: {e}")

    def _presentPlayImage(self, qimg):
        """Cover-scale the play buffer so the label is full-bleed (no side bars)."""
        label = self._playLabel
        if label is None or qimg is None or qimg.isNull():
            return
        lw = max(1, label.width())
        lh = max(1, label.height())
        game = QPixmap.fromImage(qimg)
        if game.width() < 1 or game.height() < 1:
            return
        cover = game.scaled(
            lw, lh,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (cover.width() - lw) // 2)
        y = max(0, (cover.height() - lh) // 2)
        label.setPixmap(cover.copy(x, y, lw, lh))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._cabinetActive():
            self._layoutCabinetChrome()
            self._syncSessionSize()
        else:
            self._layoutAboutChrome()

    def changeEvent(self, event):
        super().changeEvent(event)
        # Title-bar maximize can deliver the new size a tick later.
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._afterFillToggle)

    def eventFilter(self, obj, event):
        if self._splashMode and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_F11:
                self._toggleCabinetFill()
                return True
            if key == Qt.Key.Key_Escape:
                self._hideSplash()
                self._returnToCatalog()
                return True
            # Let the intro finish — do not skip or re-launch
            return True

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
            if key == Qt.Key.Key_F11:
                self._toggleCabinetFill()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._launchIndex(self._cabList.currentRow())
                return True
            if self._moveCatalog(key, event.text()):
                return True

        if self._playMode:
            if obj is self._playLabel or obj is self:
                et = event.type()
                if et == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    if event.key() == Qt.Key.Key_F11:
                        self._toggleCabinetFill()
                        return True
                    self._handlePlayKey(event.key(), True, event.text())
                    return True
                if et == QEvent.Type.KeyRelease and not event.isAutoRepeat():
                    self._handlePlayKey(event.key(), False, event.text())
                    return True
                if et == QEvent.Type.MouseButtonPress and self._playMode:
                    self._playPulses.append("click")
                    return True
        return super().eventFilter(obj, event)

    def _handlePlayKey(self, key, pressed, text=""):
        mapping = {
            Qt.Key.Key_Left: "left", Qt.Key.Key_A: "left", Qt.Key.Key_Z: "left",
            Qt.Key.Key_Right: "right", Qt.Key.Key_D: "right", Qt.Key.Key_Slash: "right",
            Qt.Key.Key_Up: "up", Qt.Key.Key_W: "up",
            Qt.Key.Key_Down: "down", Qt.Key.Key_S: "down",
        }
        if key in mapping:
            self._playKeys[mapping[key]] = pressed
            return
        ch = (text or "").lower()
        if ch == "a":
            self._playKeys["left"] = pressed
            return
        if ch == "d":
            self._playKeys["right"] = pressed
            return
        if ch == "w":
            self._playKeys["up"] = pressed
            return
        if ch == "s":
            self._playKeys["down"] = pressed
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
            self._unlockCabinetSize()
            if self.backgroundLabel is not None:
                self.backgroundLabel.hide()
            if self._cabBackdrop is not None:
                self._cabBackdrop.show()
                # Under list chrome / play / splash, above empty dialog
                self._cabBackdrop.lower()
                if self.backgroundLabel is not None:
                    self.backgroundLabel.lower()
            self._layoutCabinetChrome()
        else:
            self.setWindowTitle(self._TITLE_DEFAULT)
            self._lockStockSize()
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
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
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
        if visible:
            self._layoutCabinetChrome()

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

    def _moveCatalog(self, key, text=""):
        """W/S (and arrows) step the SELECT list."""
        if self._cabList is None or self._cabList.count() < 1:
            return False
        ch = (text or "").lower()
        up = key in (Qt.Key.Key_Up, Qt.Key.Key_W) or ch == "w"
        down = key in (Qt.Key.Key_Down, Qt.Key.Key_S) or ch == "s"
        if not up and not down:
            return False
        n = self._cabList.count()
        row = self._cabList.currentRow()
        if row < 0:
            row = 0
        if up:
            row = (row - 1) % n
        else:
            row = (row + 1) % n
        self._cabList.setCurrentRow(row)
        return True

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
        self.setFocus(Qt.FocusReason.OtherFocusReason)
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
        self._layoutCabinetChrome()
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
        mix = _pygameMixer()
        if mix is None:
            return
        try:
            if mix.get_init() is None:
                mix.init(frequency=22050, size=-16, channels=1, buffer=512)
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
        self._layoutCabinetChrome()
        self._syncSessionSize()
        if self._gameTimer is not None:
            self._gameTimer.start()

    def _onGameTick(self):
        if not self._playMode or self._session is None:
            return
        now = time.perf_counter()
        dt = max(0.0, min(0.05, now - self._lastTick))
        self._lastTick = now
        try:
            self._syncSessionSize()
            img = self._session.tick(dt, self._playKeys, self._playPulses)
            self._playPulses = []
            if img is not None and self._playLabel is not None:
                self._presentPlayImage(img)
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
        if event.key() == Qt.Key.Key_F11:
            self._toggleCabinetFill()
            return
        if self._splashMode:
            if event.key() == Qt.Key.Key_Escape:
                self._hideSplash()
                self._returnToCatalog()
                return
            # Intro is not skippable; ignore Enter/Space so SELECT cannot re-fire
            return
        if self._playMode:
            if not event.isAutoRepeat():
                self._handlePlayKey(event.key(), True, event.text())
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
            if self._moveCatalog(key, event.text()):
                return
        # Stock About: QDialog would click the default button on Enter.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self._playMode and not event.isAutoRepeat():
            self._handlePlayKey(event.key(), False, event.text())
            return
        super().keyReleaseEvent(event)

    def show(self):
        self._closing = False
        super().show()

    def exec(self):
        # Modal exec() shade-minimizes on GNOME. About is a free window.
        self.show()
        self.raise_()
        self.activateWindow()
        return QDialog.DialogCode.Accepted

    def closeEvent(self, event):
        self._closing = True
        self.stopMusic()
        self._resetToDefaultAbout()
        super().closeEvent(event)

    def reject(self):
        self._closing = True
        self.stopMusic()
        self._resetToDefaultAbout()
        super().reject()

    def showEvent(self, event):
        if getattr(self, "_closing", False):
            super().showEvent(event)
            return
        if not self._cabinetActive() and not self.isMaximized() and not self.isFullScreen():
            Utils.centerWindowToParent(self)
        if not self._cabinetMode and not self._playMode and not self._splashMode:
            if self.textInfo is not None:
                self.textInfo.show()
            if self.buttonSecret is not None:
                self.buttonSecret.show()
                self.buttonSecret.raise_()
            self._layoutAboutChrome()
            self.startMusic()
        super().showEvent(event)


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
            mix = _pygameMixer()
            if mix is None:
                return None
            return mix.Sound(buffer=bytes(buf))
        except Exception:
            return None

    class _Sfx:
        """One-shots on the same QMediaPlayer path as About music (survives capture apps)."""

        _NAMES = {
            "shoot": "c0.wav",
            "boomE": "c1.wav",
            "boomP": "c2.wav",
            "hit": "c3.wav",
            "ufo": "c4.wav",
            "life": "c5.wav",
            "clear": "c6.wav",
            "over": "c7.wav",
            "eShot": "c8.wav",
        }

        def __init__(self, host=None):
            self.ok = False
            self.sounds = {}
            self._paths = {}
            self._players = {}
            self._ufoName = "ufo"
            self._owner = QObject()
            try:
                for key, fn in self._NAMES.items():
                    path = Logic.resourcePath(f"ui/fx/{fn}")
                    if not path or not os.path.isfile(path):
                        continue
                    path = os.path.abspath(path)
                    self._paths[key] = path
                    out = QAudioOutput(self._owner)
                    out.setVolume(0.95 if key == "boomP" else 0.8)
                    pl = QMediaPlayer(self._owner)
                    pl.setAudioOutput(out)
                    pl.setSource(QUrl.fromLocalFile(path))
                    self._players[key] = pl
                self.ok = bool(self._players)
            except Exception:
                self.ok = False
                self._paths = {}
                self._players = {}

        def play(self, name):
            if not self.ok:
                return
            pl = self._players.get(name)
            if pl is None:
                return
            try:
                pl.stop()
                pl.setPosition(0)
                pl.play()
            except Exception:
                pass

        def stop(self, name=None):
            players = [self._players[name]] if name and name in self._players else list(self._players.values())
            for pl in players:
                try:
                    pl.stop()
                except Exception:
                    pass

        def startUfo(self):
            self.play(self._ufoName)

        def stopUfo(self):
            self.stop(self._ufoName)

    class _Bgm:
        """Per-title menu / play loops on QMediaPlayer (same path as About music)."""

        # markKey → (menu, play)
        _FILES = {
            "ab": ("c9.wav", "c10.wav"),
            "ls": ("c11.wav", "c12.wav"),
            "ic": ("c13.wav", "c14.wav"),
        }

        def __init__(self, host=None, markKey="ab"):
            owner = host if isinstance(host, QObject) else QObject()
            self._owner = owner
            self._menu = None
            self._game = None
            self._cur = None
            pair = self._FILES.get(str(markKey or ""))
            if not pair:
                return
            self._menu = self._load(pair[0], owner)
            self._game = self._load(pair[1], owner)

        def _load(self, fn, owner):
            try:
                path = Logic.resourcePath(f"ui/fx/{fn}")
                if not path or not os.path.isfile(path):
                    return None
                out = QAudioOutput(owner)
                out.setVolume(0.55)
                pl = QMediaPlayer(owner)
                pl.setAudioOutput(out)
                pl.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                pl.setLoops(-1)
                return pl
            except Exception:
                return None

        def playMenu(self):
            self._go(self._menu, restart=True)

        def playGame(self):
            # Same track + unpause: do not rewind
            self._go(self._game, restart=False)

        def pause(self):
            if self._cur is None:
                return
            try:
                self._cur.pause()
            except Exception:
                pass

        def stop(self):
            for pl in (self._menu, self._game):
                if pl is None:
                    continue
                try:
                    pl.stop()
                except Exception:
                    pass
            self._cur = None

        def _go(self, pl, restart):
            if pl is None:
                return
            try:
                if self._cur is pl:
                    if restart:
                        pl.setPosition(0)
                    pl.play()
                    return
                if self._cur is not None:
                    self._cur.stop()
                self._cur = pl
                pl.setPosition(0)
                pl.play()
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
        try:
            surf = pygame.Surface((tw, th)).convert()
        except Exception:
            surf = pygame.Surface((tw, th))
        surf.fill((0, 0, 0))
        surf.blit(scaled, (-x, -y))
        return surf

    def _asOverlay(img):
        """Alpha copy so the star layer cannot paint an opaque black field."""
        if img is None:
            return None
        try:
            work = img.convert_alpha()
        except Exception:
            work = img
        try:
            import numpy as np
            rgb = pygame.surfarray.pixels3d(work)
            alpha = pygame.surfarray.pixels_alpha(work)
            lum = rgb[:, :, 0].astype("uint16") + rgb[:, :, 1] + rgb[:, :, 2]
            alpha[lum < 40] = 0
            del rgb, alpha
        except Exception:
            pass
        return work

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

            self._bgSrc = _loadSurf("b0.png")
            self._starSrc = _loadSurf("b23.png")
            self._view = None
            self.screen = None
            self.bg = None
            self.stars = None
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
            self.eBullets = {
                1: [
                    _fitSurf(_loadSurf("b6.png"), 10, 22),
                    _fitSurf(_loadSurf("b30.png"), 10, 22),
                ],
                2: [
                    _fitSurf(_loadSurf("b31.png"), 14, 36),
                    _fitSurf(_loadSurf("b32.png"), 14, 36),
                ],
                3: [
                    _fitSurf(_loadSurf("b33.png"), 26, 58),
                    _fitSurf(_loadSurf("b34.png"), 26, 58),
                ],
            }
            self.eBullet = (self.eBullets.get(1) or [None])[0]
            self.barrierSrc = _fitSurf(_loadSurf("b7.png"), 108, 42)
            self.ufoImg = _fitSurf(_loadSurf("b16.png"), 52, 36)
            self.lifeImg = _fitSurf(_loadSurf("b17.png"), 16, 16)
            self.muzzle = [
                _fitSurf(_loadSurf("b21.png"), 18, 18),
                _fitSurf(_loadSurf("b22.png"), 20, 20),
            ]
            self.flameBlue = [
                _fitSurf(_loadSurf("b24.png"), 9, 16),
                _fitSurf(_loadSurf("b25.png"), 8, 18),
            ]
            self.flameGreen = [
                _fitSurf(_loadSurf("b26.png"), 8, 12),
                _fitSurf(_loadSurf("b27.png"), 7, 14),
            ]
            self.flameBullet = [
                _fitSurf(_loadSurf("b28.png"), 7, 11),
                _fitSurf(_loadSurf("b29.png"), 7, 12),
            ]
            self.expFrames = {}
            for key, pair in self._EXP.items():
                frames = []
                for fn in pair:
                    frames.append(_fitSurf(_loadSurf(fn), 40, 40))
                self.expFrames[key] = frames

            self.audio = _Sfx(host)
            self.bgm = _Bgm(host, markKey)
            self.highScore = _readMark(self._markKey)
            self.state = "MENU"
            self.score = 0
            self.lives = 3
            self.wave = 1
            self.extraAwarded = False
            self.starOff = 0.0
            self.idleT = 0.0
            self.idleFrame = 0
            self.flameT = 0.0
            self.flameFrame = 0
            self.flashT = 0.0
            self.invuln = 0.0
            self.message = ""
            self.messageT = 0.0
            self.title = "ALIEN BLASTER" if mode == "ab" else "LAST STAND"

            self.playerX = W * 0.5
            self.playerY = H - 51.0
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
            self.tilt = 0.0
            self.applySize(W, H)
            self._syncBgm()

        def applySize(self, pw, ph):
            """Rebuild the offscreen view so the playfield matches the window aspect.

            Height stays ~479; width follows the window. Positions are scaled
            so maximize/un-maximize does not jump the ship or formation.
            """
            global W, H
            pw = max(640, int(pw))
            ph = max(360, int(ph))
            oldW, oldH = W, H
            if self._view == (pw, ph) and self.screen is not None:
                if self.screen.get_size() == (pw, ph):
                    return
            W, H = pw, ph
            self._view = (pw, ph)
            self.screen = pygame.Surface((W, H))
            self.bg = _coverSurf(self._bgSrc, W, H)
            stars = self._starSrc
            if stars is not None:
                try:
                    self.stars = pygame.transform.scale(stars, (W, H))
                except Exception:
                    self.stars = stars
                self.stars = _asOverlay(self.stars)
            else:
                self.stars = None
            if oldW > 0 and oldW != W:
                ratio = W / float(oldW)
                self.playerX *= ratio
                for s in self.pShots:
                    s["x"] *= ratio
                for s in self.eShots:
                    s["x"] *= ratio
                for e in self.enemies:
                    e["x"] *= ratio
                    if "slotX" in e:
                        e["slotX"] *= ratio
                for bar in self.barriers:
                    bar["x"] *= ratio
                if self.ufo is not None:
                    self.ufo["x"] *= ratio
                for f in self.fx:
                    f["x"] *= ratio
            if oldH > 0 and oldH != H:
                yRatio = H / float(oldH)
                self.playerY *= yRatio
                for s in self.pShots:
                    s["y"] *= yRatio
                for s in self.eShots:
                    s["y"] *= yRatio
                for e in self.enemies:
                    e["y"] *= yRatio
                    if "slotY" in e:
                        e["slotY"] *= yRatio
                for bar in self.barriers:
                    bar["y"] *= yRatio
                if self.ufo is not None:
                    self.ufo["y"] *= yRatio
                for f in self.fx:
                    f["y"] *= yRatio
            else:
                self.playerY = H - 51.0
            pwShip, _ph = self._playerSize()
            half = pwShip * 0.5
            self.playerX = max(half + 8, min(W - half - 8, self.playerX))

        def loadHigh(self):
            return _readMark(self._markKey)

        def saveHigh(self):
            _writeMark(self._markKey, self.highScore)

        def playS(self, name):
            self.audio.play(name)

        def _syncBgm(self):
            bgm = getattr(self, "bgm", None)
            if bgm is None:
                return
            if not getattr(self, "running", True):
                bgm.stop()
                return
            if self.state == "PLAYING":
                bgm.playGame()
            elif self.state == "PAUSED":
                bgm.pause()
            elif self.state in ("MENU", "GAME_OVER"):
                bgm.playMenu()
            else:
                bgm.stop()

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
            self.audio.stop()
            self.score = 0
            self.lives = 3
            self.wave = 1
            self.extraAwarded = False
            self.highScore = self.loadHigh()
            self.playerX = W * 0.5
            self.playerY = H - 51.0
            self.tilt = 0.0
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
            self._syncBgm()

        def _addEnemy(self, kind, slotX, slotY, inbound=False, delay=0.0):
            if inbound:
                side = -1 if (int(slotX) + int(slotY)) % 2 == 0 else 1
                startX = -40.0 if side < 0 else float(W + 40)
                startY = 28.0 + random.random() * 36.0
                st = "IN"
                t = -delay
            else:
                startX, startY = slotX, slotY
                st = "FORM"
                t = 0.0
            self.enemies.append({
                "kind": kind,
                "x": startX,
                "y": startY,
                "slotX": slotX,
                "slotY": slotY,
                "st": st,
                "t": t,
                "phase": random.random() * 6.28,
                "shot": False,
            })

        def _setupWave(self):
            self.pShots = []
            self.eShots = []
            self.enemies = []
            self.formDx = 1
            self.formStepT = 0.0
            self.formInterval = max(0.12, 0.56 - (self.wave - 1) * 0.05)
            self.eShootT = 0.8
            self.diveT = 1.6
            delay = 0.0
            span = W / 900.0
            if self.mode == "ls":
                # Tapered hold: fewer on top, wider below (centered).
                layout = (
                    (3, 4, 86.0 * span),
                    (2, 6, 72.0 * span),
                    (1, 8, 64.0 * span),
                    (1, 10, 58.0 * span),
                )
                originY = 50.0
                gapY = 36.0
                for r, (kind, count, gapX) in enumerate(layout):
                    rowW = (count - 1) * gapX
                    left = (W - rowW) * 0.5
                    for c in range(count):
                        self._addEnemy(
                            kind, left + c * gapX, originY + r * gapY,
                            inbound=True, delay=delay,
                        )
                        delay += 0.08
            else:
                cols, rows = 8, 4
                gapX, gapY = 78.0 * span, 38
                rowW = (cols - 1) * gapX
                originX = (W - rowW) * 0.5
                originY = 58.0
                kinds = [3, 2, 1, 1]
                for r in range(rows):
                    for c in range(cols):
                        self._addEnemy(
                            kinds[r], originX + c * gapX, originY + r * gapY,
                        )
            self.inboundLeft = sum(1 for e in self.enemies if e["st"] == "IN")
            self.barriers = []
            if self.mode == "ab" and self.barrierSrc is not None:
                bw, bh = self.barrierSrc.get_size()
                n = 4
                margin = max(40.0, W * 0.10)
                spanX = max(0.0, W - 2 * margin - bw)
                xs = [margin + spanX * i / (n - 1) for i in range(n)] if n > 1 else [W * 0.5 - bw * 0.5]
                for bx in xs:
                    surf = self.barrierSrc.copy()
                    self.barriers.append({
                        "x": float(bx),
                        "y": H - 113,
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

        def _enemyFire(self, x, y, kind=1):
            self.eShots.append({"x": x, "y": y, "kind": int(kind or 1)})
            self.playS("eShot")

        def _eShotImg(self, shot):
            kind = shot.get("kind", 1)
            frames = self.eBullets.get(kind) or self.eBullets.get(1) or []
            if not frames:
                return None
            return frames[self.flameFrame % len(frames)]

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
                self._syncBgm()
                return
            self.playerDead = False
            self.playerX = W * 0.5
            self.tilt = 0.0
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
                        self.audio.stop()
                        self.state = "MENU"
                    elif self.state == "PAUSED":
                        self.audio.stop()
                        self.state = "MENU"
                    else:
                        self.audio.stop()
                        self.running = False
                    self._syncBgm()
                elif p == "p":
                    if self.state == "PLAYING":
                        self.audio.stop()
                        self.state = "PAUSED"
                    elif self.state == "PAUSED":
                        self.state = "PLAYING"
                    self._syncBgm()
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
            self.flameT += dt
            self.flameFrame = 0 if int(self.flameT / 0.07) % 2 == 0 else 1
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
            wantTilt = 0.0
            if keys.get("left") and not keys.get("right"):
                wantTilt = 16.0
            elif keys.get("right") and not keys.get("left"):
                wantTilt = -16.0
            self.tilt += (wantTilt - self.tilt) * min(1.0, 14.0 * dt)

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
                # Any living type can fire so back-row bolts actually appear
                weights = [max(0.4, float(e["y"])) for e in living]
                shooter = random.choices(living, weights=weights, k=1)[0]
                self._enemyFire(shooter["x"], shooter["y"] + 14, shooter.get("kind", 1))

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
                    self._enemyFire(e["x"], e["y"] + 12, e.get("kind", 1))
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
                self._enemyFire(shooter["x"], shooter["y"] + 14, shooter.get("kind", 1))

        def _collide(self):
            pbw, pbh = (6, 16)
            if self.pBullet is not None:
                pbw, pbh = self.pBullet.get_size()
            ebw, ebh = (6, 16)

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
                img = self._eShotImg(s)
                if img is not None:
                    ebw, ebh = img.get_size()
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

        def _rotOff(self, dx, dy, angDeg):
            rad = math.radians(angDeg)
            c, s = math.cos(rad), math.sin(rad)
            return dx * c + dy * s, -dx * s + dy * c

        def _playerDrawImg(self):
            img = self.playerImg
            if img is None or abs(self.tilt) < 0.6:
                return img
            try:
                return pygame.transform.rotozoom(img, self.tilt, 1.0)
            except Exception:
                return img

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
                y = int(self.starOff) % H
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

            fi = self.flameFrame
            if self.pBullet is not None:
                for s in self.pShots:
                    trail = None
                    if self.flameBullet:
                        trail = self.flameBullet[fi % len(self.flameBullet)]
                    if trail is not None:
                        bh = self.pBullet.get_height()
                        self._blitC(trail, s["x"], s["y"] + bh * 0.42)
                    self._blitC(self.pBullet, s["x"], s["y"])
            for s in self.eShots:
                img = self._eShotImg(s)
                if img is not None:
                    self._blitC(img, s["x"], s["y"])

            if not self.playerDead:
                blink = self.invuln > 0 and int(self.invuln * 12) % 2 == 0
                pw, ph = self._playerSize()
                ship = self._playerDrawImg()
                if not blink:
                    self._blitC(ship, self.playerX, self.playerY)
                    blue = self.flameBlue[fi % len(self.flameBlue)] if self.flameBlue else None
                    green = self.flameGreen[fi % len(self.flameGreen)] if self.flameGreen else None
                    bx, by = self._rotOff(-6, ph * 0.48, self.tilt)
                    bx2, by2 = self._rotOff(6, ph * 0.48, self.tilt)
                    gx, gy = self._rotOff(-pw * 0.42, ph * 0.36, self.tilt)
                    gx2, gy2 = self._rotOff(pw * 0.42, ph * 0.36, self.tilt)
                    if blue is not None:
                        self._blitC(blue, self.playerX + bx, self.playerY + by)
                        self._blitC(blue, self.playerX + bx2, self.playerY + by2)
                    if green is not None:
                        self._blitC(green, self.playerX + gx, self.playerY + gy)
                        self._blitC(green, self.playerX + gx2, self.playerY + gy2)
                if self.flashT > 0:
                    frame = self.muzzle[0] if self.flashT > 0.04 else self.muzzle[1]
                    mx, my = self._rotOff(0, -ph * 0.5 - 4, self.tilt)
                    self._blitC(frame, self.playerX + mx, self.playerY + my)

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
                self.audio.stop()
            except Exception:
                pass
            try:
                self.bgm.stop()
            except Exception:
                pass
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()

    class _CabinetIn:
        """Horizontal free-flight scroller — original title Incursion."""

        WORLD = 3600
        _EXP = {
            "player": ("b8.png", "b9.png"),
            "e2": ("b8.png", "b9.png"),
            "e1": ("b10.png", "b11.png"),
            "e3": ("b12.png", "b13.png"),
            "ufo": ("b14.png", "b15.png"),
        }

        def __init__(self, host, markKey="ic"):
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
            _ensureDisplay()

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

            self._bgSrc = _loadSurf("b0.png")
            self._starSrc = _loadSurf("b23.png")
            self._view = None
            self.screen = None
            self.bg = None
            self.stars = None
            self.bgLoop = None
            self.starLoop = None
            side = _loadSurf("b35.png")
            self.playerR = _fitSurf(side, 72, 38)
            self.playerL = None
            if self.playerR is not None:
                try:
                    self.playerL = pygame.transform.flip(self.playerR, True, False)
                except Exception:
                    self.playerL = self.playerR
            # Horizontal bolt is authored tip-right. Flip for left fire.
            self.pBulletR = _fitSurf(_loadSurf("b36.png"), 18, 6)
            self.pBulletL = None
            if self.pBulletR is not None:
                try:
                    self.pBulletL = pygame.transform.flip(self.pBulletR, True, False)
                except Exception:
                    self.pBulletL = self.pBulletR
            # Same trail as AB/LS, laid over for left/right so it stays behind the tip.
            rawTrail = [
                _fitSurf(_loadSurf("b28.png"), 7, 11),
                _fitSurf(_loadSurf("b29.png"), 7, 12),
            ]
            self.pTrailR = [self._rot90(f, clockwise=True) for f in rawTrail]
            self.pTrailL = []
            for f in self.pTrailR:
                if f is None:
                    self.pTrailL.append(None)
                else:
                    try:
                        self.pTrailL.append(pygame.transform.flip(f, True, False))
                    except Exception:
                        self.pTrailL.append(f)
            self.eImg = {
                1: _fitSurf(_loadSurf("b3.png"), 30, 28),
                2: _fitSurf(_loadSurf("b4.png"), 32, 30),
                3: _fitSurf(_loadSurf("b5.png"), 28, 36),
            }
            self.eIdle = {
                1: _fitSurf(_loadSurf("b18.png"), 30, 28),
                2: _fitSurf(_loadSurf("b19.png"), 32, 30),
                3: _fitSurf(_loadSurf("b20.png"), 28, 36),
            }
            # Authored nose-down (e3 ball at the bottom, tail up). Aimed at fire.
            self.eBullets = {
                1: [
                    _fitSurf(_loadSurf("b6.png"), 8, 20),
                    _fitSurf(_loadSurf("b30.png"), 8, 20),
                ],
                2: [
                    _fitSurf(_loadSurf("b31.png"), 10, 28),
                    _fitSurf(_loadSurf("b32.png"), 10, 28),
                ],
                3: [
                    _fitSurf(_loadSurf("b33.png"), 18, 40),
                    _fitSurf(_loadSurf("b34.png"), 18, 40),
                ],
            }
            self.ufoBullets = [
                _fitSurf(_loadSurf("b37.png"), 22, 22),
                _fitSurf(_loadSurf("b38.png"), 22, 22),
            ]
            self.ufoImg = _fitSurf(_loadSurf("b16.png"), 44, 30)
            self.lifeImg = _fitSurf(_loadSurf("b17.png"), 16, 16)
            flameR = [
                self._rot90(_fitSurf(_loadSurf("b24.png"), 9, 16), clockwise=True),
                self._rot90(_fitSurf(_loadSurf("b25.png"), 8, 18), clockwise=True),
            ]
            self.flameR = flameR
            self.flameL = []
            for f in flameR:
                if f is None:
                    self.flameL.append(None)
                else:
                    try:
                        self.flameL.append(pygame.transform.flip(f, True, False))
                    except Exception:
                        self.flameL.append(f)
            self.expFrames = {}
            for key, pair in self._EXP.items():
                frames = []
                for fn in pair:
                    frames.append(_fitSurf(_loadSurf(fn), 36, 36))
                self.expFrames[key] = frames

            self.audio = _Sfx(host)
            self.bgm = _Bgm(host, markKey)
            self.highScore = _readMark(self._markKey)
            self.state = "MENU"
            self.title = "INCURSION"
            self.score = 0
            self.lives = 3
            self.wave = 1
            self.extraAwarded = False
            self.playerX = 400.0
            self.playerY = H * 0.5
            self.vx = 0.0
            self.vy = 0.0
            self.face = 1
            self.camX = 0.0
            self.camShift = 0.0
            self.playerDead = False
            self.dieWait = 0.0
            self.invuln = 0.0
            self.pShots = []
            self.eShots = []
            self.enemies = []
            self.fx = []
            self.idleT = 0.0
            self.idleFrame = 0
            self.flameT = 0.0
            self.flameFrame = 0
            self.message = ""
            self.messageT = 0.0
            self.maxPShots = 3
            self.accel = 780.0
            self.maxSpeed = 300.0
            self.drag = 2.4
            self.applySize(W, H)
            self._syncBgm()

        def applySize(self, pw, ph):
            """Widen the camera window to the host aspect.

            World coords stay put — a wider window just shows more of the course.
            """
            global W, H
            pw = max(640, int(pw))
            ph = max(360, int(ph))
            pw = min(pw, max(640, self.WORLD - 200))
            if self._view == (pw, ph) and self.screen is not None:
                if self.screen.get_size() == (pw, ph):
                    return
            oldH = H
            W, H = pw, ph
            self._view = (pw, ph)
            self.screen = pygame.Surface((W, H))
            self.bg = _coverSurf(self._bgSrc, W, H)
            stars = self._starSrc
            if stars is not None:
                try:
                    self.stars = pygame.transform.scale(stars, (W, H))
                except Exception:
                    self.stars = stars
                self.stars = _asOverlay(self.stars)
            else:
                self.stars = None
            self.bgLoop = self._loopStrip(self.bg, alpha=False)
            self.starLoop = self._loopStrip(self.stars, alpha=True)
            if oldH > 0 and oldH != H:
                yRatio = H / float(oldH)
                self.playerY *= yRatio
                for s in self.pShots:
                    s["y"] *= yRatio
                for s in self.eShots:
                    s["y"] *= yRatio
                for e in self.enemies:
                    e["y"] *= yRatio
                for f in self.fx:
                    f["y"] *= yRatio
            _pw, phShip = self._playerSize()
            self.playerY = max(40 + phShip * 0.5, min(H - 22 - phShip * 0.5, self.playerY))

        def _rot90(self, img, clockwise=False):
            if img is None:
                return None
            try:
                ang = -90 if clockwise else 90
                return pygame.transform.rotate(img, ang)
            except Exception:
                return img

        def _aimBolt(self, frames, vx, vy):
            """Rotate nose-down bolt frames so the head leads (vx, vy)."""
            if not frames:
                return []
            ang = 90.0 - math.degrees(math.atan2(vy, vx))
            out = []
            for img in frames:
                if img is None:
                    out.append(None)
                    continue
                try:
                    out.append(pygame.transform.rotozoom(img, ang, 1.0))
                except Exception:
                    try:
                        out.append(pygame.transform.rotate(img, ang))
                    except Exception:
                        out.append(img)
            return out

        def _loopStrip(self, img, alpha=False):
            """Mirror-join so horizontal wrap has no hard cut."""
            if img is None:
                return None
            try:
                iw, ih = img.get_size()
                flags = pygame.SRCALPHA if alpha else 0
                strip = pygame.Surface((iw * 2, ih), flags)
                if not alpha:
                    try:
                        strip = strip.convert()
                    except Exception:
                        pass
                    strip.fill((0, 0, 0))
                strip.blit(img, (0, 0))
                try:
                    strip.blit(pygame.transform.flip(img, True, False), (iw, 0))
                except Exception:
                    strip.blit(img, (iw, 0))
                return strip
            except Exception:
                return img

        def loadHigh(self):
            return _readMark(self._markKey)

        def saveHigh(self):
            _writeMark(self._markKey, self.highScore)

        def playS(self, name):
            self.audio.play(name)

        def _syncBgm(self):
            bgm = getattr(self, "bgm", None)
            if bgm is None:
                return
            if not getattr(self, "running", True):
                bgm.stop()
                return
            if self.state == "PLAYING":
                bgm.playGame()
            elif self.state == "PAUSED":
                bgm.pause()
            elif self.state in ("MENU", "GAME_OVER"):
                bgm.playMenu()
            else:
                bgm.stop()

        def _wrap(self, x):
            w = self.WORLD
            return x % w

        def _wrapDelta(self, a, b):
            w = self.WORLD
            return (a - b + w * 0.5) % w - w * 0.5

        def _sx(self, wx):
            return (wx - self.camX) % self.WORLD

        def _screenXs(self, wx, pad=80):
            s = self._sx(wx)
            out = []
            if -pad <= s <= W + pad:
                out.append(s)
            if s > self.WORLD - W - pad:
                out.append(s - self.WORLD)
            return out

        def beginPlay(self):
            self.audio.stop()
            self.score = 0
            self.lives = 3
            self.wave = 1
            self.extraAwarded = False
            self.highScore = self.loadHigh()
            self.playerX = 400.0
            self.playerY = H * 0.5
            self.vx = 0.0
            self.vy = 0.0
            self.face = 1
            self.camX = 0.0
            self.camShift = 0.0
            self.playerDead = False
            self.dieWait = 0.0
            self.invuln = 0.0
            self.pShots = []
            self.eShots = []
            self.fx = []
            self.message = ""
            self.messageT = 0.0
            self.state = "PLAYING"
            self._setupWave()
            self._syncBgm()

        def _setupWave(self):
            self.enemies = []
            n = 7 + self.wave * 2
            n = min(18, n)
            for i in range(n):
                kind = 1 if i % 5 < 3 else (2 if i % 5 == 3 else 3)
                self.enemies.append({
                    "kind": kind,
                    "x": random.random() * self.WORLD,
                    "y": 50 + random.random() * 360,
                    "vx": random.uniform(-40, 40),
                    "vy": random.uniform(-30, 30),
                    "shotT": random.uniform(0.6, 2.2),
                    "ufo": False,
                })
            if self.wave >= 2:
                self.enemies.append({
                    "kind": 2,
                    "x": random.random() * self.WORLD,
                    "y": 80 + random.random() * 200,
                    "vx": 90 if random.random() < 0.5 else -90,
                    "vy": 0.0,
                    "shotT": 1.4,
                    "ufo": True,
                })

        def _addScore(self, n):
            self.score += int(n)
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()
            if (not self.extraAwarded) and self.score >= 2000:
                self.extraAwarded = True
                self.lives += 1
                self.playS("life")
                self.message = "EXTRA LIFE"
                self.messageT = 1.4

        def _spawnFx(self, kind, x, y):
            frames = self.expFrames.get(kind) or self.expFrames.get("e1") or []
            self.fx.append({"x": x, "y": y, "frames": frames, "i": 0, "t": 0.0})

        def _playerSize(self):
            img = self.playerR if self.face >= 0 else self.playerL
            if img is not None:
                return img.get_size()
            return (64, 32)

        def _overlap(self, a, b):
            return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]

        def _firePlayer(self):
            if self.playerDead or self.state != "PLAYING":
                return
            if len(self.pShots) >= self.maxPShots:
                return
            pw, _ph = self._playerSize()
            self.pShots.append({
                "x": self.playerX + self.face * pw * 0.45,
                "y": self.playerY,
                "vx": self.face * 420.0,
                "gone": 0.0,
            })
            self.playS("shoot")

        def _killPlayer(self):
            if self.playerDead or self.invuln > 0:
                return
            self.playerDead = True
            self.dieWait = 1.25
            self._spawnFx("player", self.playerX, self.playerY)
            self.playS("boomP")
            self.lives -= 1
            self.pShots = []
            if self.lives <= 0:
                self.saveHigh()

        def _nextLifeOrOver(self):
            if self.lives <= 0:
                self.state = "GAME_OVER"
                self.playS("over")
                self.saveHigh()
                self._syncBgm()
                return
            self.playerDead = False
            self.invuln = 1.6
            self.vx = 0.0
            self.vy = 0.0
            self.eShots = []

        def handlePulses(self, pulses, keys):
            for p in pulses:
                if p == "escape":
                    self.audio.stop()
                    if self.state in ("PLAYING", "PAUSED"):
                        self.state = "MENU"
                    else:
                        self.running = False
                    self._syncBgm()
                elif p == "p":
                    if self.state == "PLAYING":
                        self.audio.stop()
                        self.state = "PAUSED"
                    elif self.state == "PAUSED":
                        self.state = "PLAYING"
                    self._syncBgm()
                elif p in ("space", "click"):
                    if self.state in ("MENU", "GAME_OVER"):
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
            self.flameT += dt
            self.flameFrame = 0 if int(self.flameT / 0.07) % 2 == 0 else 1
            if self.invuln > 0:
                self.invuln -= dt

            if self.playerDead:
                self.dieWait -= dt
                self._updateFx(dt)
                if self.dieWait <= 0:
                    self._nextLifeOrOver()
                return

            ax = 0.0
            ay = 0.0
            if keys.get("left"):
                ax -= 1.0
                self.face = -1
            if keys.get("right"):
                ax += 1.0
                self.face = 1
            if keys.get("up"):
                ay -= 1.0
            if keys.get("down"):
                ay += 1.0
            if ax and ay:
                ax *= 0.707
                ay *= 0.707
            self.vx += ax * self.accel * dt
            self.vy += ay * self.accel * dt
            damp = max(0.0, 1.0 - self.drag * dt)
            if not ax:
                self.vx *= damp
            if not ay:
                self.vy *= damp
            sp = math.hypot(self.vx, self.vy)
            if sp > self.maxSpeed:
                self.vx *= self.maxSpeed / sp
                self.vy *= self.maxSpeed / sp
            self.playerX = self._wrap(self.playerX + self.vx * dt)
            self.playerY += self.vy * dt
            pw, ph = self._playerSize()
            self.playerY = max(40 + ph * 0.5, min(H - 22 - ph * 0.5, self.playerY))

            # Keep the ship centered. Look-ahead follows velocity only (not facing),
            # so flipping left/right does not yank the whole view.
            look = max(-55.0, min(55.0, self.vx * 0.16))
            target = self.playerX - W * 0.5 + look
            oldCam = self.camX
            self.camX = self._wrap(oldCam + self._wrapDelta(target, oldCam) * min(1.0, 3.2 * dt))
            self.camShift += self._wrapDelta(self.camX, oldCam)

            # Player bolts do not wrap — a miss leaves the view and frees the slot.
            keepP = []
            for s in self.pShots:
                s["x"] += s["vx"] * dt
                s["gone"] = s.get("gone", 0.0) + abs(s["vx"] * dt)
                sx = self._wrapDelta(s["x"], self.camX)
                if s["gone"] > self.WORLD * 0.4:
                    continue
                if sx < -48 or sx > W + 48:
                    continue
                keepP.append(s)
            self.pShots = keepP

            for s in self.eShots:
                s["x"] = self._wrap(s["x"] + s["vx"] * dt)
                s["y"] += s["vy"] * dt
            self.eShots = [s for s in self.eShots if 20 < s["y"] < H - 8]

            for e in self.enemies:
                dx = self._wrapDelta(self.playerX, e["x"])
                dy = self.playerY - e["y"]
                dist = math.hypot(dx, dy) or 1.0
                chase = 55.0 + self.wave * 6
                if e.get("ufo"):
                    chase += 40
                e["vx"] += (dx / dist) * chase * dt * 0.35
                e["vy"] += (dy / dist) * chase * dt * 0.35
                e["vx"] += math.sin(e["x"] * 0.01 + e["y"] * 0.02) * 18 * dt
                ev = math.hypot(e["vx"], e["vy"])
                cap = 70 if not e.get("ufo") else 140
                if ev > cap:
                    e["vx"] *= cap / ev
                    e["vy"] *= cap / ev
                e["x"] = self._wrap(e["x"] + e["vx"] * dt)
                e["y"] += e["vy"] * dt
                e["y"] = max(46, min(H - 28, e["y"]))
                e["shotT"] -= dt
                if e["shotT"] <= 0 and dist < 420:
                    e["shotT"] = max(0.7, 1.8 - self.wave * 0.08)
                    spd = 160.0
                    vx = (dx / dist) * spd
                    vy = (dy / dist) * spd
                    kind = e["kind"]
                    base = self.eBullets.get(kind) or self.eBullets.get(1) or []
                    self.eShots.append({
                        "x": e["x"],
                        "y": e["y"],
                        "vx": vx,
                        "vy": vy,
                        "kind": kind,
                        "ufo": bool(e.get("ufo")),
                        "imgs": None if e.get("ufo") else self._aimBolt(base, vx, vy),
                    })
                    self.playS("eShot")

            self._collide()
            self._updateFx(dt)
            if not self.playerDead and not self.enemies:
                self.playS("clear")
                self.wave += 1
                self.message = f"WAVE {self.wave}"
                self.messageT = 1.4
                self._setupWave()

        def _collide(self):
            if self.playerDead:
                return
            pw, ph = self._playerSize()

            # Hurt the player first so ramming is never a free kill
            for s in list(self.eShots):
                img = None
                if s.get("ufo") and getattr(self, "ufoBullets", None):
                    frames = self.ufoBullets
                else:
                    frames = s.get("imgs") or self.eBullets.get(s.get("kind", 1)) or []
                if frames:
                    img = frames[self.flameFrame % len(frames)]
                ebw, ebh = (14, 10)
                if img is not None:
                    ebw, ebh = img.get_size()
                if self._viewHit(s["x"], s["y"], ebw * 0.5, ebh * 0.5, pw * 0.42, ph * 0.42):
                    try:
                        self.eShots.remove(s)
                    except ValueError:
                        pass
                    self._killPlayer()
                    return

            for e in list(self.enemies):
                ew, eh = (28, 28)
                img = self.ufoImg if e.get("ufo") and self.ufoImg is not None else self.eImg.get(e["kind"])
                if img is not None:
                    ew, eh = img.get_size()
                if self._viewHit(e["x"], e["y"], ew * 0.4, eh * 0.4, pw * 0.42, ph * 0.42):
                    if self.invuln > 0:
                        continue
                    tag = "ufo" if e.get("ufo") else {1: "e1", 2: "e2", 3: "e3"}.get(e["kind"], "e1")
                    self._spawnFx(tag, e["x"], e["y"])
                    self.playS("boomE")
                    try:
                        self.enemies.remove(e)
                    except ValueError:
                        pass
                    self._killPlayer()
                    return

            pbw, pbh = (16, 6)
            if self.pBulletR is not None:
                pbw, pbh = self.pBulletR.get_size()
            keepP = []
            for s in self.pShots:
                hit = False
                for e in list(self.enemies):
                    ew, eh = (28, 28)
                    img = self.ufoImg if e.get("ufo") and self.ufoImg is not None else self.eImg.get(e["kind"])
                    if img is not None:
                        ew, eh = img.get_size()
                    if self._hitOnce(s["x"], s["y"], pbw * 0.5, pbh * 0.5, e["x"], e["y"], ew * 0.45, eh * 0.45):
                        tag = "ufo" if e.get("ufo") else {1: "e1", 2: "e2", 3: "e3"}.get(e["kind"], "e1")
                        self._spawnFx(tag, e["x"], e["y"])
                        pts = 150 if e.get("ufo") else {1: 20, 2: 40, 3: 60}.get(e["kind"], 20)
                        self._addScore(pts)
                        self.playS("boomE")
                        self.enemies.remove(e)
                        hit = True
                        break
                if not hit:
                    keepP.append(s)
            self.pShots = keepP

        def _viewHit(self, ax, ay, ahw, ahh, bhw, bhh, bx=None, by=None):
            """Hit test in camera space so on-screen overlaps match damage."""
            if bx is None:
                bx, by = self.playerX, self.playerY
            for sax in self._screenXs(ax, pad=160):
                for sbx in self._screenXs(bx, pad=160):
                    if self._overlap(
                        (sax - ahw, ay - ahh, ahw * 2, ahh * 2),
                        (sbx - bhw, by - bhh, bhw * 2, bhh * 2),
                    ):
                        return True
            return False

        def _hitOnce(self, ax, ay, ahw, ahh, bx, by, bhw, bhh):
            """Player-bolt hit test — no world wrap, so a miss cannot strike the far edge."""
            sax = self._wrapDelta(ax, self.camX)
            if sax < -80 or sax > W + 80:
                return False
            for sbx in self._screenXs(bx, pad=80):
                if self._overlap(
                    (sax - ahw, ay - ahh, ahw * 2, ahh * 2),
                    (sbx - bhw, by - bhh, bhw * 2, bhh * 2),
                ):
                    return True
            return False

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

        def _drawWorld(self, img, wx, wy):
            if img is None:
                return
            for sx in self._screenXs(wx):
                self._blitC(img, sx, wy)

        def _drawOnce(self, img, wx, wy):
            """Blit in camera space without wrapping to the opposite edge."""
            if img is None:
                return
            sx = self._wrapDelta(wx, self.camX)
            if -80 <= sx <= W + 80:
                self._blitC(img, sx, wy)

        def _drawHud(self):
            score = self.font.render(f"{self.score:05d}", True, WHITE)
            hi = self.font.render(f"HI {self.highScore:05d}", True, YELLOW)
            wave = self.font.render(f"W{self.wave}", True, CYAN)
            self.screen.blit(score, (16, 6))
            self.screen.blit(hi, (W // 2 - hi.get_width() // 2, 6))
            self.screen.blit(wave, (W - 70, 6))
            # scanner
            bar = pygame.Rect(80, 22, W - 160, 6)
            pygame.draw.rect(self.screen, (20, 30, 40), bar)
            pygame.draw.rect(self.screen, (80, 120, 140), bar, 1)
            for e in self.enemies:
                px = bar.x + int((e["x"] / self.WORLD) * bar.w)
                col = (0, 220, 255) if e.get("ufo") else ((180, 80, 255) if e["kind"] == 1 else ((255, 80, 80) if e["kind"] == 2 else (120, 80, 255)))
                pygame.draw.rect(self.screen, col, (px, bar.y, 2, bar.h))
            px = bar.x + int((self.playerX / self.WORLD) * bar.w)
            pygame.draw.rect(self.screen, (80, 255, 255), (px - 1, bar.y - 1, 3, bar.h + 2))
            if self.lifeImg is not None:
                for i in range(max(0, self.lives)):
                    self.screen.blit(self.lifeImg, (16 + i * 20, H - 22))
            if self.messageT > 0 and self.message:
                msg = self.bigFont.render(self.message, True, YELLOW)
                self.screen.blit(msg, (W // 2 - msg.get_width() // 2, 210))

        def _blitParallax(self, strip, factor):
            if strip is None:
                return
            period = strip.get_width()
            if period < 1:
                return
            off = int(-(self.camShift * factor) % period)
            self.screen.blit(strip, (off - period, 0))
            self.screen.blit(strip, (off, 0))
            if off + period < W:
                self.screen.blit(strip, (off + period, 0))

        def draw(self):
            if self.bg is not None or self.bgLoop is not None:
                self._blitParallax(self.bgLoop or self.bg, 0.28)
            else:
                self.screen.fill((4, 2, 12))
            # Stars stay alpha — never bake them onto an opaque black strip
            if self.starLoop is not None:
                self._blitParallax(self.starLoop, 0.62)
            elif self.stars is not None:
                self._blitParallax(self.stars, 0.62)

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

            fi = self.flameFrame
            for e in self.enemies:
                if e.get("ufo") and self.ufoImg is not None:
                    img = self.ufoImg
                else:
                    img = self.eImg.get(e["kind"])
                    if self.idleFrame and self.eIdle.get(e["kind"]) is not None:
                        img = self.eIdle.get(e["kind"])
                self._drawWorld(img, e["x"], e["y"])

            for s in self.pShots:
                goingR = s["vx"] >= 0
                bolt = self.pBulletR if goingR else self.pBulletL
                trails = self.pTrailR if goingR else self.pTrailL
                trail = trails[fi % len(trails)] if trails else None
                if trail is not None and bolt is not None:
                    bw = bolt.get_width()
                    self._drawOnce(trail, s["x"] - (1 if goingR else -1) * bw * 0.42, s["y"])
                self._drawOnce(bolt, s["x"], s["y"])
            for s in self.eShots:
                if s.get("ufo") and self.ufoBullets:
                    frames = self.ufoBullets
                else:
                    frames = s.get("imgs") or self.eBullets.get(s.get("kind", 1)) or []
                img = frames[fi % len(frames)] if frames else None
                self._drawWorld(img, s["x"], s["y"])

            if not self.playerDead:
                blink = self.invuln > 0 and int(self.invuln * 12) % 2 == 0
                if not blink:
                    ship = self.playerR if self.face >= 0 else self.playerL
                    self._drawWorld(ship, self.playerX, self.playerY)
                    flames = self.flameR if self.face >= 0 else self.flameL
                    fl = flames[fi % len(flames)] if flames else None
                    if fl is not None:
                        pw, _ph = self._playerSize()
                        self._drawWorld(fl, self.playerX - self.face * pw * 0.48, self.playerY)

            for f in self.fx:
                frames = f["frames"]
                i = f["i"]
                if 0 <= i < len(frames) and frames[i] is not None:
                    self._drawWorld(frames[i], f["x"], f["y"])
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
                self.audio.stop()
            except Exception:
                pass
            try:
                self.bgm.stop()
            except Exception:
                pass
            if self.score > self.highScore:
                self.highScore = self.score
                self.saveHigh()

    def _factoryAb(host, markKey="ab"):
        return _CabinetSh(host, markKey, "ab")

    def _factoryLs(host, markKey="ls"):
        return _CabinetSh(host, markKey, "ls")

    def _factoryIc(host, markKey="ic"):
        return _CabinetIn(host, markKey)

    _addTitle("ALIEN BLASTER", _factoryAb, "ab")
    _addTitle("LAST STAND", _factoryLs, "ls")
    _addTitle("INCURSION", _factoryIc, "ic")

else:
    def _factoryAb(host, markKey="ab"):
        return None

    def _factoryLs(host, markKey="ls"):
        return None

    def _factoryIc(host, markKey="ic"):
        return None
