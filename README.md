# Data Doctor

A desktop tool for querying, reviewing, and (on Reclamation HDB) editing hydrologic time series from:

- **USGS** Water Data for the Nation (OGC API + legacy NWIS)
- **USBR** Hydrologic Database (HDB / Oracle)
- **Aquarius** Time-Series

Built for Reclamation and USGS workflows: data dictionary labels, QAQC coloring, overlay/delta pairs, graphing, CSV export, and saved Quick Looks.

Current version: **3.0.0** (see `core/Version.py`).

[Wiki](https://github.com/S31F3R/DataDoctor/wiki) · [Releases](https://github.com/S31F3R/DataDoctor/releases) · [Issues](https://github.com/S31F3R/DataDoctor/issues)

---

## Requirements

- **Python 3.13.x** (tested with 3.13.7)
- Dependencies in [`requirements.txt`](requirements.txt): PyQt6, requests, oracledb, keyring, matplotlib, numpy, pygame
- **USBR / HDB**: Oracle Instant Client (packaged with Windows/AppImage when present) plus TNS / `tnsnames.ora`
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

- Needs Python 3.13 on PATH (an installer may be included in the zip)
- Live app lives under `Project Files\` (`DataDoctor.pyw`)
- Updates: drop `DataDoctor-Python-*.zip` in `Update\` and run `applyUpdate.cmd`

### Linux (AppImage)

Download `DataDoctor-x86_64.AppImage` (or the matching arch), mark executable, run it.

Build on the same arch/glibc you intend to ship:

```bash
python scripts/packageAppImage.py
```

### macOS

Unzip the macOS package and double-click `Data Doctor.command` (needs Python 3.13). Optional native `.app` via `python scripts/packageMac.py --app` on a Mac.

More detail: [Installation](https://github.com/S31F3R/DataDoctor/wiki/Installation) and [Updates and Releases](https://github.com/S31F3R/DataDoctor/wiki/Updates-and-Releases).

---

## First-run setup

Open **Options** and set the sources that apply:

| Tab | What to set |
|-----|-------------|
| General | Raw data, QAQC, retro font, debug, **Beta updates** |
| USGS | API key (optional, stored in the OS keyring) |
| USBR | Oracle user / password; TNS names path if needed |
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

- Launcher / Python payload: `DataDoctor-Python.zip` (or `*python*.zip`)
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
