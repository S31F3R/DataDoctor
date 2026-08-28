# Querying

Two query doors on the main window:

| Button | Who it is for | Typical sources |
|--------|----------------|-----------------|
| **Public Query** | No HDB write, no internal-only metadata | USGS-NWIS, public USBR web, Aquarius if configured |
| **Internal Query** | Reclamation / HDB login | HDB (Oracle), Aquarius, USGS |

Both open the same Query window. The window title / `queryType` decides what is allowed (internal can upload; public cells stay locked).

**Options → Oracle → Access List** hides unchecked HDB names from **Internal Query** and **SQL Query Builder**. **Public Query** still lists every database. Data Dictionary is not filtered.

## Building a query list

1. Pick **database**, **DataID**, **interval**, and a time range.
2. **Add Query** (or **Insert Above / Insert Below / Delete** from the list context menu).
3. Repeat for more series.
4. Optional Query Options (all default **unchecked**): **Display Deltas**, **Overlay Pairs**, **Raw Data**, **QAQC**. See [Overlay and Delta](Overlay-and-Delta).
5. **Query**.

Double-click a list row to edit it (interval and database can change). Select more than one row (Ctrl / Shift) to **Delete** or move with the up/down buttons; Insert Above / Below is disabled while several rows are selected. Moving stops at the topmost selected row going up, and the bottommost going down. **Clear Query List** also unchecks the Query Options boxes.

**Prev Day** / **Prev Week** recompute “now” when you open the window, load a Quick Look, or run Query — they are not frozen timestamps from last week. A Quick Look remembers which of Custom / Prev Day / Prev Week was selected. Custom is the default and stores the picker times; the two rolling modes do not.

**Data ID Search** includes **siteID**. See [Data Dictionary](Data-Dictionary#what-dataid-and-siteid-mean) for what dataID / siteID mean per source.

## Intervals

| Interval | Notes |
|----------|--------|
| `INSTANT:1` / `:15` / `:60` | Instantaneous / continuous |
| `HOUR` | HDB / Aquarius. **Not** offered for USGS-NWIS |
| `DAY` | Daily |
| `MONTH` / `YEAR` / `WATER YEAR` | HDB (and similar). USGS OGC has no monthly/yearly products |

USGS-NWIS combo is capped at **DAY**. Default when you pick USGS-NWIS is `INSTANT:15`.

Timestamps in the table: day / month / year / water-year use display formats (not a fake 00:00 on every row when the interval is coarser). Instant/hour stay clock times.

## Time range radios

- **Custom** — whatever is in the start/end pickers
- **Prev Day to current** / **Prev Week to current** — rolling windows ending now
- **Refresh** on the main Data Query tab bumps the end time to now unless the query is clearly historical (end more than ~2 hours in the past)

## Data Query vs SQL Query Builder

- **Data Query** — the series table from Public/Internal Query (graph, overlay, upload, QAQC)
- **SQL Query Builder** — custom Oracle SQL (internal). Toggle with the SQL button; the tab can Detach like Graph/Log. Worksheets (query tabs) each remember their database. Results are tabs under the worksheet; the **pin** on a result tab (where close would be) keeps that grid and the next run opens a new one. **Stop** cancels a running query. **History** reloads recent SQL (double-click). Snippets live in the right pane (categories). Existing snippets start in Uncategorized; **Categories** lets you add/remove groups and drag a snippet onto a category to move it. Right-click a snippet (in the pane or in Categories) to **Delete**. Double-click the thin dotted splitter handle to collapse/expand that pane (the handle stays visible). Worksheets are session-only.

**CSV** exports whichever of those two tables is active. See [CSV Export](CSV-Export).

## After a query

The **Data Query** tab is selected (re-added at index 0 if you had closed it). Graph stays available via the Graph button or header/cell context menu.

Right-click a **header** for series details / Graph. Right-click a **cell** for value details (internal, plus USGS public “Show details”).

Internal tables accept Excel-style **formulas** (`=A1+B1`, fill handle, `$` locks). See [Formulas](Formulas).

See [Data Dictionary](Data-Dictionary) for how column titles are built.
