# Aquarius

Aquarius Time-Series is an optional **internal/public** source. Configure it under **Options → Aquarius**:

- Server URL (`aqServer`)
- User (`aqUser`)
- Password (`aqPassword`)

All three live in the OS keyring, service `DataDoctor`. The server field is the Aquarius host / base URL. Empty server → Aquarius queries fail.

Entra vs credential-account login is not implemented. Username and password are used.

## TLS certificates

Windows and macOS launcher zips include an empty `pythonFiles/certs/` folder. Updates never replace files there. Place the server cert:

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

Converted `aquarius.pem` is written **next to** the source file. TLS uses system trust first, then `certs/aquarius.pem`. There is **no unverified HTTPS fallback** (that would send the password to a MITM). If both fail, add the server cert or put it in the OS trust store.

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

## Writes

Aquarius **upload is stubbed**. You can edit the table; write-back is not live yet.

## Time zones

Daily Aquarius values can show as `23:00` instead of `00:00` if the query UTC offset does not match the location TZ (e.g. UTC−6 data queried as UTC−7). That is a known issue, not a dictionary bug.
