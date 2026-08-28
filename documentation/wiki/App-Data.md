# App Data

Application name is **Data Doctor** (no organization folder). Config is **per user**, not inside the install tree.

## Config directory

| Platform | Path |
|----------|------|
| Linux | `~/.config/Data Doctor/` |
| Windows | `%LOCALAPPDATA%\Data Doctor\` |
| macOS | `~/Library/Application Support/Data Doctor/` |

| Item | Purpose |
|------|---------|
| `user.config` | JSON settings: UTC offset, raw/QAQC/retro/debug, last Quick Look, export path, graph save folder, SQL snippet order/categories, update channel, Oracle access list, … |
| `logs/app.log` | Current Python + Qt log (Log Viewer tab) |
| `logs/app.log.1` … `.5` | Rotated backups (~1 MB each, newest `.1`) |
| `logs/fault.log` | Native interpreter faults (not held open on `app.log`) |
| `quickLook/query/` | Saved query lists (Quick Looks) |
| `quickLook/sql/` | SQL Query Builder snippets (category assignment in `user.config`) |
| `certs/` | Optional user-level Aquarius cert folder (created only if needed) |

Passwords and API keys are **not** in `user.config`. They go to the OS keyring, service name `DataDoctor`:

- `usgsApiKey`
- `oracleUser` / `oraclePassword`
- `aqServer` / `aqUser` / `aqPassword`

## Install / dictionary files

| File | Role |
|------|------|
| `core/bunker.db` | Live data dictionary (Windows: `pythonFiles\core\bunker.db`) |
| `core/valuePrecision.json` | Aquarius identifier → rounding spec |
| Packaged `temp/bunker.db` | Merge source only — do not replace the live DB with this |

`applyUpdate` merges packaged dictionary rows into the live DB. User Quick Looks in the config folder are left alone.

## Logging

**Log Viewer** on the main window toggles a tab that loads `app.log` plus `app.log.1`…`app.log.5` (newest first) and live-appends while the tab is open. Closing and reopening reloads every rotation from disk. Uncaught exceptions write full tracebacks there. Debug mode (**Options → General**) adds extra `DEBUG` lines.
