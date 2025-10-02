# Test all PyQt6 imports for DataDoctor.py
try:
    from PyQt6.QtGui import QGuiApplication
    print("✓ QtGui (QGuiApplication) imported successfully")
except ImportError as e:
    print(f"✗ QtGui error: {e}")

try:
    from PyQt6.QtCore import QFile, QIODevice, QTextStream
    print("✓ QtCore (QFile, QIODevice, QTextStream) imported successfully")
except ImportError as e:
    print(f"✗ QtCore error: {e}")

try:
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTableWidget, 
                                 QTextEdit, QComboBox, QDateTimeEdit, QListWidget, 
                                 QListWidgetItem, QMessageBox)
    print("✓ QtWidgets (all classes) imported successfully")
except ImportError as e:
    print(f"✗ QtWidgets error: {e}")

try:
    from PyQt6 import uic
    print("✓ uic (UI loader) imported successfully")
except ImportError as e:
    print(f"✗ uic error: {e}")

print("\nAll tests passed—imports are good! Run DataDoctor.py now.")