# Data Dictionary

The dictionary (`core/bunker.db`, table `dataDictionary`) is how Data Doctor turns raw IDs into labels, rounding, and QAQC limits.

Open it from the book/database button on the main window. **Ctrl+S** or **Save** writes the table (combo columns are committed first). Search filters as you type (dataID, site name, common name — not siteID or database).

**siteID** and **database** headers have a filter icon. **siteID** opens a text box (type a site, substring match). **database** opens a list of databases in the table (first click). While a filter is on, the icon switches to **Filtered**. Right-click that icon → **Clear filter**. Database lists refresh when you Save.

## Columns (order)

`dataID`, `siteID`, `database`, `siteName`, `commonName`, `datatype`, `valuePrecision`, `precisionOverride`, `expectedMin`, `expectedMax`, `cuttoffMin`, `cutoffMax`, `rateOfChange`

(`cuttoffMin` is the historical spelling in the schema.)

## What dataID and siteID mean

These two columns are **not** the same thing, and the ID you type in Query is the **dataID**. What that string is depends on the source:

| Source | dataID (what you query) | siteID (dictionary / search) |
|--------|-------------------------|------------------------------|
| **USBR / HDB** | Site datatype ID (**SDID**). Optional model-run suffix: `SDID-MRID` | HDB site ID (numeric) |
| **Aquarius** | Timeseries **UID** (32-char hex) | Location identifier (e.g. `TFLC`) |
| **USGS-NWIS** | Dictionary stores the `time_series_id` hex. Query accepts `Site-tsid[-parameter]`, `Site-parameter`, or legacy `Site-methodID-parameter` | USGS site number (e.g. `09429100`) |

**Data ID Search** in the Query window lists `dataID`, `siteID`, database, commonName, and datatype. Sorting those ID columns puts **all-digit values first** (numeric order), then mixed/text IDs alphabetically.

**database** is a dropdown (internal + public sources). **valuePrecision** is a dropdown of Aquarius identifiers from `core/valuePrecision.json`.

## How header labels are built

When a queried ID hits the dictionary **and** `commonName` is a real name (not empty / not the raw id):

```
commonName-datatype
<second line depends on source>
```

No spaces around the dash. If `datatype` is blank, or **Options → USBR / Aquarius / USGS → Add Data Type to Labels** is off for that source, the first line is just `commonName`.

| Source | Second line |
|--------|-------------|
| USGS-NWIS | `USGS` |
| Aquarius | `AQUARIUS` |
| USBR / HDB | SDID, or `SDID-MRID` when MRID is not `0` |

Misses (or a weak USGS hit) fall back to site name / interval / raw DataID. Graph legends use the **first** header line (`commonName-datatype`), not the source tag.

**Rename header** (header context menu) changes only the common-name part, not `-datatype`. After the next new query, Data Doctor can save or update that common name in the dictionary (dataID / database / USGS site fields filled from the query when the row is new).

## valuePrecision and precisionOverride

Display rounding is a **RoundingSpec**: `DEC(n)` (decimal places) or `SIG(n)` (significant figures). Bankers rounding (half to even).

1. **valuePrecision** — Aquarius parameter identifier. Looked up in `valuePrecision.json` (e.g. discharge → `DEC(3)`).
2. **precisionOverride** — if set (e.g. `DEC(2)`), it wins for that row.
3. If both are blank → **DEC(2)**.

Query window **Raw Data** skips rounding in the table (full fixed-point text, never scientific notation). Overlay/delta still compare through the limiter so tiny binary leftovers do not show as a fake delta. See [Overlay and Delta](Overlay-and-Delta). The box is per query (and stored on a Quick Look); default is unchecked.

USGS rows are matched on the **bare time_series_id** (the hex in the DataID), so `precisionOverride` applies even when the query string is `site-tsid-parameter`.

## QAQC coloring

Enabled by the Query window **QAQC** checkbox (stored on a Quick Look; default unchecked). Runs after the table is filled. **Delta columns are skipped** (they have their own +/− colors).

| Condition | Color |
|-----------|-------|
| Empty cell, timestamp ≤ now | <span style="background:#64C3F7;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> Missing |
| Value &lt; `expectedMin` | <span style="background:#F9F06B;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> |
| Value &gt; `expectedMax` | <span style="background:#F9C211;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> |
| Value &lt; `cuttoffMin` | <span style="background:#FFA348;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> |
| Value &gt; `cutoffMax` | <span style="background:#C01C28;color:#FFF;padding:2px 14px;border:1px solid #888">Aa</span> |
| Adjacent-step change &gt; `rateOfChange` | <span style="background:#F66151;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> |
| Consecutive values equal | <span style="background:#57E389;color:#000;padding:2px 14px;border:1px solid #888">Aa</span> |

Limits come from that series’ dictionary row. Blank limit → that check is off.

Overlay, delta, pending-edit, and upload colors: [Table colors](Table-Colors) (same swatches as **Options → Appearance**).

## Editing

- Cell multi-select + **Ctrl+C** (Excel-like TSV)
- **Add row** / **Delete row**
- Combo columns size to contents

The live file is next to the app (`pythonFiles\core\bunker.db` on Windows). Packaged `temp/bunker.db` is only a merge source for updates.
