# plotLag.py
# Time Lag math for the Plotter. No Qt.
# Lag is in query-interval steps, zero or positive (downstream delayed).

from __future__ import annotations

import numpy as np


def stepMinutes(interval):
    """Minutes in one step, or None when the interval is a calendar period."""
    iv = (interval or "").strip().upper()
    if iv == "HOUR":
        return 60
    if iv.startswith("INSTANT:"):
        try:
            n = int(iv.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
        return n if n > 0 else None
    return None


def lagClockText(steps, interval):
    """`12 steps (3:00)` for minute/hour grids; calendar intervals say days/months/years."""
    steps = int(steps or 0)
    iv = (interval or "").strip().upper()
    minutes = stepMinutes(iv)
    if minutes is not None:
        total = minutes * steps
        hours = total // 60
        mins = total % 60
        return f"{steps} steps ({hours}:{mins:02d})"
    if iv == "DAY":
        unit = "day" if steps == 1 else "days"
        return f"{steps} steps ({steps} {unit})"
    if iv == "MONTH":
        unit = "month" if steps == 1 else "months"
        return f"{steps} steps ({steps} {unit})"
    if iv in ("YEAR", "WATER YEAR"):
        unit = "year" if steps == 1 else "years"
        return f"{steps} steps ({steps} {unit})"
    return f"{steps} steps"


def overlapCount(left, right):
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    n = min(a.size, b.size)
    if n <= 0:
        return 0
    return int(np.sum(np.isfinite(a[:n]) & np.isfinite(b[:n])))


def maxLagSteps(nOverlap, stepsInWindow):
    """
    Largest lag the slider may use.
    min(nOverlap - 2, floor(nOverlap / 3), steps in the query). 0 when the
    overlap is too short to correlate.
    """
    nOverlap = int(nOverlap or 0)
    stepsInWindow = int(max(0, stepsInWindow or 0))
    if nOverlap < 3:
        return 0
    return max(0, min(nOverlap - 2, nOverlap // 3, stepsInWindow))


def positiveLagSums(x, y, maxLag):
    """sum_i x[i] * y[i + k] for k = 0..maxLag. Values outside y are zero."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = int(x.size)
    maxLag = int(max(0, maxLag))
    size = 1
    while size < n + maxLag + 1:
        size *= 2
    xF = np.fft.rfft(x, size)
    yF = np.fft.rfft(y, size)
    # corr(y, x)[k] = sum_i y[i + k] * x[i]
    summed = np.fft.irfft(yF * np.conj(xF), size)
    return np.real(summed[: maxLag + 1])


def pearsonByLag(reference, target, maxLag):
    """
    Pearson r at each lag 0..maxLag. Target is delayed by k steps
    (reference[i] lines up with target[i + k]). NaN where the pair is too short
    or one side does not vary.
    """
    a = np.asarray(reference, dtype=float)
    b = np.asarray(target, dtype=float)
    n = min(a.size, b.size)
    a = a[:n]
    b = b[:n]
    if n < 3:
        return np.full(1, np.nan)
    maxLag = int(max(0, min(int(maxLag), n - 3)))
    finiteA = np.isfinite(a)
    finiteB = np.isfinite(b)
    a0 = np.where(finiteA, a, 0.0)
    b0 = np.where(finiteB, b, 0.0)
    maskA = finiteA.astype(float)
    maskB = finiteB.astype(float)
    count = positiveLagSums(maskA, maskB, maxLag)
    sumA = positiveLagSums(a0, maskB, maxLag)
    sumB = positiveLagSums(maskA, b0, maxLag)
    sumAB = positiveLagSums(a0, b0, maxLag)
    sumA2 = positiveLagSums(a0 * a0, maskB, maxLag)
    sumB2 = positiveLagSums(maskA, b0 * b0, maxLag)
    r = np.full(maxLag + 1, np.nan)
    ok = count >= 3
    if not np.any(ok):
        return r
    meanA = np.zeros(maxLag + 1, dtype=float)
    meanB = np.zeros(maxLag + 1, dtype=float)
    meanA[ok] = sumA[ok] / count[ok]
    meanB[ok] = sumB[ok] / count[ok]
    varA = np.zeros(maxLag + 1, dtype=float)
    varB = np.zeros(maxLag + 1, dtype=float)
    varA[ok] = sumA2[ok] / count[ok] - meanA[ok] ** 2
    varB[ok] = sumB2[ok] / count[ok] - meanB[ok] ** 2
    cov = np.zeros(maxLag + 1, dtype=float)
    cov[ok] = sumAB[ok] / count[ok] - meanA[ok] * meanB[ok]
    good = ok & (varA > 1e-12) & (varB > 1e-12)
    r[good] = cov[good] / np.sqrt(varA[good] * varB[good])
    return r


def bestPositiveLag(reference, target, maxLag):
    """(lag, r) with the highest Pearson r on 0..maxLag. (0, None) if none."""
    scores = pearsonByLag(reference, target, maxLag)
    if scores.size == 0 or not np.any(np.isfinite(scores)):
        return 0, None
    lag = int(np.nanargmax(scores))
    return lag, float(scores[lag])


def chainLag(columns, maxLag):
    """
    Consecutive-pair lags, summed as the first→last guess.

    Returns (recommendedLag, pairLags, lagVsFirst, usedDirect).
    lagVsFirst[0] is 0. Intermediates keep their chain lag. The last entry
    is the slider seed: the chain sum, or the direct first-vs-last lag when
    a pair could not be correlated.
    """
    series = [np.asarray(col, dtype=float) for col in (columns or [])]
    n = len(series)
    if n == 0:
        return 0, [], [], False
    if n == 1:
        return 0, [], [0], False
    maxLag = int(max(0, maxLag))
    pairLags = []
    usable = True
    for i in range(n - 1):
        pairOverlap = overlapCount(series[i], series[i + 1])
        limit = maxLagSteps(pairOverlap, maxLag)
        lag, score = bestPositiveLag(series[i], series[i + 1], limit)
        if score is None:
            usable = False
            pairLags.append(0)
        else:
            pairLags.append(int(lag))
    lagVsFirst = [0]
    running = 0
    for lag in pairLags:
        running += int(lag)
        lagVsFirst.append(int(min(max(running, 0), maxLag)))
    if usable:
        recommended = lagVsFirst[-1]
        return recommended, pairLags, lagVsFirst, False
    directLag, directScore = bestPositiveLag(series[0], series[-1], maxLag)
    recommended = int(directLag if directScore is not None else 0)
    lagVsFirst[-1] = recommended
    return recommended, pairLags, lagVsFirst, True


def shiftByLag(values, lag):
    """
    Move a downstream series earlier by `lag` steps so it lines up with upstream.
    value[j + lag] is drawn at index j. Rows that fall off the end stay blank.
    """
    src = np.asarray(values, dtype=float)
    lag = int(lag or 0)
    if lag <= 0:
        return src.copy()
    out = np.full(src.shape, np.nan, dtype=float)
    if lag < src.size:
        out[:-lag] = src[lag:]
    return out


def viewPairScores(xValues, observed, simulated, x0, x1):
    """
    Scores for the visible window. observed is the first series, simulated is
    the lagged last series. r² is the squared Pearson correlation. NSE is
    Nash-Sutcliffe of simulated against observed. ME is mean(simulated − observed).

    Returns n, r2, nse, me, rmse. r2 / nse / me / rmse are None when they
    are not defined (too few points, or a flat observed series for NSE).
    """
    x = np.asarray(xValues, dtype=float)
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)
    n = min(x.size, obs.size, sim.size)
    empty = {"n": 0, "r2": None, "nse": None, "me": None, "rmse": None}
    if n < 1:
        return empty
    x = x[:n]
    obs = obs[:n]
    sim = sim[:n]
    lo = float(min(x0, x1))
    hi = float(max(x0, x1))
    mask = np.isfinite(x) & np.isfinite(obs) & np.isfinite(sim) & (x >= lo) & (x <= hi)
    count = int(np.sum(mask))
    out = {"n": count, "r2": None, "nse": None, "me": None, "rmse": None}
    if count < 3:
        return out
    yy = obs[mask]
    hh = sim[mask]
    resid = hh - yy
    out["me"] = float(np.mean(resid))
    out["rmse"] = float(np.sqrt(np.mean(resid ** 2)))
    if float(np.std(yy)) > 0 and float(np.std(hh)) > 0:
        score = float(np.corrcoef(yy, hh)[0, 1])
        if np.isfinite(score):
            out["r2"] = float(score * score)
    centered = yy - float(np.mean(yy))
    ssTot = float(np.dot(centered, centered))
    ssRes = float(np.dot(resid, resid))
    if ssTot > 1e-18:
        out["nse"] = float(1.0 - ssRes / ssTot)
    return out


def pearsonInRange(xValues, left, right, x0, x1):
    """
    Pearson r of left vs right where both are finite and x is inside [x0, x1].
    None when fewer than 3 points or one side is flat.
    """
    x = np.asarray(xValues, dtype=float)
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    n = min(x.size, a.size, b.size)
    if n < 3:
        return None, 0
    x = x[:n]
    a = a[:n]
    b = b[:n]
    lo = float(min(x0, x1))
    hi = float(max(x0, x1))
    mask = np.isfinite(x) & np.isfinite(a) & np.isfinite(b) & (x >= lo) & (x <= hi)
    count = int(np.sum(mask))
    if count < 3:
        return None, count
    aa = a[mask]
    bb = b[mask]
    if float(np.std(aa)) == 0 or float(np.std(bb)) == 0:
        return None, count
    score = float(np.corrcoef(aa, bb)[0, 1])
    if not np.isfinite(score):
        return None, count
    return score, count
