# Installation

## Prerequisites

- **Python 3.13.x** (tested with 3.13.7)
- From [`requirements.txt`](https://github.com/S31F3R/DataDoctor/blob/main/requirements.txt): PyQt6, requests, oracledb, keyring, matplotlib, numpy, pygame
- **USBR queries**: Oracle Instant Client + a working TNS / `tnsnames.ora`
- **Aquarius**: optional TLS certificate (see [Aquarius](Aquarius))
- **USGS**: optional API key (see [USGS](USGS))

## From source

```bash
git clone https://github.com/S31F3R/DataDoctor.git
cd DataDoctor
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python DataDoctor.py
```

If the editor does not pick up `.venv`, select that interpreter (VS Code: **Python: Select Interpreter**).

## Windows (launcher zip)

Typical layout after unzip:

```
Data Doctor.exe
applyUpdate.cmd
README.txt
UPDATE.txt
Update\                 (includes a DataDoctor-Python-*.zip for first run)
Project Files\
  DataDoctor.pyw
  core\          (live bunker.db stays here)
  ui\
  quickLook\
  oracle\
  certs\         (empty; drop aquarius.pem / .cer here)
  scripts\
  temp\bunker.db (packaged dictionary for merge only)
```

1. Unzip to a writable folder.
2. Install Python 3.13 if needed (an installer may be in the zip). Enable **Add python.exe to PATH**.
3. Run **applyUpdate.cmd** once. Linux/mac virtualenvs cannot run on Windows, so the zip does not ship a `.venv`. applyUpdate creates `Project Files\.venv`, installs requirements, and applies the Python payload already in `Update\`.
4. Double-click **Data Doctor.exe**.

Do **not** overwrite `Project Files\core\bunker.db` with a zip’s copy if the dictionary has local edits. Updates merge via `applyUpdate.cmd`.

## Linux AppImage

1. Download `DataDoctor-x86_64.AppImage` (or `aarch64` / the arch you run).
2. `chmod +x DataDoctor-x86_64.AppImage && ./DataDoctor-x86_64.AppImage`

AppImages are host-native. A build from one distro/arch may not run on another glibc or CPU. Rebuild on the target class of machine:

```bash
pip install pyinstaller
python scripts/packageAppImage.py
```

Needs a matching tool under `scripts/appimagetool/` from [appimagetool releases](https://github.com/AppImage/appimagetool/releases).

## macOS

1. Unzip `DataDoctor-macOS-*.zip`.
2. Double-click **Data Doctor.command** (needs Python 3.13 and a venv or system env with requirements).

A portable zip can be built with `python scripts/packageMac.py`. A native `.app` requires `python scripts/packageMac.py --app` on macOS with PyInstaller.

## Oracle Instant Client

Packaged Windows / Linux / macOS trees may include Instant Client **Basic Lite** (raw library files, no extra Oracle installer) under `oracle/client` (or `Project Files\oracle\client`). The app prefers that copy and falls back to a system Instant Client. Set **Options → Oracle** to the `tnsnames.ora` path if TNS names are not in the default location.

The Python update zip does not include Instant Client (it is OS-specific).

## Next

- [Updates and Releases](Updates-and-Releases)
- [App Data](App-Data)
- **Options**: USGS key, HDB login, and/or Aquarius server as needed
