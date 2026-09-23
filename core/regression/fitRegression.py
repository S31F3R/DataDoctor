# fitRegression.py
# One lagged OLS fit. Callers get a result or a refusal message.
# No second equation, no table writes.

from __future__ import annotations

from datetime import timedelta

import numpy as np

from core.regression.alignSeries import (
    buildGrid,
    medianStepSeconds,
    shiftDisplay,
    stepInBand,
)
from core.regression.equation import (
    formatClock,
    formatNumber,
    formatStep,
    formatSteps,
    legendLag,
    renderEquation,
    renderLabel,
)
from core.regression.lagDetect import detectLag
from core.regression.scoreRegression import blockedCvR2, effectiveN, regressionScores


class SeriesColumn:
    """One numeric table column already pulled off the query grid."""

    def __init__(self, key: str, label: str, col: int, times, values):
        self.key = str(key)
        self.label = str(label or key)
        self.col = int(col)
        self.times = list(times)
        self.values = np.asarray(values, dtype=float)


class PredictorFit:
    def __init__(self, column: SeriesColumn, detection, coef: float):
        self.key = column.key
        self.label = column.label
        self.col = column.col
        self.lagSteps = int(detection.lagSteps)
        self.peakRho = float(detection.peakRho)
        self.agrees = bool(detection.agrees)
        self.pinned = bool(detection.pinned)
        self.phi = float(detection.phi)
        self.coef = float(coef)


class AlignedSeries:
    def __init__(self, key, label, legend, times, values, lagSteps, isTarget):
        self.key = key
        self.label = label
        self.legend = legend
        self.times = times
        self.values = np.asarray(values, dtype=float)
        self.lagSteps = int(lagSteps)
        self.isTarget = bool(isTarget)


class RegressionResult:
    def __init__(self):
        self.targetKey = ""
        self.targetLabel = ""
        self.targetCol = -1
        self.predictors = []
        self.intercept = 0.0
        self.r2 = 0.0
        self.me = 0.0
        self.rmse = 0.0
        self.n = 0
        self.nEff = 0.0
        self.cvR2 = None
        self.equationText = ""
        self.copyText = ""
        self.labelText = ""
        self.figureText = ""
        self.warnings = []
        self.stepSeconds = 0.0
        self.stepLabel = ""
        self.scatterMode = "fitted"  # 'lagged' (one predictor) or 'fitted'
        self.scatterX = np.array([])
        self.scatterY = np.array([])
        self.lineX = np.array([])
        self.lineY = np.array([])
        self.xLabel = ""
        self.yLabel = ""
        self.aligned = []
        self.spanSeconds = 0.0


def _refuse(message: str):
    return None, message


def _completeDesign(grid, targetKey, predictors):
    """
    Rows where the target and every lagged predictor are finite.

    Returns (indices, designWithoutIntercept, y) or None.
    """
    yGrid = grid.columns.get(targetKey)
    if yGrid is None:
        return None
    n = int(grid.length)
    xs = []
    for pred in predictors:
        arr = grid.columns.get(pred.key)
        if arr is None:
            return None
        xs.append(arr)
    indices = []
    rows = []
    ys = []
    for t in range(n):
        if not np.isfinite(yGrid[t]):
            continue
        row = []
        ok = True
        for pred, arr in zip(predictors, xs):
            j = t + int(pred.lagSteps)
            if j < 0 or j >= n or not np.isfinite(arr[j]):
                ok = False
                break
            row.append(float(arr[j]))
        if not ok:
            continue
        indices.append(t)
        rows.append(row)
        ys.append(float(yGrid[t]))
    if not indices:
        return None
    design = np.asarray(rows, dtype=float)
    if design.ndim == 1:
        design = design.reshape(-1, 1)
    return indices, design, np.asarray(ys, dtype=float)


def _fitOls(design, y):
    """(intercept, coefs, yhat, r2, me, rmse) or None if y does not vary."""
    if design.size == 0 or y.size < 2:
        return None
    centered = y - float(np.mean(y))
    if float(np.dot(centered, centered)) <= 1e-18:
        return None
    A = np.column_stack([np.ones(y.size), design])
    coef, *_rest = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    r2, me, rmse = regressionScores(y, yhat)
    return coef, yhat, A, r2, me, rmse


def _isDead(r2Full, r2Without, coef, xColumn, y, peakRho) -> bool:
    """
    Drop a column only when it has no real weight.

    Unique r² can be tiny when two gages carry the same wave (upstream and
    downstream of the target). That is not "near zero" — the coefficient
    still moves the target. A flat, unrelated column has a weak peak and
    does not earn its term.
    """
    gained = float(r2Full) - float(r2Without)
    stdY = float(np.std(y))
    stdX = float(np.std(xColumn))
    if stdY <= 1e-12:
        return True
    contrib = abs(float(coef)) * stdX / stdY
    if abs(float(peakRho)) < 0.15 and gained < 0.02:
        return True
    if gained < 0.01 and contrib < 0.05:
        return True
    return False


