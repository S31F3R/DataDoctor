# DataDoctor

Tested with Python 3.13.7

To install dependancies run in project terminal
pip install -r requirements.txt


To build on Windows: pyinstaller --noconsole --noupx --onedir --add-data "ui;ui" --add-data "quickLook;quickLook" --add-data "core;core" --add-data "oracle;oracle" --add-data "documentation;documentation" --icon=DataDoctor.ico --distpath "dist/Windows" --workpath "build/Windows" --name DataDoctor DataDoctor.py

For secure AQUARIUS queries, place the server’s certificate as 'certs/aquarius.pem' or add it to your system trust store