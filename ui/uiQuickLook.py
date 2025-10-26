import os
from PyQt6.QtWidgets import QDialog, QLineEdit, QPushButton, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6 import uic
from core import Logic, Utils, Config

class uiQuickLook(QDialog):
    """Quick look save dialog: Names and stores query presets."""
    def __init__(self, winMain=None):
        super().__init__(parent=winMain)
        uic.loadUi(Logic.resourcePath('ui/winQuickLook.ui'), self)
        self.winMain = winMain
        self.currentListQueryList = None
        self.CurrentCbQuickLook = None

        # Define controls
        self.btnSave = self.findChild(QPushButton, 'btnSave')
        self.btnCancel = self.findChild(QPushButton, 'btnCancel')
        self.qleQuickLookName = self.findChild(QLineEdit, 'qleQuickLookName')

        # Create events
        self.btnSave.clicked.connect(self.btnSavePressed)
        self.btnCancel.clicked.connect(self.btnCancelPressed)

        if Config.debug:
            print("[DEBUG] uiQuickLook initialized with QLineEdit qleQuickLookName")

    def showEvent(self, event):
        Utils.centerWindowToParent(self)
        super().showEvent(event)

    def btnSavePressed(self):
        if not self.currentListQueryList or not self.CurrentCbQuickLook:
            if Config.debug:
                print("[DEBUG] btnSavePressed: No query list or combo box set")
            return
        quickLookName = self.qleQuickLookName.text().strip()

        if not quickLookName:
            if Config.debug:
                print("[DEBUG] btnSavePressed: Empty Quick Look name, showing warning")
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid Quick Look name.")
            return
        quickLookPath = os.path.join(Utils.getQuickLookDir(), f"{quickLookName}.txt")

        try:
            with open(quickLookPath, 'w', encoding='utf-8') as f:
                for i in range(self.currentListQueryList.count()):
                    f.write(self.currentListQueryList.item(i).text() + '\n')

            # Update combo box
            self.CurrentCbQuickLook.addItem(quickLookName)
            self.CurrentCbQuickLook.setCurrentText(quickLookName)

            if Config.debug:
                print(f"[DEBUG] btnSavePressed: Saved Quick Look to {quickLookPath}, set cbQuickLook to {quickLookName}")
        except Exception as e:
            if Config.debug:
                print(f"[ERROR] btnSavePressed: Failed to save Quick Look: {e}")
            QMessageBox.warning(self, "Save Error", f"Failed to save Quick Look: {e}")
        self.clear()
        self.accept()

    def btnCancelPressed(self):
        self.clear()
        self.reject()

        if Config.debug:
            print("[DEBUG] btnCancelPressed: Cleared qleQuickLookName and closed dialog")

    def clear(self):
        self.qleQuickLookName.clear()

        if Config.debug:
            print("[DEBUG] Cleared qleQuickLookName")