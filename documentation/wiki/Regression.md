# Regression

Right-click a header or a cell block on the Data Query table and choose **Regression**. Pick which series to predict. Data Doctor opens a **Regression** tab with one fit. The query table is not changed, and nothing is uploaded.

You need at least two numeric columns. The step has to fall between **1 minute and 1 day** (the median gap in the table). Delta columns are left out. An overlay column uses the **primary** value you see in the cell.

## What the fit is

For each other column, Regression estimates a single lag (how many steps that series leads or trails the one you are predicting), then fits a straight line with an intercept.

- A **negative** lag means that series leads (typical of an upstream gage).
- A **positive** lag means it trails.

The search window depends on the step: a few hours for 1-minute data, up to 14 days for daily data. A lag that lands on the edge of that window is called out on the equation label.

A column that does not improve the fit is dropped. There is one equation, not a list of runners-up.

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

The label under the plot repeats the equation, the lags, r², mean error (ME), RMSE, how many points were used, and the step. Warnings (short record, weak cross-check, lag on the window edge) are on that label too. The fit is still drawn.

Double-click the label, or right-click it and choose **Copy**. The clipboard gets a formula you can paste into a Data Query cell:

```
=1.037*B1+0.214*D1+8.6
```

Letters match the live table (`A` is the leftmost data column). The lag is **not** in that formula. The label tells you which row the lagged series came from so you can start the fill on the right row.

## Save and detach

**Save** uses the last regression folder (or the last graph folder, if you have not saved a regression yet). Right-click the Regression **tab** → **Detach**. Attach puts it back. Switching Appearance restyles an open regression the same way as Graph.

One column, a step coarser than daily, or too little overlap: a status message, and no Regression tab.

## Related

[Graph](Graph) · [Formulas](Formulas) · [Overlay and Delta](Overlay-and-Delta)
