# alignSeries.py
# Time step, shared grid, and lag shift for lagged regression.
# numpy + datetime only. No Qt.

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

# A year of 1-minute data is ~526k steps. Past this the grid is not a
# usable fit (bad timestamps, or a step much finer than the span).
MAX_GRID_STEPS = 2_000_000


def medianStepSeconds(columns) -> float | None:
    """
    Median positive gap between timestamps that actually have a value.

    Mixed or irregular steps are allowed; the median is the working step.
    """
    stamps = []
    for col in columns:
        times = getattr(col, "times", None) or []
        values = getattr(col, "values", None)
        if values is None:
            continue
        vals = np.asarray(values, dtype=float)
        for i, t in enumerate(times):
            if t is None or i >= vals.size or not np.isfinite(vals[i]):
                continue
            if isinstance(t, datetime):
                stamps.append(t)
    if len(stamps) < 3:
        return None
    stamps = sorted(set(stamps))
    diffs = []
    for a, b in zip(stamps, stamps[1:]):
        d = (b - a).total_seconds()
        if d > 0:
            diffs.append(d)
    if not diffs:
        return None
    diffs.sort()
    mid = len(diffs) // 2
    if len(diffs) % 2:
        return float(diffs[mid])
    return float(0.5 * (diffs[mid - 1] + diffs[mid]))


def stepInBand(stepSeconds: float) -> bool:
    """1 minute through 1 day, with a small tolerance for float gaps."""
    if stepSeconds is None or not np.isfinite(stepSeconds):
        return False
    return (60.0 * 0.98) <= float(stepSeconds) <= (86400.0 * 1.02)


class Grid:
    """Integer-step columns. Index 0 is `origin`. Missing samples are NaN."""

    def __init__(self, origin: datetime, stepSeconds: float, length: int, columns: dict):
        self.origin = origin
        self.stepSeconds = float(stepSeconds)
        self.length = int(length)
        self.columns = columns

    def times(self):
        step = self.stepSeconds
        origin = self.origin
        return [origin + timedelta(seconds=i * step) for i in range(self.length)]


def buildGrid(columns, stepSeconds: float):
    """
    Bin each series onto one step grid.

    Returns (Grid, None) or (None, message). Two samples in one bin keep
    the one closer to the bin center.
    """
    step = float(stepSeconds)
    if step <= 0:
        return None, "Could not determine a time step."

    origin = None
    for col in columns:
        vals = np.asarray(col.values, dtype=float)
        for i, t in enumerate(col.times):
            if not isinstance(t, datetime) or i >= vals.size or not np.isfinite(vals[i]):
                continue
            if origin is None or t < origin:
                origin = t
    if origin is None:
        return None, "No numeric values with timestamps to regress."

    binned = {}
    maxIndex = 0
    for col in columns:
        vals = np.asarray(col.values, dtype=float)
        best = {}
        for i, t in enumerate(col.times):
            if not isinstance(t, datetime) or i >= vals.size or not np.isfinite(vals[i]):
                continue
            delta = (t - origin).total_seconds() / step
            idx = int(round(delta))
            if idx < 0:
                continue
            dist = abs(delta - idx)
            prev = best.get(idx)
            if prev is None or dist < prev[0]:
                best[idx] = (dist, float(vals[i]))
        if best:
            maxIndex = max(maxIndex, max(best))
        binned[col.key] = best

    length = maxIndex + 1
    if length > MAX_GRID_STEPS:
        return None, "Time span is too long for this step, so Regression did not fit."

    columnsOut = {}
    for col in columns:
        arr = np.full(length, np.nan, dtype=float)
        for idx, (_dist, val) in binned.get(col.key, {}).items():
            if 0 <= idx < length:
                arr[idx] = val
        columnsOut[col.key] = arr
    return Grid(origin, step, length, columnsOut), None


def shiftDisplay(values, lagSteps: int) -> np.ndarray:
    """
    Move a series by `lagSteps` so it sits on the target.

    Negative lag (predictor leads): the value from t+lag is drawn at t.
    out[t] = src[t + lagSteps].
    """
    src = np.asarray(values, dtype=float)
    n = int(src.size)
    out = np.full(n, np.nan, dtype=float)
    k = int(lagSteps)
    if n == 0:
        return out
    if k == 0:
        return src.copy()
    if k > 0:
        out[: n - k] = src[k:]
        return out
    shift = -k
    if shift < n:
        out[shift:] = src[: n - shift]
    return out
