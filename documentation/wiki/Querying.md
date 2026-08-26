# Querying

Two query doors on the main window:

| Button | Who it is for | Typical sources |
|--------|----------------|-----------------|
| **Public Query** | No HDB write, no internal-only metadata | USGS-NWIS, public USBR web, Aquarius if configured |
| **Internal Query** | Reclamation / HDB login | HDB (Oracle), Aquarius, USGS |

Both open the same Query window. The window title / `queryType` decides what is allowed (internal can upload; public cells stay locked).

## Building a query list

1. Pick **database**, **DataID**, **interval**, and a time range.
2. **Add Query** (or **Insert Above / Insert Below / Delete** from the list context menu).
3. Repeat for more series.
4. Optional: **Delta** and/or **Overlay** (see [Overlay and Delta](Overlay-and-Delta)).
5. **Query**.

Double-click a list row to edit it (interval and database can change). **Clear Query List** also unchecks Delta and Overlay.

**Prev Day** / **Prev Week** recompute “now” when you open the window, load a Quick Look, or run Query — they are not frozen timestamps from last week.

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
- **SQL Query Builder** — custom Oracle SQL (internal). Toggle with the SQL button. Opens with **zero** tabs; add/run from there. Snippets save under [App Data](App-Data) `quickLook/sql/`

**CSV** exports whichever of those two tables is active. See [CSV Export](CSV-Export).

## After a query

The **Data Query** tab is selected (re-added at index 0 if you had closed it). Graph stays available via the Graph button or header/cell context menu.

Right-click a **header** for series details / Graph. Right-click a **cell** for value details (internal, plus USGS public “Show details”).

See [Data Dictionary](Data-Dictionary) for how column titles are built.
