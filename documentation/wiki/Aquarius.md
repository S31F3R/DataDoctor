# Aquarius

Aquarius Time-Series is an optional **internal/public** source. Configure it under **Options → Aquarius**:

- Server URL (`aqServer`)
- User (`aqUser`)
- Password (`aqPassword`)

All three live in the OS keyring, service `DataDoctor`. The server field’s placeholder is the Aquarius **link** you must have (host / base URL your site actually serves). Empty server → Aquarius queries will fail.

Entra vs credential-account login is **not** implemented yet (backlog). Today it is username/password.

## TLS certificates

The app **never creates** a `certs/` folder. You create one and drop the server cert in:

| File | Behavior |
|------|----------|
| `aquarius.pem` | Used as-is (preferred) |
| `.cer` / `.crt` | Converted to `aquarius.pem` on first use; source file removed after success |
| `.pfx` / `.p12` | **Not supported** — export `.cer` or `.pem` first |

Search order (existing folders only):

1. Project `certs/`
2. App root
3. Parent of app root (Windows zip / launcher folder)
4. Current working directory
5. User config `certs/` (see [App Data](App-Data))

Converted `aquarius.pem` is written **next to** the source file. If conversion fails, the app falls back to system trust, then unverified — it will not keep using a stale pem blindly.

You can instead add the cert to the OS trust store and skip `certs/`.

## Dictionary headers

A dictionary hit uses:

```
commonName-datatype
AQUARIUS
```

Series not in the dictionary keep the API location / label.

## Rounding

`valuePrecision` is an Aquarius **parameter identifier**. `core/valuePrecision.json` maps those identifiers to `DEC(n)` / `SIG(n)`. Override per row with `precisionOverride`. See [Data Dictionary](Data-Dictionary).

## Writes

Aquarius **upload is stubbed**. You can edit the table; write-back is not live yet.

## Time zones

Daily Aquarius values can show as `23:00` instead of `00:00` if the query UTC offset does not match the location TZ (e.g. UTC−6 data queried as UTC−7). That is a known issue, not a dictionary bug.
