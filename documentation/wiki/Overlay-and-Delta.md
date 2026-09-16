# Overlay and Delta

On the Query window, **Overlay Pairs**, **Display Deltas**, **Raw Data**, and **QAQC** are **per-series flags**. Checking a box flags every current Data ID and anything added later. Unchecked, right-click a query-list row to toggle **Overlay**, **Display Deltas**, **Raw Data**, or **QAQC Data** (hold **Ctrl** to toggle several without closing the menu). All four default **unchecked**.

**Overlay pairing** uses consecutive flagged neighbors in list order. A flagged ID next to an unflagged one stays flagged but is **not** a pair (not color-highlighted). Example: six IDs with the 2nd unflagged → first stays flagged but unpaired; 3rd is primary and 4th secondary; 5th/6th the next pair. The query list colors primaries and secondaries as **Overlay primary flag** / **Overlay secondary flag** in **Options → Appearance** (defaults follow the theme). Unpaired and unflagged rows keep the normal text color.

## Overlay

One table column holds two series. Where both have a value, you see the **primary**. Where only the secondary exists, that value is filled in and **auto-marked for upload** (magenta edit) so a Refresh does not treat it as an untouched blank.

- Overlay cells that differ (after the display limiter) paint <span style="color:#FF0000">red</span>. Values that match at the **primary** rounding (USBR `642.272` vs Aquarius `642.2724` at DEC(3)) are **not** flagged; Delta is `0`.
- With **Raw Data** off, Overlay Details shows both values at the primary spec. Individual USBR / Aquarius / USGS details tabs keep each series’ own rounding.
- Header **Swap Primary/Secondary** flips the pair (full header including the dataID line), the query list, and recalculates Delta from the new primary’s rounding. Overlay red clears when the pair now matches at that spec. Column width is resized to fit.
- Cell **Update from secondary** writes the secondary value into primary for cells that differ (Ctrl+Z / Ctrl+Y undo that). USGS and Aquarius primaries are skipped.
- Overlay Details shows Primary Value, Secondary Value, and Delta using the **same strings as the limiter** — in raw mode, two DB floats that only differ past display precision show as equal and Delta `0`.
- Graph overlay legends use each series’ first header line (`commonName-datatype`).

If a saved Quick Look is missing overlay/delta metadata, those checkboxes stay **unchecked** (safe default).

## Delta

An extra column: primary − secondary (same sign as overlay Delta).

- Never shows signed zero (`-0.00`).
- Uses the same display limiter as overlay (raw mode will not invent `2e-15`).
- **QAQC does not color delta columns.** Positive delta is <span style="color:#FFA500">orange</span>; negative is <span style="color:#44A5FF">blue</span>.

See [Table colors](Table-Colors) for overlay-only fills, pending upload (magenta), and the Options swatch table.

You can run Overlay, Delta, or both.

Header **Remove** drops the overlay pair (and Delta when that box is checked) from the table and the query list. With Delta on and Overlay off, removing any of the three columns drops all three.

[Formulas](Formulas) on an overlay column edit the **primary** value only. Delta columns stay locked.

## Upload

Internal queries only. Public tables are locked.

- User edits and overlay auto-fills are <span style="background:#C2185B;color:#FFF;padding:1px 8px">magenta</span> until uploaded.
- HDB writes go through `MODIFY_R_BASE` / `DELETE_R_BASE` (blank cells delete).
- Aquarius writes are not implemented yet (stub popup).
- **Ctrl+Z** / **Ctrl+Y** undo and redo cell edits (including Update from secondary). Toolbar **Reset** re-sorts by timestamp; it does not revert uploads.

See [USBR HDB](USBR-HDB) for BOP/EOP on hourly writes.
