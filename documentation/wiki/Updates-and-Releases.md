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
| Update payload (Windows launcher `applyUpdate`) | `DataDoctor-Python-vX.Y.Z.zip` (any `*python*.zip`) |
| Windows first install | `DataDoctor-Windows-vX.Y.Z.zip` |
| Linux | `DataDoctor-x86_64-vX.Y.Z.AppImage` (or a zip that contains an AppImage) |
| macOS portable | `DataDoctor-macOS-vX.Y.Z.zip` |

Tags use `vMAJOR.MINOR.PATCH`. Release candidates and betas use `vX.Y.Z-rc.N` or `vX.Y.Z-beta.N` and are marked **Pre-release** so stable users skip them.

## Apply on Windows (launcher)

1. Close Data Doctor.
2. Put `DataDoctor-Python-*.zip` in the install’s `Update\` folder (next to `Data Doctor.exe`).
3. Run `applyUpdate.cmd`.

That refreshes `Project Files` code (`DataDoctor.pyw`, `ui/`, `core/*` except the **live** `bunker.db`), merges the packaged dictionary (`Project Files\temp\bunker.db` → live `core\bunker.db`), creates `Project Files\.venv` if missing, and runs pip. `Project Files\certs\` is left alone so Aquarius certificates survive updates.

Dictionary merge updates `datatype` / `siteName` / `database` from the packaged copy. `valuePrecision`, `precisionOverride`, `expectedMin`, `expectedMax`, `cuttoffMin`, `cutoffMax`, and `rateOfChange` fill blanks only and never overwrite a value you already set.

Dictionary-only merge:

```text
python "Project Files\scripts\updateBunker.py"
```

The raw Python zip ships `DataDoctor.py`. On Windows (or when a `.pyw` already exists) `applyUpdate` installs it as `DataDoctor.pyw` so both files are not left side by side.

`applyUpdate` does not touch `user.config`, the OS keyring, or user-added Quick Looks (same-name files are overwritten).

## Apply on AppImage

Download the new AppImage next to the current one (or into `Update/`). Use **Quit and apply** from the update prompt, or `scripts/applyAppImageUpdate.sh`.

## Apply on macOS

Replace the unzipped tree or run `Data Doctor.command` from the new zip.

## From source

A download accepted from the update prompt lands in an `Update/` folder next to the project or install root. Apply it the same way as the matching package type.
