# Quick Looks

A Quick Look is a **saved query list** (databases, DataIDs, intervals, overlay/delta flags, time-range mode) so you can reload a stretch or station set without rebuilding it.

## Where they live

User Quick Looks (the ones you save):

```
<config>/quickLook/query/*.txt   # Linux: ~/.config/Data Doctor/quickLook/query/
```

Example / shipped Quick Looks ship in the app `quickLook/` folder and are copied or listed alongside.

SQL snippets are a different folder: `<config>/quickLook/sql/`.

See [App Data](App-Data).

## Save / load / delete

In the Query window:

1. Build the list (and set Delta / Overlay if you want them stored).
2. **Save Quick Look** — name it. That becomes the last-used name in `user.config`.
3. Pick it in the combo and **Load Quick Look**.
4. **Delete Quick Look** removes that saved file.

If an older file is missing overlay/delta metadata, those checkboxes stay **unchecked** when loaded.

**Prev Day / Prev Week** stored in a Quick Look still mean “rolling to now” — they refresh when you load and when you Query.

## Packaged example

`quickLook/Below Parker Dam (MRID).json` (and similar) are starter looks. Updates do **not** delete user-added files; same-name packaged files can be overwritten.

## Plot-style Quick Looks

A Quick Look is the **query list**, not a saved graph layout. After load, use [Graph](Graph) as usual.
