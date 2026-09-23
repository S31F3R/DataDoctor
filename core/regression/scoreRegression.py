# scoreRegression.py
# r², mean error, RMSE, effective N, blocked cross-check.

from __future__ import annotations

import numpy as np

from core.regression.lagDetect import ar1Phi


def regressionScores(y, yhat):
    """(r2, me, rmse) on paired finite samples. me = mean(Ŷ − Y)."""
    yy = np.asarray(y, dtype=float)
    hh = np.asarray(yhat, dtype=float)
    mask = np.isfinite(yy) & np.isfinite(hh)
    if int(mask.sum()) < 2:
        return 0.0, 0.0, 0.0
    obs = yy[mask]
    fit = hh[mask]
    resid = fit - obs
    me = float(np.mean(resid))
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    ssRes = float(np.sum((obs - fit) ** 2))
    centered = obs - float(np.mean(obs))
    ssTot = float(np.dot(centered, centered))
    if ssTot <= 1e-18:
        r2 = 0.0
    else:
        r2 = 1.0 - ssRes / ssTot
    return float(r2), me, rmse


def effectiveN(y) -> float:
    """
    N_eff ≈ N (1−φ)/(1+φ) from the target AR(1) on the fit rows.

    φ is clamped to [0, 0.999] so a negative sample correlation does not
    inflate N_eff past N.
    """
    v = np.asarray(y, dtype=float)
    v = v[np.isfinite(v)]
    n = int(v.size)
    if n < 3:
        return float(n)
    phi = ar1Phi(v)
    phiPos = min(max(phi, 0.0), 0.999)
    return float(n * (1.0 - phiPos) / (1.0 + phiPos))


def blockedCvR2(design, y, nBlocks: int = 5):
    """
    Contiguous-block cross-check r².

    Train on the other blocks, predict the held-out block, score the pooled
    predictions. None when there are not enough rows to split.
    """
    A = np.asarray(design, dtype=float)
    yy = np.asarray(y, dtype=float)
    n = int(yy.size)
    if n < 30 or A.ndim != 2 or A.shape[0] != n:
        return None
    blocks = 5 if n >= 50 else 3
    if nBlocks:
        blocks = int(nBlocks)
    p = int(A.shape[1])
    if n <= p + blocks:
        return None
    edges = np.linspace(0, n, blocks + 1, dtype=int)
    yhat = np.full(n, np.nan, dtype=float)
    for i in range(blocks):
        a = int(edges[i])
        b = int(edges[i + 1])
        if b <= a:
            continue
        train = np.ones(n, dtype=bool)
        train[a:b] = False
        if int(train.sum()) < p + 2:
            continue
        coef, *_rest = np.linalg.lstsq(A[train], yy[train], rcond=None)
        yhat[a:b] = A[a:b] @ coef
    mask = np.isfinite(yhat) & np.isfinite(yy)
    if int(mask.sum()) < max(10, n // 2):
        return None
    r2, _me, _rmse = regressionScores(yy[mask], yhat[mask])
    return float(r2)
