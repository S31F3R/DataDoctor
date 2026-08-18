# Data Dictionary

The dictionary (`core/bunker.db`, table `dataDictionary`) is how Data Doctor turns raw IDs into labels, rounding, and QAQC limits.

Open it from the book/database button on the main window. **Ctrl+S** or **Save** writes the table (combo columns are committed first). Search filters as you type.

## Columns (order)

`dataID`, `siteID`, `database`, `siteName`, `commonName`, `datatype`, `valuePrecision`, `precisionOverride`, `expectedMin`, `expectedMax`, `cuttoffMin`, `cutoffMax`, `rateOfChange`

(`cuttoffMin` is the historical spelling in the schema.)

- **database** is a dropdown (internal + public sources).
- **valuePrecision** is a dropdown of Aquarius identifiers from `core/valuePrecision.json`.

## How header labels are built

When a queried ID hits the dictionary **and** `commonName` is a real name (not empty / not the raw id):

```
commonName-datatype
<second line depends on source>
```

No spaces around the dash. If `datatype` is blank, the first line is just `commonName`.

| Source | Second line |
|--------|-------------|
| USGS-NWIS | `USGS` |
| Aquarius | `AQUARIUS` |
| USBR / HDB | SDID, or `SDID-MRID` when MRID is not `0` |

Misses (or a weak USGS hit) fall back to site name / interval / raw DataID. Graph legends use the **first** header line (`commonName-datatype`), not the source tag.

## valuePrecision and precisionOverride

Display rounding is a **RoundingSpec**: `DEC(n)` (decimal places) or `SIG(n)` (significant figures). Bankers rounding (half to even).

1. **valuePrecision** — Aquarius parameter identifier. Looked up in `valuePrecision.json` (e.g. discharge → `DEC(3)`).
2. **precisionOverride** — if set (e.g. `DEC(2)`), it wins for that row.
3. If both are blank → **DEC(2)**.

**Options → Raw data** skips rounding in the table (full fixed-point text, never scientific notation). Overlay/delta still compare through the limiter so tiny binary leftovers do not show as a fake delta. See [Overlay and Delta](Overlay-and-Delta).

USGS rows are matched on the **bare time_series_id** (the hex in the DataID), so `precisionOverride` applies even when the query string is `site-tsid-parameter`.

## QAQC coloring

Enabled by **Options → QAQC** (`qaqc` in `user.config`). Runs after the table is filled. **Delta columns are skipped** (they have their own +/− colors).

| Condition | Typical color |
|-----------|----------------|
| Empty cell, timestamp ≤ now | Blue (missing) |
| Value &lt; `expectedMin` | Yellow |
| Value &gt; `expectedMax` | Amber |
| Value &lt; `cuttoffMin` | Orange |
| Value &gt; `cutoffMax` | Red |
| Adjacent-step change &gt; `rateOfChange` | Coral |
| Consecutive values equal | Green |

Limits come from that series’ dictionary row. Blank limit → that check is off.

## Editing

- Cell multi-select + **Ctrl+C** (Excel-like TSV)
- **Add row** / **Delete row**
- Combo columns size to contents

The live file is next to the app (`Project Files\core\bunker.db` on Windows). Packaged `temp/bunker.db` is only a merge source for updates.
