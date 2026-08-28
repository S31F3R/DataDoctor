# USBR HDB

Internal queries talk to Reclamation Hydrologic Databases over **Oracle** (`oracledb`). Set **Options → Oracle** user and password (OS keyring). Hourly BOP/EOP and the overwrite flag are under **Options → USBR**.

The packaged Instant Client is used whenever it is in the install (`oracle/client` or `pythonFiles\oracle\client` on Windows). TNS names and `sqlnet.ora` come from one folder: `TNS_ADMIN` if that env var is set, otherwise **Options → Oracle → TNS Names Location** (default packaged `oracle/network/admin`). `tnsnames.ora` is not shipped — copy yours into that folder. Both files must live together.

**Options → Oracle → Access List** is which HDBs you actually use. Unchecked names drop out of Internal Query and SQL Query Builder. Public Query still shows every database. A wrong password on one HDB pauses **that** database for five minutes (or until you save new credentials) so the others stay usable.

Regional / office DSN names:

| DSN | Office |
|-----|--------|
| `lchdb` | Lower Colorado Regional Office |
| `uchdb2` | Upper Colorado Regional Office |
| `yaohdb` | Yuma Area Office |
| `ecohdb` | Eastern Colorado Area Office |
| `lbohdb` | Lahontan Basin Area Office |
| `kbohdb` | Klamath Basin Area Office |
| `pnhyd` | Pacific Northwest Regional Office |
| `gphyd` | Great Plains Regional Office |

DataIDs are **site datatype IDs (SDID)**. A model-run suffix is allowed: `SDID-MRID`. When MRID is `0` or omitted, the header second line is just the SDID.

## BOP and EOP

Hourly HDB values are **period** values. Data Doctor needs to know whether the timestamp you see is the **beginning** or **end** of that hour.

| Setting | Meaning | Hourly write window |
|---------|---------|---------------------|
| **EOP** (end of period) | Display time is the *end* of the hour | START = display − 1h, END = display |
| **BOP** (beginning of period) | Display time is the *start* of the hour | START = display, END = display + 1h |

This is **Options → USBR → HOUR Timestamp Method** (`hourTimestampMethod` in `user.config`). It affects both how hourly data is interpreted and how `MODIFY_R_BASE` / `DELETE_R_BASE` are called on upload.

Daily / instant series do not use that hour window the same way.

## Uploads

Internal Data Query only. Edited cells (magenta) and overlay auto-fills can be sent with the upload button.

- `MODIFY_R_BASE` for values
- `DELETE_R_BASE` for blanks (Delete key can clear a multi-cell selection)
- Overlay secondary-only fills are flagged automatically; changing the cell yourself clears the auto flag
- **Options → USBR → Overwrite Flag** sets `MODIFY_R_BASE` `OVERWRITE_FLAG` to `O` when checked, or NULL when off. Existing HDB values are only replaced when that box is checked. Freehand SQL in the Query Builder does not get this flag — it is for the upload write path.

## Password change

**Options → USBR** can change the Oracle password across HDBs. The summary popup lists successes, locked accounts, and skipped DBs. Missing users and TNS/network noise stay in `app.log`, not the popup. **Skip** on a per-DB wrong-password prompt continues the rest of the queue.

## Database links

**Internal SQL only:** **UCHDB2 / LCHDB / YAOHDB** share database links. A mixed query among those three may use `SCHEMA.r_base@dsn` (e.g. `LCHDBA.r_base@lchdb`) from the first of them. If that link fails, Data Doctor retries by connecting to the target DSN **directly** and querying unqualified `r_base` / `r_hour`.

**KBOHDB, CUHDB, LBOHDB, and ECOHDB** (internal) each get their own worker and a **direct** connection: `FROM r_base`, never `@kbohdb`. Public USBR web queries stay a single USBR group (HTTP API, no Oracle links).

## Public USBR web (not HDB)

Public USBR series (when offered in the database list) use the Reclamation web API, not an Oracle login. That path is read-only.

| Parameter | Meaning |
|-----------|---------|
| `svr` | HDB name (`lchdb`, `uchdb2`, …) |
| `sdi` | Site datatype ID; multiple IDs may be comma-separated |
| `tstp` | `IN` instant, `HR` hourly, `DY` daily, `MN` monthly |
| `t1` / `t2` | Start and end. Dates: `MM-DD-YYYY` or `YYYY-MM-DDTHH:mm`. Integers are a timestep offset from today (`t1=-7`, `t2=0` on daily = last 7 days). |

Reclamation: https://www.usbr.gov/
