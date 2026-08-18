# Updates and Releases

Data Doctor checks [GitHub Releases](https://github.com/S31F3R/DataDoctor/releases) at startup. If nothing is published yet, the check is **silent** (no popup). About still shows the version from `core/Version.py`.

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
