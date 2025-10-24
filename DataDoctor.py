import sys
from PyQt6.QtWidgets import QApplication
from core import Logic
from ui.uiMain import uiMain
from ui.uiQuery import uiQuery
from ui.uiDataDictionary import uiDataDictionary
from ui.uiQuickLook import uiQuickLook
from ui.uiOptions import uiOptions
from ui.uiAbout import uiAbout
from ui.utils import applyStylesAndFonts, loadDataDictionary, loadQuickLooks

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName("Data Doctor")
    
    # Create instances
    winMain = uiMain()
    winQuery = uiQuery(parent=winMain)
    winDataDictionary = uiDataDictionary(parent=winMain)
    winQuickLook = uiQuickLook(parent=winQuery)  # Parent is uiQuery for access to listQueryList
    winOptions = uiOptions(parent=winMain)
    winAbout = uiAbout(parent=winMain)
    
    # Apply styles and fonts
    applyStylesAndFonts(app, winMain.mainTable, winQuery.listQueryList)
    
    # Load data dictionary and quick looks
    loadDataDictionary(winDataDictionary.mainTable)
    loadQuickLooks(winQuery.cbQuickLook)
    
    # Show main window
    winMain.show()
    
    # Start application
    sys.exit(app.exec())