def _lagCoverage(grid, targetKey, det) -> int:
    """Target rows where this lagged predictor is also finite."""
    yGrid = grid.columns[targetKey]
    arr = grid.columns.get(det.key)
    if arr is None:
        return 0
    n = int(grid.length)
    count = 0
    for t in range(n):
        if not np.isfinite(yGrid[t]):
            continue
        j = t + int(det.lagSteps)
        if 0 <= j < n and np.isfinite(arr[j]):
            count += 1
    return count


def _warnings(stepSeconds, spanSeconds, n, nEff, r2, cvR2, predictors):
    out = []
    if n < 50 or nEff < 20:
        out.append(
            "Underpowered fit (few rows or strong autocorrelation); "
            "treat the slope as a sketch."
        )
    subDaily = float(stepSeconds) < 86400.0 * 0.98
    if subDaily:
        if spanSeconds < 48 * 3600:
            out.append(
                "Short record (under 48 hours): likely one event, "
                "not a standing relationship."
            )
        if spanSeconds < 7 * 86400:
            out.append("Short record (under 7 days).")
    elif spanSeconds < 30 * 86400:
        out.append("Short daily record (under 30 days).")
    for pred in predictors:
        if not pred.agrees:
            out.append(f"Split-half lags disagree for {pred.key}.")
        if pred.pinned:
            out.append(
                f"Lag for {pred.key} sits on the search window edge; "
                "a longer lag may be cut off."
            )
    if cvR2 is not None:
        muchWorse = (float(r2) - float(cvR2)) > 0.25
        weakHoldout = float(r2) >= 0.4 and float(cvR2) < 0.4
        if muchWorse or weakHoldout:
            out.append("Cross-check r² is much weaker than the in-sample fit.")
    return out


def _aligned(grid, target, predictors):
    times = grid.times()
    out = []
    y = grid.columns[target.key]
    out.append(AlignedSeries(
        target.key, target.label, "Target", times, y, 0, True,
    ))
    for pred in predictors:
        src = grid.columns[pred.key]
        shown = shiftDisplay(src, pred.lagSteps)
        out.append(AlignedSeries(
            pred.key,
            pred.label,
            legendLag(pred.key, pred.lagSteps, grid.stepSeconds),
            times,
            shown,
            pred.lagSteps,
            False,
        ))
    return out


