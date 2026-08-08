# uiAbout.py

import os
from PyQt6.QtWidgets import QDialog, QLabel, QTextBrowser, QPushButton, QMessageBox
from PyQt6.QtCore import Qt, QUrl, QSize, QObject, QEvent
from PyQt6.QtGui import QPixmap, QFont, QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6 import uic
from core import Logic, Utils, Config, Version

class uiAbout(QDialog):
    """About dialog: Retro PNG bg with transparent info overlay and looping music."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winAbout.ui'), self)
        self.winMain = winMain

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

        filterObj = _WorthyKeyFilter(dlg)
        dlg.installEventFilter(filterObj)
        # Catch keys even when a child has focus
        for child in dlg.findChildren(QObject):
            try:
                child.installEventFilter(filterObj)
            except Exception:
                pass

        dlg.exec()

    def showEvent(self, event):        
        Logic.logMessage("WARN", f"uiAbout showEvent")
        Utils.centerWindowToParent(self)
        self.startMusic()
        super().showEvent(event)
    
    def closeEvent(self, event):
        self.stopMusic()
        super().closeEvent(event)


class _WorthyKeyFilter(QObject):
    """Key sequence gate for the worthy dialog. Opaque on purpose."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = dialog
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
                QMessageBox.information(self._dialog.parent() or self._dialog, " ", "Enter")
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
