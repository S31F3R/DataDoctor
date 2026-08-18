# USBR HDB

Internal queries talk to Reclamation Hydrologic Databases over **Oracle** (`oracledb`). Set **Options → USBR** user and password (OS keyring). Point at `tnsnames.ora` if needed.

Regional / office DSN names you will see (examples): `lchdb`, `uchdb2`, `yaohdb`, `ecohdb`, `lbohdb`, `kbohdb`, `pnhyd`, `gphyd`.

DataIDs are **site datatype IDs (SDID)**. A model-run suffix is allowed: `SDID-MRID`. When MRID is `0` or omitted, the header second line is just the SDID.

## BOP and EOP

Hourly HDB values are **period** values. Data Doctor needs to know whether the timestamp you see is the **beginning** or **end** of that hour.

| Setting | Meaning | Hourly write window |
|---------|---------|---------------------|
| **EOP** (end of period) | Display time is the *end* of the hour | START = display − 1h, END = display |
| **BOP** (beginning of period) | Display time is the *start* of the hour | START = display, END = display + 1h |

This is **Options → USBR → timestamp method** (`hourTimestampMethod` in `user.config`). It affects both how hourly data is interpreted and how `MODIFY_R_BASE` / `DELETE_R_BASE` are called on upload.

Daily / instant series do not use that hour window the same way.

## Uploads

Internal Data Query only. Edited cells (magenta) and overlay auto-fills can be sent with the upload button.

- `MODIFY_R_BASE` for values
- `DELETE_R_BASE` for blanks (Delete key can clear a multi-cell selection)
- Overlay secondary-only fills are flagged automatically; changing the cell yourself clears the auto flag

## Password change

**Options → USBR** can change the Oracle password across HDBs. The summary popup lists successes, locked accounts, and skipped DBs. Missing users and TNS/network noise stay in `app.log`, not the popup. **Skip** on a per-DB wrong-password prompt continues the rest of the queue.

## Database links

A multi-DB internal query may use `@link` from the primary. If the link fails (`ORA-02019` and similar), Data Doctor retries by connecting to the target DSN **directly**.

## Public USBR web (not HDB)

Public USBR series (when offered in the database list) use the Reclamation web API, not your Oracle login. Parameters look like `svr`, `sdi`, `tstp` (`IN`/`HR`/`DY`/`MN`), `t1`/`t2`. That path is read-only.

Reclamation: https://www.usbr.gov/
