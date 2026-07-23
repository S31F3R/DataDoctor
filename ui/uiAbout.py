# uiAbout.py

from PyQt6.QtWidgets import QDialog, QLabel, QTextBrowser, QPushButton
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QPixmap, QFont, QFontDatabase, QIcon
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6 import uic
from core import Logic, Utils

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
        fontPath = Logic.resourcePath('ui/fonts/PressStart2P-Regular.ttf')
        fontId = QFontDatabase.addApplicationFont(fontPath)
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0] if fontId != -1 else "Courier"
        retroFontObj = QFont(fontFamily, 10)
        retroFontObj.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.textInfo.setFont(retroFontObj)
        
        infoList = [
            ('Version', '3.0.0'),
            ('GitHub', 'https://github.com/S31F3R/DataDoctor'),
            ('Author', 'S31F3R'),
            ('License', 'GPL-3.0'),
            ('Music', 'By Eric Matyas at www.soundimage.org')
        ]

        htmlContent = '<html><body style="color: white; font-family: \'' + fontFamily + '\'; font-size: 10pt; padding-left: 50px; white-space: nowrap; line-height: 2.0;">'

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
        self._setupSecretButton()
        # QMediaPlayer (music role) instead of QSoundEffect (event role): better for a
        # long looping track, and avoids PipeWire/Pulse muting "event" streams on Linux.
        # Same Qt6 APIs on Windows/macOS/Linux — keep audioOutput alive on self.
        self.mediaPlayer = None
        self.audioOutput = None
        self._setupMusic()

    def _setupMusic(self):
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
            self.mediaPlayer.errorOccurred.connect(self._onMusicError)
        except Exception as e:
            self.mediaPlayer = None
            self.audioOutput = None
            Logic.logMessage("WARN", f"Failed to load about music: {e}")

    def _onMusicError(self, error, errorString):
        Logic.logMessage("WARN", f"About music error: {error} {errorString}")

    def _startMusic(self):
        if not self.mediaPlayer:
            return
        # Restart cleanly when the dialog is reopened
        self.mediaPlayer.setPosition(0)
        self.mediaPlayer.play()

    def _stopMusic(self):
        if self.mediaPlayer:
            self.mediaPlayer.stop()

    def _setupSecretButton(self):
        """
        Tiny easter-egg control — The Net (1995) π backdoor icon, bottom-right
        (same corner as the movie). Hook action up later.
        """
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
        iconPath = Logic.resourcePath('ui/icons/Secret.png')
        icon = QIcon(iconPath)
        self.buttonSecret.setIcon(icon)
        # Movie pi is small and quiet in the corner
        self.buttonSecret.setIconSize(QSize(16, 16))
        # No-op for now — wire secret behavior when you're ready
        self.buttonSecret.clicked.connect(self.buttonSecretPressed)

    def buttonSecretPressed(self):
        """Placeholder for the secret action (attach later)."""
        if hasattr(Logic, 'logMessage'):
            Logic.logMessage("DEBUG", "buttonSecretPressed: secret button clicked (no action wired yet)")
    
    def showEvent(self, event):        
        Logic.logMessage("WARN", f"uiAbout showEvent")
        Utils.centerWindowToParent(self)
        self._startMusic()
        super().showEvent(event)
    
    def closeEvent(self, event):
        self._stopMusic()
        super().closeEvent(event)