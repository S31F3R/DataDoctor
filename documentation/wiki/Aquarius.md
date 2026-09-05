# Aquarius

Aquarius Time-Series is an optional **internal/public** source. Configure it under **Options → Aquarius**:

- Server URL (`aqServer`)
- User (`aqUser`)
- Password (`aqPassword`)

All three live in the OS keyring, service `DataDoctor`. The server field is the Aquarius host / base URL. Empty server → Aquarius queries fail.

Entra vs credential-account login is not implemented. Username and password are used.

## TLS certificates

Aquarius is **HTTPS** on an internal/VPN network. Verification order:

1. **OS certificate store** (Windows Trusted Root, not the Mozilla `certifi` bundle). If IT already deploys the **issuing CA** with Group Policy, you do **not** need a yearly file on each PC — a new server leaf signed by that CA still verifies.
2. Optional `certs/aquarius.pem` (extra CA). Prefer the **issuing CA**, not the yearly server certificate.
3. If both fail: still connect over HTTPS **without** checking the certificate, and write a **WARN** in the log. USGS (public internet) never uses this fallback.

A `certs/` file is optional. Windows/macOS zips include an empty `pythonFiles/certs/`; updates never replace it.

| File | Behavior |
|------|----------|
| `aquarius.pem` | Extra CA (or leaf) loaded into the OS trust context |
| `.cer` / `.crt` | Converted to `aquarius.pem` on first use; source file removed after success |
| `.pfx` / `.p12` | **Not supported** — export `.cer` or `.pem` first |

Search order (existing folders only): project `certs/`, app root, parent of app root (launcher folder), cwd, user config `certs/` (see [App Data](App-Data)).

The server URL is always `https://` (a stored `http://` host is upgraded).

## Dictionary headers

A dictionary hit uses:

```
commonName-datatype
AQUARIUS
```

Series not in the dictionary keep the API location / label.

## Rounding

`valuePrecision` is an Aquarius **parameter identifier**. `core/valuePrecision.json` maps those identifiers to `DEC(n)` / `SIG(n)`. Override per row with `precisionOverride`. See [Data Dictionary](Data-Dictionary).

## Dictionary export (published series)

From the project root, with Options → Aquarius already set (same keyring login as queries):

```bash
python scripts/aquariusDictionary.py TFLC
python scripts/aquariusDictionary.py ALL
python scripts/aquariusDictionary.py TFLC --out tflc.csv
python scripts/aquariusDictionary.py ALL --apply
```

Pass a location **Identifier** (or the 32-character location UniqueId), or **ALL** / `--all` for every location. The script lists time-series with **Publish** checked and writes Data Dictionary columns:

| Column | Source |
|--------|--------|
| `dataID` | Time-series UniqueId |
| `siteID` | Location Identifier |
| `database` | `AQUARIUS` |
| `siteName` | Location name |
| `commonName` | Time-series Label |
| `datatype` / `valuePrecision` | Aquarius `Parameter` only when it exactly matches a `valuePrecision.json` Identifier; otherwise blank |

`--apply` inserts new rows into `core/bunker.db` and skips existing `dataID` + `AQUARIUS`. There is no `stationID` column; the location identifier is `siteID`.

## Writes

Aquarius **upload is stubbed**. You can edit the table; write-back is not live yet.

## Time zones

Daily Aquarius values can show as `23:00` instead of `00:00` if the query UTC offset does not match the location TZ (e.g. UTC−6 data queried as UTC−7). That is a known issue, not a dictionary bug.
