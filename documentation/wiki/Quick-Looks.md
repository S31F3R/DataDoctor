# Quick Looks

A Quick Look is a **saved query list** (databases, DataIDs, intervals, Query Options flags, time-range mode) so you can reload a stretch or station set without rebuilding it.

## Where they live

User Quick Looks (the ones you save):

```
<config>/quickLook/query/*.txt   # Linux: ~/.config/Data Doctor/quickLook/query/
```

SQL snippets are a different folder: `<config>/quickLook/sql/`.

See [App Data](App-Data).

## Save / load / delete

In the Query window:

1. Build the list (and set Display Deltas / Overlay Pairs / Raw Data / QAQC if you want them stored).
2. **Save Quick Look** — the name box is filled from the combo when a Quick Look is already selected. If that name exists, confirm overwrite.
3. Pick it in the combo and **Load Quick Look**.
4. **Delete Quick Look** removes that saved file (including former packaged examples — they live in your profile).

If an older file is missing overlay/delta/raw/QAQC metadata, those checkboxes stay **unchecked** when loaded.

Date range:

- **Custom** (default) — on **Save Quick Look** you must pick how those dates should behave on load (issue #3). Choices are inferred from the start/end you set and the query interval, for example:
  - From **current time** through N days later (start was within one interval of now; for 1-minute series, within 15 minutes)
  - From **current time through midnight** N calendar days from today (end was 00:00)
  - **Today at HH:MM** through N days later at that clock (you were not querying “now”)
  - Last N days **through current time**
  - Weekly on the same weekday, or first/second/…/last weekday of the month (daily-style ranges)
  - **Don't restore dates** when the Quick Look is loaded
  - **Keep these exact dates**
  - **None of these** — save is cancelled; a suggestion is shown to snap the end to an even interval
- **Prev Day to current** / **Prev Week to current** — only the mode is stored; load and Query refresh from *now* (same rolling window as the radio buttons)

Relative custom rules (and Prev Day / Prev Week) refresh when you **load** and when you **Query**.

## Export / Import

**Options → General → Export… / Import…** can include Query Quick Looks, SQL Quick Looks, Config, and the **Data Dictionary**. Dictionary import replaces `core/bunker.db` (no merge prompts).

Import **merges**. Existing files with the same name prompt **Overwrite**, **Skip**, or **Rename** (and Overwrite all / Skip all when more than one clash remains). Nothing is wiped just because it was not in the zip.

SQL Quick Looks export a `categories.json` sidecar. On import you choose **With categories** (keep folder assignments from the zip) or **Without categories** (new snippets go to Uncategorized).

## Packaged examples

Zips still ship a `quickLook/` folder for first install. On launch, if the user profile has **no** query Quick Looks, those files are copied into `<config>/quickLook/query/`. Then the packaged folder is removed (installs only — not the source tree). If you already have profile Quick Looks, packaged copies are just deleted. There is no separate “example” list and no delete restriction.

## Plot-style Quick Looks

A Quick Look is the **query list**, not a saved graph layout. After load, use [Graph](Graph) as usual.
