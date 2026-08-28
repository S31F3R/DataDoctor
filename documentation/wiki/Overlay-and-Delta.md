# Overlay and Delta

On the Query window, **Overlay Pairs** and **Display Deltas** apply to **pairs** in the query list (1–2, 3–4, …). **Raw Data** and **QAQC** sit on the next row. All four default **unchecked** and are stored on a Quick Look the same way.

## Overlay

One table column holds two series. Where both have a value, you see the **primary**. Where only the secondary exists, that value is filled in and **auto-marked for upload** (magenta edit) so a Refresh does not treat it as an untouched blank.

- Overlay cells that differ (after the display limiter) paint <span style="color:#FF0000">red</span>.
- Overlay Details shows Primary Value, Secondary Value, and Delta using the **same strings as the limiter** — in raw mode, two DB floats that only differ past display precision show as equal and Delta `0`.
- Graph overlay legends use each series’ first header line (`commonName-datatype`).

If a saved Quick Look is missing overlay/delta metadata, those checkboxes stay **unchecked** (safe default).

## Delta

An extra column: secondary − primary (or the pair rule used at query time).

- Never shows signed zero (`-0.00`).
- Uses the same display limiter as overlay (raw mode will not invent `2e-15`).
- **QAQC does not color delta columns.** Positive delta is <span style="color:#FFA500">orange</span>; negative is <span style="color:#44A5FF">blue</span>.

See [Table colors](Table-Colors) for overlay-only fills, pending upload (magenta), and the Options swatch table.

You can run Overlay, Delta, or both.

[Formulas](Formulas) on an overlay column edit the **primary** value only. Delta columns stay locked.

## Upload

Internal queries only. Public tables are locked.

- User edits and overlay auto-fills are <span style="background:#C2185B;color:#FFF;padding:1px 8px">magenta</span> until uploaded.
- HDB writes go through `MODIFY_R_BASE` / `DELETE_R_BASE` (blank cells delete).
- Aquarius writes are not implemented yet (stub popup).
- **Undo** re-sorts by timestamp; it does not revert uploads.

See [USBR HDB](USBR-HDB) for BOP/EOP on hourly writes.
