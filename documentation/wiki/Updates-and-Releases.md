# Updates and Releases

Data Doctor checks [GitHub Releases](https://github.com/S31F3R/DataDoctor/releases) at startup. If nothing is published yet, the check is **silent** (no popup). About still shows the version from `core/Version.py` (not from `winAbout.ui`).

## How publishing works

GitHub **Releases** are not a git push of zip files (the wiki *is* a git repo; releases are not). A Release is an API object: a **tag** (`v3.0.0` or `v3.0.0-rc.1`) plus uploaded assets. The in-app updater looks at those tags and asset names.

From this Linux machine you can still publish the same way we published the wiki — one script talks to GitHub with your existing credentials (git PAT, `GITHUB_TOKEN`, or `gh auth`):

```bash
python scripts/publishRelease.py
```

It asks **published / rc / beta**:

| You pick | Version written to `core/Version.py` | GitHub tag | Pre-release? | Who sees the update |
|----------|--------------------------------------|------------|--------------|---------------------|
| published | `3.0.0` (the triple already in Version.py) | `v3.0.0` | no | Stable + Beta |
| rc | `3.0.0-rc.1` (asks for N) | `v3.0.0-rc.1` | yes | Beta channel only |
| beta | `3.0.0-beta.1` | `v3.0.0-beta.1` | yes | Beta channel only |

The packaged About window and the GitHub tag **must match**, so the script writes `Version.py` before it builds. Commit that change with the release.

### What this machine can build

| Asset | On this Linux box? | Notes |
|-------|--------------------|--------|
| `DataDoctor-Python-vX.Y.Z.zip` | yes | Update payload. Windows `applyUpdate` looks for `*python*.zip`. |
| `DataDoctor-Windows-vX.Y.Z.zip` | yes | First install. Uses the already-built `launcher/Data Doctor.exe`. **Always `--skip-venv` here** — a Linux `.venv` will not run on Windows. |
| `DataDoctor-x86_64-vX.Y.Z.AppImage` | yes | This CPU/glibc only. Needs PyInstaller. |
| `DataDoctor-macOS-vX.Y.Z.zip` | yes | Portable `Data Doctor.command` + Project Files, `--skip-venv`. |
| native `.app` | **no** | `python scripts/packageMac.py --app` **on a Mac**. |
| other-arch AppImage | **no** | Build on that arch. |
| rebuild `Data Doctor.exe` | **no** | VB.NET launcher already lives under `launcher/`. You do **not** need a Windows box to zip a Windows install. |

You do **not** need to run `packageWindows` on Windows or `packageMac` on a Mac for the zip flavors. You **do** need a Mac only if you want a double-click `.app`.

`--build-only` writes `dist/` and stops. `--upload` creates the GitHub Release and attaches the files. `--dry-run` prints the plan.

```bash
python scripts/publishRelease.py --channel rc --number 1 --dry-run
python scripts/publishRelease.py --channel published --build-only --skip-appimage
python scripts/publishRelease.py --channel published --upload --yes
```

## Channels

| Channel | What you get |
|---------|----------------|
| **Stable** (default) | Latest non–pre-release tag |
| **Beta** | Includes GitHub **Pre-release** tags and `-rc` / `-beta` versions |

Toggle **Options → General → Beta updates**. The choice is saved as `updateChannel` in `user.config`.

## Asset names

Publish these on the GitHub Release (names are matched loosely):

| Kind | Asset |
|------|--------|
| Python / launcher payload | `DataDoctor-Python.zip` (or any `*python*.zip`) |
| Linux | `DataDoctor-x86_64.AppImage` (or a zip that contains the AppImage) |

Tags: `vMAJOR.MINOR.PATCH` or `vX.Y.Z-rc.N`. Mark betas/RCs as **Pre-release** so stable users skip them.

## Apply on Windows (launcher)

1. Close Data Doctor.
2. Put `DataDoctor-Python-*.zip` in the install’s `Update\` folder (next to `Data Doctor.exe`).
3. Run `applyUpdate.cmd`.

That refreshes `Project Files` code (`DataDoctor.pyw`, `ui/`, `core/*` except the **live** `bunker.db`), merges the packaged dictionary (`Project Files\temp\bunker.db` → live `core\bunker.db`), and runs pip.

Dictionary-only merge:

```text
python "Project Files\scripts\updateBunker.py"
```

The raw Python zip ships `DataDoctor.py`. On Windows (or when a `.pyw` already exists) `applyUpdate` installs it as `DataDoctor.pyw` so you do not end up with both.

`applyUpdate` does **not** touch `user.config`, the OS keyring, or user-added Quick Looks (same-name files are overwritten).

## Apply on AppImage

Download the new AppImage next to the current one (or into `Update/`). Use **Quit and apply** from the update prompt, or `scripts/applyAppImageUpdate.sh`. The AppImage apply path is not wired identically to the launcher yet.

## Apply on macOS

Replace the unzipped tree or re-run the `.command` from the new zip. There is no Windows-style `applyUpdate.cmd` on Mac.

## Dev / unpackaged

Startup still checks GitHub. A download, if you accept it, lands in an `Update/` folder next to the project or install root. You apply it the same way as the matching package type.
