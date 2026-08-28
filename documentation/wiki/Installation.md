# Installation

## Prerequisites

- **Python 3.14** (Windows launcher ships embeddable 3.14; from source / Linux / macOS: 3.14 recommended, 3.13 still works)
- From [`requirements.txt`](https://github.com/S31F3R/DataDoctor/blob/main/requirements.txt): PyQt6, requests, oracledb, keyring, matplotlib, numpy, pygame-ce
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
updates\                (includes a DataDoctor-Python-*.zip for first run)
pythonFiles\
  app.pyw        (DataDoctor.py renamed — launcher always starts this name)
  python-embed\  (official Windows embeddable Python 3.14 — no system Python)
  core\          (live bunker.db stays here)
  ui\
  quickLook\
  oracle\
  certs\         (empty; drop aquarius.pem / .cer here)
  scripts\
  temp\bunker.db (packaged dictionary for merge only)
```

1. Unzip to a writable folder.
2. Double-click **Data Doctor.exe**. If `updates\` has a zip, the launcher starts **applyUpdate.cmd** and exits (so the `.exe` can be replaced). applyUpdate pip-installs into `python-embed` (needs internet the first time), merges the dictionary, then starts **Data Doctor.exe** again, which then opens `app.pyw`.
3. Or run **applyUpdate.cmd** yourself — it starts the exe when it finishes.

No system Python and no `.venv`. `python-embed` is the interpreter. If the window never appears, check:

- `%LOCALAPPDATA%\Data Doctor\logs\app.log` (launcher, applyUpdate, and Python startup lines)
- `%LOCALAPPDATA%\Data Doctor\logs\fault.log` (native crash dump)
- `pythonFiles\startup-error.log` (import failure next to the app; pythonw has no console)

A rebuilt `Data Doctor.exe` also waits a few seconds and pops a message if `pythonw` dies immediately.

Coming from a **3.0.x** install that used system Python + `Project Files\.venv`: do **not** drop only the Python zip. Use `DataDoctor-Windows-*.zip` (see [Updates and Releases](Updates-and-Releases)).

Do **not** overwrite `pythonFiles\core\bunker.db` with a zip’s copy if the dictionary has local edits. Updates merge via `applyUpdate.cmd`. A 3.0.x `Project Files\core\bunker.db` is migrated on the Windows-zip hop.

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
2. Double-click **Data Doctor.command** (needs Python 3.14 or 3.13 and a venv or system env with requirements). Live app is `pythonFiles/DataDoctor.py`. If `updates/` has a zip, the command runs `applyUpdate.sh` then applyUpdate starts the command again.

A portable zip can be built with `python scripts/packageMac.py`. A native `.app` requires `python scripts/packageMac.py --app` on macOS with PyInstaller.

## Oracle Instant Client

Packaged Windows / Linux / macOS trees may include Instant Client **Basic Lite** (raw library files, no extra Oracle installer) under `oracle/client` (Windows: `pythonFiles\oracle\client`). **That packaged client is always used when it is present** — a system Oracle install is only a fallback if the package has no client.

`tnsnames.ora` and `sqlnet.ora` are read from the **same folder**:

1. `TNS_ADMIN` environment variable, if set
2. Else **Options → Oracle → TNS Names Location** (defaults to packaged `oracle/network/admin`)

The package ships `sqlnet.ora` in `oracle/network/admin` (Windows: `pythonFiles\oracle\network\admin`). It does **not** ship `tnsnames.ora`. Copy yours into that folder (or point `TNS_ADMIN` at a folder that already has both files). Instant Client will not look under `oracle/client/network/admin`.

The Python update zip does not include Instant Client (it is OS-specific).

## Next

- [Updates and Releases](Updates-and-Releases)
- [App Data](App-Data)
- **Options**: USGS key, HDB login, and/or Aquarius server as needed