def fitColumns(columns, targetIndex: int):
    """
    Fit one equation.

    columns: sequence of SeriesColumn (predictors + target).
    targetIndex: which entry is predicted.
    Returns (RegressionResult, None) or (None, refusalMessage).
    """
    cols = list(columns or [])
    if targetIndex is None or targetIndex < 0 or targetIndex >= len(cols):
        return _refuse("Pick a series to predict.")
    if len(cols) < 2:
        return _refuse("Regression needs at least two numeric columns.")

    target = cols[targetIndex]
    others = [c for i, c in enumerate(cols) if i != targetIndex]
    if not others:
        return _refuse("Regression needs at least two numeric columns.")

    step = medianStepSeconds(cols)
    if step is None:
        return _refuse("Not enough timestamps to see a step.")
    if not stepInBand(step):
        return _refuse(
            "Step is outside 1 minute through 1 day, so Regression did not fit."
        )

    grid, gridError = buildGrid(cols, step)
    if grid is None:
        return _refuse(gridError or "Could not line the series up in time.")

    finiteTarget = int(np.count_nonzero(np.isfinite(grid.columns[target.key])))
    if finiteTarget < 20:
        return _refuse(
            f"Not enough overlapping rows to fit (have {finiteTarget}, need 20)."
        )

    detections = []
    detectedCols = []
    for col in others:
        found = detectLag(
            grid.columns[target.key],
            grid.columns[col.key],
            step,
            key=col.key,
        )
        if found is None or not found.usable:
            continue
        detections.append(found)
        detectedCols.append(col)
    if not detections:
        return _refuse("No usable lag between the target and the other columns.")

    built = _completeDesign(grid, target.key, detections)
    if built is None:
        return _refuse("No overlap left after lagging.")
    indices, design, y = built
    fitted = _fitOls(design, y)
    if fitted is None:
        return _refuse("The target does not vary, so Regression did not fit.")
    coef, yhat, A, r2, me, rmse = fitted

    # Drop dead predictors once. Do not shop a second equation.
    keep = []
    for i, det in enumerate(detections):
        # Column i+1 of A is this predictor (column 0 is the intercept).
        colsKeep = [c for c in range(A.shape[1]) if c != i + 1]
        reduced, *_rest = np.linalg.lstsq(A[:, colsKeep], y, rcond=None)
        yhatReduced = A[:, colsKeep] @ reduced
        r2Reduced, _meR, _rmseR = regressionScores(y, yhatReduced)
        if _isDead(r2, r2Reduced, coef[i + 1], A[:, i + 1], y, det.peakRho):
            continue
        keep.append(i)

    if not keep:
        return _refuse("No usable lag between the target and the other columns.")

    if len(keep) != len(detections):
        detections = [detections[i] for i in keep]
        built = _completeDesign(grid, target.key, detections)
        if built is None:
            return _refuse("No overlap left after lagging.")
        indices, design, y = built
        fitted = _fitOls(design, y)
        if fitted is None:
            return _refuse("The target does not vary, so Regression did not fit.")
        coef, yhat, A, r2, me, rmse = fitted

    # A short custom column (a formula filled on only a few rows) must not
    # throw out the gages that actually overlap. Drop the sparsest and refit.
    while len(detections) > 1:
        p = 1 + len(detections)
        n = int(y.size)
        if n >= max(20, 10 * p):
            break
        covers = [_lagCoverage(grid, target.key, det) for det in detections]
        detections.pop(int(np.argmin(covers)))
        built = _completeDesign(grid, target.key, detections)
        if built is None:
            return _refuse("No overlap left after lagging.")
        indices, design, y = built
        fitted = _fitOls(design, y)
        if fitted is None:
            return _refuse("The target does not vary, so Regression did not fit.")
        coef, yhat, A, r2, me, rmse = fitted

    predictors = []
    for i, det in enumerate(detections):
        column = next(c for c in others if c.key == det.key)
        predictors.append(PredictorFit(column, det, coef[i + 1]))

    p = 1 + len(predictors)
    n = int(y.size)
    need = max(20, 10 * p)
    if n < need:
        return _refuse(
            f"Not enough overlapping rows to fit (have {n}, need {need})."
        )

    origin = grid.origin
    pairTimes = [origin + timedelta(seconds=int(i) * step) for i in indices]
    span = 0.0
    if len(pairTimes) >= 2:
        span = (pairTimes[-1] - pairTimes[0]).total_seconds()
    kClock = max(abs(pred.lagSteps) * step for pred in predictors)
    if kClock > 0 and span < 3.0 * kClock:
        return _refuse(
            "Record is shorter than a few travel times, so the lag is not trustworthy."
        )

    nEff = effectiveN(y)
    cvR2 = blockedCvR2(A, y)
    warnings = _warnings(step, span, n, nEff, r2, cvR2, predictors)

    terms = [(pred.key, pred.coef, pred.lagSteps) for pred in predictors]
    equationText, copyText = renderEquation(terms, float(coef[0]))
    stepLabel = formatStep(step)
    lagParts = [(pred.key, pred.lagSteps, step) for pred in predictors]
    labelText = renderLabel(
        equationText, copyText, lagParts, r2, me, rmse, n, stepLabel, warnings,
    )
    figureText = (
        f"{equationText}\n"
        f"r² = {formatNumber(r2)}   ME = {formatNumber(me)}   "
        f"RMSE = {formatNumber(rmse)}   N = {n}"
    )

    result = RegressionResult()
    result.targetKey = target.key
    result.targetLabel = target.label
    result.targetCol = target.col
    result.predictors = predictors
    result.intercept = float(coef[0])
    result.r2 = float(r2)
    result.me = float(me)
    result.rmse = float(rmse)
    result.n = n
    result.nEff = float(nEff)
    result.cvR2 = None if cvR2 is None else float(cvR2)
    result.equationText = equationText
    result.copyText = copyText
    result.labelText = labelText
    result.figureText = figureText
    result.warnings = warnings
    result.stepSeconds = float(step)
    result.stepLabel = stepLabel
    result.spanSeconds = float(span)
    result.aligned = _aligned(grid, target, predictors)

    if len(predictors) == 1:
        pred = predictors[0]
        result.scatterMode = "lagged"
        result.scatterX = np.asarray(design[:, 0], dtype=float)
        result.scatterY = np.asarray(y, dtype=float)
        x0 = float(np.min(result.scatterX))
        x1 = float(np.max(result.scatterX))
        result.lineX = np.array([x0, x1], dtype=float)
        result.lineY = result.intercept + pred.coef * result.lineX
        clock = formatClock(pred.lagSteps * step)
        result.xLabel = f"{pred.key} lagged ({formatSteps(pred.lagSteps)}, {clock})"
        result.yLabel = target.label or target.key
    else:
        result.scatterMode = "fitted"
        result.scatterX = np.asarray(yhat, dtype=float)
        result.scatterY = np.asarray(y, dtype=float)
        lo = float(min(np.min(result.scatterX), np.min(result.scatterY)))
        hi = float(max(np.max(result.scatterX), np.max(result.scatterY)))
        result.lineX = np.array([lo, hi], dtype=float)
        result.lineY = np.array([lo, hi], dtype=float)
        result.xLabel = "Fitted"
        result.yLabel = "Observed"

    return result, None
