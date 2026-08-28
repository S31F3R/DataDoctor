# Data Doctor

A desktop tool for querying, reviewing, and (on Reclamation HDB) editing hydrologic time series from:

- **USGS** Water Data for the Nation (OGC API + legacy NWIS)
- **USBR** Hydrologic Database (HDB / Oracle)
- **Aquarius** Time-Series

Built for Reclamation and USGS workflows: data dictionary labels, QAQC coloring, overlay/delta pairs, graphing, CSV export, and saved Quick Looks.

Current version: **3.0.1** (see `core/Version.py`). Next Windows builds ship Python 3.14 embeddable.

[Wiki](https://github.com/S31F3R/DataDoctor/wiki) · [Releases](https://github.com/S31F3R/DataDoctor/releases) · [Issues](https://github.com/S31F3R/DataDoctor/issues)

---

## Requirements

- **Python 3.14** (Windows launcher ships embeddable 3.14; from source / Linux / macOS: 3.14 recommended, 3.13 still works)
- Dependencies in [`requirements.txt`](requirements.txt): PyQt6, requests, oracledb, keyring, matplotlib, numpy, pygame-ce
- **USBR / HDB**: packaged Oracle Instant Client (when present) plus TNS / `tnsnames.ora`. The client in the package is used whenever it is there. `tnsnames.ora` and `sqlnet.ora` come from `TNS_ADMIN` if that env var is set, otherwise from packaged `oracle/network/admin/` (we do not ship `tnsnames.ora` — copy yours there).
- **Aquarius** (TLS): a server certificate in a `certs/` folder — see [Aquarius](https://github.com/S31F3R/DataDoctor/wiki/Aquarius)
- **USGS** (optional): an [api.data.gov](https://api.waterdata.usgs.gov/signup/) key for higher rate limits — see [USGS](https://github.com/S31F3R/DataDoctor/wiki/USGS)

---

## Install

### From source (any platform)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python DataDoctor.py
```

### Windows (launcher zip)

Unzip a **Windows** package and double-click `Data Doctor.exe`.

- No system Python. The zip ships Python 3.14 under `Project Files\python-embed\`
- First run: `Data Doctor.exe` applies the Python zip in `Update\` (pip into python-embed), or run `applyUpdate.cmd` yourself
- Live app lives under `Project Files\` (`DataDoctor.pyw`)
- Later code updates: drop `DataDoctor-Python-*.zip` in `Update\` and restart (or run `applyUpdate.cmd`)
- Coming from 3.0.x (system Python / `.venv`): use `DataDoctor-Windows-*.zip`, close Data Doctor, then run `applyUpdate.cmd` so the launcher can be replaced

### Linux (AppImage)

Download `DataDoctor-x86_64.AppImage` (or the matching arch), mark executable, run it.

Build on the same arch/glibc you intend to ship:

```bash
python scripts/packageAppImage.py
```

### macOS

Unzip the macOS package and double-click `Data Doctor.command` (needs Python 3.14, or 3.13). Optional native `.app` via `python scripts/packageMac.py --app` on a Mac.

More detail: [Installation](https://github.com/S31F3R/DataDoctor/wiki/Installation) and [Updates and Releases](https://github.com/S31F3R/DataDoctor/wiki/Updates-and-Releases).

---

## First-run setup

Open **Options** (left categories, General tab on each) and set the sources that apply:

| Category | What to set |
|----------|-------------|
| General | Debug, **Beta updates**, profile export/import |
| Appearance | Retro mode, color theme (System / Light / Dark) |
| Oracle | TNS names path, user / password; Databases access list |
| USGS | API key (optional, stored in the OS keyring) |
| USBR | Hour timestamp method (BOP/EOP), overwrite flag |
| Aquarius | Server URL, user, password |

Credentials are stored in the OS keyring (`DataDoctor` service), not in `user.config`.

---

## What lives where

Config and logs are **per user**, not inside the install folder.

| Platform | Config directory |
|----------|------------------|
| Linux | `~/.config/Data Doctor/` |
| Windows | `%LOCALAPPDATA%\Data Doctor\` |
| macOS | `~/Library/Application Support/Data Doctor/` |

Inside that folder: `user.config`, `logs/app.log`, `quickLook/query/`, `quickLook/sql/`.

The live data dictionary is `core/bunker.db` next to the app (Windows: `Project Files\core\bunker.db`). Do not overwrite it with a packaged copy if the dictionary has local edits — `applyUpdate` merges.

See [App Data](https://github.com/S31F3R/DataDoctor/wiki/App-Data).

---

## Aquarius TLS certificates

Create a `certs/` folder (the app never creates one) and place the server cert as one of:

- `aquarius.pem` (preferred)
- `.cer` / `.crt` (converted to `aquarius.pem` on first use; source file removed after success)

`.pfx` / `.p12` are not supported — export as `.cer` or `.pem` first.

Search locations (existing folders only): project `certs/`, app root, parent of app root (Windows zip / launcher folder), current working directory, and the user-config `certs/` folder.

---

## Packaging (developers)

From the project root:

| Script | Output |
|--------|--------|
| `python scripts/publishRelease.py` | Prompts published / rc / beta, builds host-supported assets, optional GitHub upload |
| `python scripts/packageWindows.py` | Windows launcher zip (`DataDoctor.pyw` under `Project Files/`) |
| `python scripts/packagePython.py` | `DataDoctor-Python.zip` (update payload / raw Python) |
| `python scripts/packageAppImage.py` | `dist/DataDoctor-<arch>-YYYYMMDD.AppImage` |
| `python scripts/packageMac.py` | macOS zip (`Data Doctor.command`) |

GitHub Release asset names:

- Code update: `DataDoctor-Python-vX.Y.Z.zip` (already on python-embed)
- Windows first install / 3.0.x hop: `DataDoctor-Windows-vX.Y.Z.zip`
- AppImage: `DataDoctor-x86_64.AppImage`
- Tags: `vMAJOR.MINOR.PATCH` or `vX.Y.Z-rc.N` (check **Pre-release** for betas)

---

## Useful links

- [USGS Water Data API docs](https://api.waterdata.usgs.gov/docs/ogcapi/)
- [Request a USGS / api.data.gov key](https://api.waterdata.usgs.gov/signup/)
- [USGS National Water Dashboard](https://dashboard.waterdata.usgs.gov/app/nwd/en/)
- [Reclamation](https://www.usbr.gov/)

---

## License

[GPL-3.0](LICENSE)
