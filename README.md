# DataDoctor

Tested with Python 3.13.7

To install dependancies run in project terminal
pip install -r requirements.txt


To build on Windows: pyinstaller --noconsole --noupx --onedir --add-data "ui;ui" --add-data "quickLook;quickLook" --add-data "core;core" --add-data "oracle;oracle" --add-data "documentation;documentation" --icon=ui/icons/DataDoctor.ico --distpath "dist/Windows" --workpath "build/Windows" --name DataDoctor DataDoctor.py

## Aquarius TLS certificates

Create a `certs/` folder yourself (the app never creates one) and place the server cert as one of:

- `aquarius.pem` (preferred)
- `.cer` / `.crt` (auto-converted to `aquarius.pem` on first use; source file removed after success)

`.pfx` / `.p12` are not supported — export the cert as `.cer` or `.pem` first.

Search locations (existing folders only): project `certs/`, app root, parent of app root (Windows zip / launcher folder), current working directory, and the user config `certs/` folder. Converted `aquarius.pem` is written next to the source file. If conversion fails, the app falls back to system trust (then unverified) rather than using a stale pem.

Or add the cert to your system trust store.

## Packaging / updates

- Windows zip: `python scripts/packageWindows.py` (launcher as zip root, app under `Project Files/`, `DataDoctor.pyw`)
  - Generates `README.txt` and `UPDATE.txt` each run
  - Packaged dictionary for merge: `Project Files/temp/bunker.db`
  - Live user dictionary: `Project Files/core/bunker.db`
- Merge: `updateBunker.cmd` → `Project Files/scripts/updateBunker.py` (then removes `temp/`)