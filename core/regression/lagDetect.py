# lagDetect.py
# Pre-whitened cross-correlation to pick one lag per predictor.

from __future__ import annotations

import numpy as np

# A lag needs this many overlapping pre-whitened pairs before it can win.
MIN_PAIRS = 20
# Split-half check is softer; a half with fewer pairs is "no vote".
MIN_HALF_PAIRS = 12
# |ρ| below this is not a peak (flat CCF).
MIN_PEAK_RHO = 0.1


def pearson(a, b):
    """(rho, count). rho is NaN when the pair count is under 3 or either side is flat."""
    aa = np.asarray(a, dtype=float)
    bb = np.asarray(b, dtype=float)
    mask = np.isfinite(aa) & np.isfinite(bb)
    count = int(mask.sum())
    if count < 3:
        return np.nan, count
    x = aa[mask]
    y = bb[mask]
    x = x - x.mean()
    y = y - y.mean()
    dx = float(np.sqrt(np.dot(x, x)))
    dy = float(np.sqrt(np.dot(y, y)))
    if dx <= 1e-18 or dy <= 1e-18:
        return np.nan, count
    return float(np.dot(x, y) / (dx * dy)), count


def ar1Phi(values) -> float:
    """AR(1) slope on consecutive finite pairs, clipped to (-0.99, 0.99)."""
    v = np.asarray(values, dtype=float)
    if v.size < 3:
        return 0.0
    a = v[:-1]
    b = v[1:]
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 5:
        return 0.0
    x = a[mask]
    y = b[mask]
    x = x - float(x.mean())
    y = y - float(y.mean())
    var = float(np.dot(x, x))
    if var <= 1e-18:
        return 0.0
    phi = float(np.dot(x, y) / var)
    if phi > 0.99:
        return 0.99
    if phi < -0.99:
        return -0.99
    return phi


def prewhiten(values, phi: float) -> np.ndarray:
    """y'[t] = y[t] - φ y[t-1]. Index 0 and any gap stay NaN."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan, dtype=float)
    if v.size < 2:
        return out
    prev = v[:-1]
    cur = v[1:]
    mask = np.isfinite(prev) & np.isfinite(cur)
    out[1:][mask] = cur[mask] - float(phi) * prev[mask]
    return out


def lagMaxSeconds(stepSeconds: float) -> float:
    """
    Default CCF window so 1-minute data does not scan a week of lags.

    1–5 min → 6 h; 6–15 min → 12 h; 16–60 min → 24 h;
    longer than an hour and shorter than a day → 3 d; 1 day → 14 d.
    """
    step = float(stepSeconds)
    if step <= 5 * 60:
        return 6 * 3600.0
    if step <= 15 * 60:
        return 12 * 3600.0
    if step <= 60 * 60:
        return 24 * 3600.0
    if step < 86400.0 * 0.98:
        return 3 * 86400.0
    return 14 * 86400.0


def lagMaxSteps(stepSeconds: float) -> int:
    window = lagMaxSeconds(stepSeconds)
    return max(1, int(round(window / float(stepSeconds))))


def _corrAtLag(y, x, k: int, minPairs: int):
    """corr(y[t], x[t+k]). None when there are not enough finite pairs."""
    n = int(y.size)
    if abs(k) >= n:
        return None
    if k >= 0:
        yv = y[: n - k] if k else y
        xv = x[k:]
    else:
        yv = y[-k:]
        xv = x[: n + k]
    rho, count = pearson(yv, xv)
    if count < minPairs or not np.isfinite(rho):
        return None
    return float(rho), count


def _bestLag(y, x, kMax: int, minPairs: int):
    """
    (absRho, lagSteps, rho, count) or None.

    Ties go to the smaller |lag|.
    """
    best = None
    for k in range(-kMax, kMax + 1):
        hit = _corrAtLag(y, x, k, minPairs)
        if hit is None:
            continue
        rho, count = hit
        score = abs(rho)
        if best is None or score > best[0] + 1e-12 or (
            abs(score - best[0]) <= 1e-12 and abs(k) < abs(best[1])
        ):
            best = (score, k, rho, count)
    return best


class LagDetection:
    def __init__(self, key, lagSteps, peakRho, pairCount, phi, agrees, pinned, kMax):
        self.key = key
        self.lagSteps = int(lagSteps)
        self.peakRho = float(peakRho)
        self.pairCount = int(pairCount)
        self.phi = float(phi)
        self.agrees = bool(agrees)
        self.pinned = bool(pinned)
        self.kMax = int(kMax)

    @property
    def usable(self) -> bool:
        return self.pairCount >= MIN_PAIRS and abs(self.peakRho) >= MIN_PEAK_RHO


def detectLag(y, x, stepSeconds: float, key: str = "") -> LagDetection | None:
    """
    One lag for predictor x against target y (same grid).

    Pre-whiten both with the predictor's AR(1), then take the CCF peak.
    Sign: negative means the predictor leads (typical upstream).
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if y.size < 3 or x.size != y.size:
        return None
    phi = ar1Phi(x)
    yw = prewhiten(y, phi)
    xw = prewhiten(x, phi)
    kMax = lagMaxSteps(stepSeconds)
    best = _bestLag(yw, xw, kMax, MIN_PAIRS)
    if best is None:
        return None
    _score, lagSteps, rho, count = best

    mid = int(y.size // 2)
    left = _bestLag(yw[:mid], xw[:mid], kMax, MIN_HALF_PAIRS)
    right = _bestLag(yw[mid:], xw[mid:], kMax, MIN_HALF_PAIRS)
    agrees = True
    if left is not None and right is not None and int(left[1]) != int(right[1]):
        agrees = False

    pinned = abs(int(lagSteps)) == kMax
    return LagDetection(key, lagSteps, rho, count, phi, agrees, pinned, kMax)
