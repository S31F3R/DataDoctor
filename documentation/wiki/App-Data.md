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
| `user.config` | JSON settings: UTC offset, raw/QAQC/retro/debug, last Quick Look, export path, graph save folder, SQL snippet order, update channel, … |
| `logs/app.log` | Full Python + Qt logs (Log Viewer tab) |
| `quickLook/query/` | Saved query lists (Quick Looks) |
| `quickLook/sql/` | SQL Query Builder snippets |
| `certs/` | Optional user-level Aquarius cert folder (created only if needed) |

Passwords and API keys are **not** in `user.config`. They go to the OS keyring, service name `DataDoctor`:

- `usgsApiKey`
- `oracleUser` / `oraclePassword`
- `aqServer` / `aqUser` / `aqPassword`

## Install / dictionary files

| File | Role |
|------|------|
| `core/bunker.db` | Live data dictionary (Windows: `Project Files\core\bunker.db`) |
| `core/valuePrecision.json` | Aquarius identifier → rounding spec |
| Packaged `temp/bunker.db` | Merge source only — do not replace the live DB with this |

`applyUpdate` merges packaged dictionary rows into the live DB. User Quick Looks in the config folder are left alone.

## Logging

**Log Viewer** on the main window toggles a tab that tails `app.log`. Uncaught exceptions write full tracebacks there. Debug mode (**Options → General**) adds extra `DEBUG` lines.
