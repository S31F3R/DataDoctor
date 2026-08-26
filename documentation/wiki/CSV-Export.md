# CSV Export

The export button writes **whichever table is on the active tab**:

| Active tab | What is exported |
|------------|------------------|
| **Data Query** | The series table (timestamps + every column as displayed) |
| **SQL Query Builder** | The current result tab of the active worksheet |

Display text is what you get (raw vs rounded follows **Options → Raw data**). Overlay/delta columns export as they appear.

You pick the file path. The last folder is remembered as `lastExportPath` in `user.config`.

This is a dump of the table, not a native USGS/HDB extract. For QAQC colors and dictionary meaning, stay in the app or see [Data Dictionary](Data-Dictionary).
