# Regression

Right-click a header or a cell block on the Data Query table and choose **Regression**. Pick which series to predict. Data Doctor opens a **Regression** tab with one fit. The query table is not changed, and nothing is uploaded.

You need at least two numeric columns. The step has to fall between **1 minute and 1 day** (the median gap in the table). Delta columns are left out. An overlay column uses the **primary** value you see in the cell.

## What the fit is

For each other column, Regression estimates a single lag (how many steps that series leads or trails the one you are predicting), then fits one straight line with an intercept. Every selected series is tried. A series that cannot be used is left out, and the label under the stats names it and says why. Two upstream gages on the same wave both stay in the equation. There is one equation, not a list of runners-up.

## How the lag is chosen

The lag search is a pre-whitened cross-correlation, one lag per series.

1. Fit an AR(1) on that series: each value against the one before it. The slope φ is clipped to (−0.99, 0.99).
2. Pre-whiten the target and that series with the same φ: `y'[t] = y[t] − φ·y[t−1]`. The first point and any gap stay blank. This stops a slow rise (a storm climbing for hours) from looking like a travel time.
3. At each candidate shift k, compute the correlation of the whitened target at t with the whitened series at t+k. The winning lag is the largest |correlation|. A tie goes to the smaller shift.

The sign follows the table, not the river mile:

- A **negative** lag means that series leads (typical of an upstream gage). The fit uses an earlier row of that column.
- A **positive** lag means it trails.

The search window depends on the step, so 1-minute data is not scanned across a week:

| Step | Window |
|------|--------|
| 1–5 min | 6 hours |
| 6–15 min | 12 hours |
| 16–60 min | 24 hours |
| longer than an hour, shorter than a day | 3 days |
| 1 day | 14 days |

A lag needs at least 20 overlapping whitened pairs, and |correlation| of at least 0.1. Otherwise that series is left out as **no usable lag**.

The record is also split in half. If the two halves pick different lags, the label warns that the split-half lags disagree. The equation still uses the lag from the full record. A lag that lands on the edge of the window is called out too: a longer travel time may have been cut off.

## The equation

The line is ordinary least squares on the **original** values, shifted by the lags above, plus an intercept. Pre-whitening is only for finding the lag. It is not what gets plotted or copied.

```
Y = a·A[t + lag A] + b·B[t + lag B] + c
```

Letters match the live table (`A` is the leftmost data column). Copied into a cell, the lag is dropped (`=1.037*B1+8.6`). The label tells you which row the lagged series came from so you can start the fill on the right row.

The numbers under the equation:

| Stat | Meaning |
|------|---------|
| r² | Share of the target's variance the line explains (`1 − SS_res / SS_tot`). |
| ME | Mean of fitted minus observed. Near zero means the line is not systematically high or low. |
| RMSE | Root mean square of that same residual, in the target's units. |
| N | Rows where the target and every kept series all have a value after the lag. |

A blocked cross-check trains on some stretches of the record and scores the stretches it held out. When that r² is much weaker than the in-sample fit, the label says so. It is a warning, not a second equation.

Short records are called out the same way (under 48 hours, under 7 days, or under 30 days of daily data). A fit with few rows, or with a target that is strongly autocorrelated, is marked underpowered: treat the slope as a sketch.

## What gets left out

Each warning sits under the stats as `Warning: Left out A: …`.

- **no usable lag** — not enough overlap, or the whitened correlation never reaches 0.1.
- **does not move the fit** — the whitened peak is under 0.15 and the series adds less than 0.02 to r². A weak peak that does raise r² by that much still stays, unless its coefficient moves the target by less than about 5% of the target's spread. A peak of 0.15 or more stays even when its unique r² is tiny, which is what happens when two gages carry the same wave.
- **not enough overlapping rows** — after lagging, N is below the larger of 20 rows and 10 rows per fitted term (the intercept plus each series). The sparsest series is dropped and the rest are refit. A short custom column must not throw out the gages that actually overlap.

If you select six series and only two can be used, the equation uses those two and names the other four. If nothing usable is left, there is no Regression tab: the status bar says why.

## Two views

The legend is a radio. Exactly one view is on.

```
[x] Relationship
[ ] Aligned
```

**Relationship** (default) is a scatter, not a hydrograph.

- One other column: observed values versus that column after the lag, with the fit line.
- Two or more: observed versus fitted, with a 1:1 line.

**Aligned** is a time plot. The series you predicted stays put. The others are shifted by their lag so the wave sits on it. Each legend row shows the lag in steps and in clock time. Those rows can be hidden; they are not extra fits.

Missing timestamps stay gapped.

## Equation

The label under the plot repeats the equation, the lags, r², mean error (ME), RMSE, how many points were used, and the step. Warnings (short record, weak cross-check, lag on the window edge, a series left out) are on that label too. The fit is still drawn.

Double-click the label, or right-click it and choose **Copy**. The clipboard gets a formula you can paste into a Data Query cell:

```
=1.037*B1+0.214*D1+8.6
```

Letters match the live table (`A` is the leftmost data column). The lag is **not** in that formula. The label tells you which row the lagged series came from so you can start the fill on the right row.

## Save and detach

**Save** uses the last regression folder (or the last graph folder, if you have not saved a regression yet). Right-click the Regression **tab** → **Detach**. Attach puts it back. Switching Appearance restyles an open regression the same way as Graph.

One column, a step outside 1 minute through 1 day, a target that does not vary, or a record shorter than a few travel times: a status message, and no Regression tab. Too little overlap drops the sparsest series first; the tab is skipped only when even one series cannot meet the row count.

## Related

[Graph](Graph) · [Formulas](Formulas) · [Overlay and Delta](Overlay-and-Delta)
