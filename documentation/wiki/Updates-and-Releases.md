# Updates and Releases

Data Doctor checks [GitHub Releases](https://github.com/S31F3R/DataDoctor/releases) at startup. If nothing is published yet, the check is silent (no popup). The About window shows the installed version.

## Channels

| Channel | What is offered |
|---------|-----------------|
| **Stable** (default) | Latest full release (`v3.0.0`) |
| **Beta** | Includes GitHub **Pre-release** tags (`-rc` and `-beta`) |

Newest-first among those: **published > rc > beta** of the same `X.Y.Z`. Example: `3.0.0` is newer than `3.0.0-rc.2.1`, which is newer than `3.0.0-rc.1`, which is newer than `3.0.0-beta.4`. A `3.0.0` install will not be offered `3.0.0-rc.1` (that RC is older than 3.0.0).

Toggle **Options → General → Beta updates**. The choice is saved as `updateChannel` in `user.config`. Saving with the box **checked** runs an update check (including pre-releases). Saving with it **unchecked** offers the latest published (non-RC / non-beta) release so you can leave the beta channel.

## Release assets

Typical files on a GitHub Release:

| Kind | Asset name |
|------|------------|
| Code update (already on `python-embed`) | `DataDoctor-Python-vX.Y.Z.zip` (any `*python*.zip`) |
| Windows first install **and** 3.0.x → 3.1+ launcher hop | `DataDoctor-Windows-vX.Y.Z.zip` |
| Linux | `DataDoctor-x86_64-vX.Y.Z.AppImage` (or a zip that contains an AppImage) |
| macOS portable | `DataDoctor-macOS-vX.Y.Z.zip` |

Tags use `vMAJOR.MINOR.PATCH`. Release candidates and betas use `vX.Y.Z-rc.N` or `vX.Y.Z-beta.N` and are marked **Pre-release** so stable users skip them.

## Apply on Windows (launcher)

### Already on bundled Python 3.14 (`pythonFiles\python-embed\`)

1. Close Data Doctor (or leave it closed).
2. Put `DataDoctor-Python-*.zip` in the install’s `Update\` folder (next to `Data Doctor.exe`).
3. Run `applyUpdate.cmd`, or restart **Data Doctor.exe** (it applies zips in `Update\` first).

That refreshes `pythonFiles` code (`app.pyw`, `ui/`, `core/*` except the **live** `bunker.db`), merges the packaged dictionary, pip-installs into `python-embed`, and deletes the zip. `pythonFiles\certs\` is left alone so Aquarius certificates survive updates.

### Coming from 3.0.x (system Python + `.venv`)

The old zip needed Python on PATH. 3.1+ ships Python 3.14 next to the app and a launcher that starts `python-embed\pythonw.exe`.

In-app update on this hop downloads **`DataDoctor-Windows-*.zip`**, not the Python zip, and tells you to close the app.

1. Close Data Doctor completely (the running `.exe` cannot replace itself).
2. Confirm `DataDoctor-Windows-*.zip` is in `Update\` (download it from the update prompt if it is not there yet).
3. Double-click `applyUpdate.cmd`.

That replaces `Data Doctor.exe` / `applyUpdate.cmd`, installs `pythonFiles\python-embed\` and `pythonFiles\app.pyw`, merges `bunker.db` (including from a leftover `Project Files\core\bunker.db`), and pip-installs. Do **not** use only the Python zip for this hop — old `applyUpdate` cannot install the launcher or the embed.

If you already applied a 3.1 Python zip (new code, still on `.venv`), the app will prompt for the Windows zip on the next start.

Dictionary merge updates `datatype` / `siteName` / `database` from the packaged copy. `valuePrecision`, `precisionOverride`, `expectedMin`, `expectedMax`, `cuttoffMin`, `cutoffMax`, and `rateOfChange` fill blanks only and never overwrite a value you already set.

Dictionary-only merge:

```text
"pythonFiles\python-embed\python.exe" "pythonFiles\scripts\updateBunker.py"
```

The raw Python zip ships `DataDoctor.py`. On Windows `applyUpdate` installs it as `pythonFiles\app.pyw` (the generic launcher always starts that name).

`applyUpdate` does not touch `user.config`, the OS keyring, or user-added Quick Looks (same-name files are overwritten).

## Apply on AppImage

Download the new AppImage next to the current one (or into `Update/`). Use **Quit and apply** from the update prompt, or `scripts/applyAppImageUpdate.sh`.

## Apply on macOS

Replace the unzipped tree or run `Data Doctor.command` from the new zip.

## From source

A download accepted from the update prompt lands in an `Update/` folder next to the project or install root. Apply it the same way as the matching package type.
