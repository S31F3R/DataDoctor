# DataDoctor

pip install pyqt6, requests

To build on Windows: PyInstaller --noconsole --onedir --add-data "ui;ui" --add-data "quickLook;quickLook" --add-data "DataDictionary.csv;." --icon=DataDoctor.ico --distpath "dist/Windows" --workpath "builds/Windows" --name DataDoctor DataDoctor.py