from PyQt6.QtWidgets import QDialog, QLabel, QTextBrowser
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QPixmap, QFont, QFontDatabase, QIcon
from PyQt6.QtMultimedia import QSoundEffect
from PyQt6 import uic
from core import Logic, Config, Utils
import os

class uiAbout(QDialog):
    """About dialog: Retro PNG bg with transparent info overlay and looping sound."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winAbout.ui'), self)
        self.winMain = winMain

        # Define controls
        self.backgroundLabel = self.findChild(QLabel, 'backgroundLabel')
        self.textInfo = self.findChild(QTextBrowser, 'textInfo')
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
        self.soundEffect = None

        try:
            wavPath = Logic.resourcePath('ui/sounds/8-Bit-Perplexion.wav')
            self.soundEffect = QSoundEffect(self)
            self.soundEffect.setSource(QUrl.fromLocalFile(wavPath))
            self.soundEffect.setLoopCount(QSoundEffect.Infinite)
            self.soundEffect.setVolume(0.8)
        except Exception as e:
            if Config.debug:
                print(f"[ERROR] Failed to load sound effect: {e}")
    
    def showEvent(self, event):
        if Config.debug:
            print(f"[DEBUG] uiAbout showEvent")
        Utils.centerWindowToParent(self)     
        
        if self.soundEffect:
            self.soundEffect.play()
        super().showEvent(event)
    
    def closeEvent(self, event):
        if self.soundEffect:
            self.soundEffect.stop()
        super().closeEvent(event)