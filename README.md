# DataDoctor

Tested with Python 3.13.7

To install dependancies run in project terminal
pip install -r requirements.txt


To build on Windows: PyInstaller --noconsole --onedir --add-data "ui;ui" --add-data "quickLook;quickLook" --add-data "DataDictionary.csv;." --icon=DataDoctor.ico --distpath "dist/Windows" --workpath "build/Windows" --name DataDoctor DataDoctor.py