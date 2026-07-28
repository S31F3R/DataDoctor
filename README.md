# DataDoctor

Tested with Python 3.13.7

To install dependancies run in project terminal
pip install -r requirements.txt


To build on Windows: pyinstaller --noconsole --noupx --onedir --add-data "ui;ui" --add-data "quickLook;quickLook" --add-data "core;core" --add-data "oracle;oracle" --add-data "documentation;documentation" --icon=ui/icons/DataDoctor.ico --distpath "dist/Windows" --workpath "build/Windows" --name DataDoctor DataDoctor.py

## Aquarius TLS certificates

Place the server cert in a `certs/` folder as one of:

- `aquarius.pem` (preferred)
- `.cer` / `.crt` (auto-converted to `aquarius.pem` on first use)
- `.pfx` / `.p12` (converted via OpenSSL if on PATH, or the `cryptography` package; optional password in keyring key `DataDoctor` / `aqCertPassword`)

Search locations (first hit wins): project `certs/`, app root, parent of app root (Windows zip / launcher folder), current working directory, and the user config `certs/` folder. Converted `aquarius.pem` is written next to the source file when possible.

Or add the cert to your system trust store.

## Packaging / updates

- Windows zip: `python scripts/packageWindows.py` (launcher as zip root, app under `Project Files/`, `DataDoctor.pyw`)
- Merge packaged `bunker.db` into a user DB without wiping user fields: `launcher/updateBunker.py` or `launcher/updateBunker.cmd`