# Time Lag math for the Plotter. No Qt.
# Run from the repo root: python tests/test_plotLag.py

from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.plotLag import (
    bestPositiveLag,
    chainLag,
    lagClockText,
    maxLagSteps,
    overlapCount,
    pearsonInRange,
    positiveLagSums,
    shiftByLag,
    viewPairScores,
)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def testClock():
    if lagClockText(12, "INSTANT:15") != "12 steps (3:00)":
        return fail("clock", lagClockText(12, "INSTANT:15"))
    if lagClockText(2, "HOUR") != "2 steps (2:00)":
        return fail("clock hour", lagClockText(2, "HOUR"))
    if lagClockText(3, "DAY") != "3 steps (3 days)":
        return fail("clock day", lagClockText(3, "DAY"))
    if lagClockText(1, "DAY") != "1 steps (1 day)":
        return fail("clock one day", lagClockText(1, "DAY"))
    return 0


def testMaxLag():
    if maxLagSteps(2, 100) != 0:
        return fail("short overlap", maxLagSteps(2, 100))
    if maxLagSteps(10, 100) != 3:
        return fail("third of overlap", maxLagSteps(10, 100))
    if maxLagSteps(30, 4) != 4:
        return fail("window cap", maxLagSteps(30, 4))
    return 0


def testShiftAndSums():
    src = np.array([0, 0, 5, 0, 0, 1], dtype=float)
    shifted = shiftByLag(src, 2)
    if not np.isnan(shifted[-1]) or not np.isnan(shifted[-2]):
        return fail("shift tail", shifted)
    if shifted[0] != 5 or shifted[3] != 1:
        return fail("shift body", shifted)
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([0.0, 1.0, 2.0, 3.0])
    sums = positiveLagSums(x, y, 2)
    direct = [
        float(np.sum(x[: 4 - k] * y[k:]))
        for k in range(3)
    ]
    if not np.allclose(sums, direct):
        return fail("lag sums", (sums, direct))
    return 0


def testBestLagAndChain():
    rng = np.random.default_rng(1)
    n = 180
    upstream = rng.normal(size=n)
    mid = np.full(n, np.nan)
    mid[4:] = upstream[:-4]
    down = np.full(n, np.nan)
    down[6:] = mid[:-6]
    lag, score = bestPositiveLag(upstream, mid, 40)
    if lag != 4 or score is None or score < 0.99:
        return fail("pair lag", (lag, score))
    window = maxLagSteps(overlapCount(upstream, down), n)
    recommended, pairLags, lagVsFirst, usedDirect = chainLag(
        [upstream, mid, down], window
    )
    if usedDirect or pairLags != [4, 6] or recommended != 10:
        return fail("chain", (recommended, pairLags, lagVsFirst, usedDirect))
    if lagVsFirst[0] != 0 or lagVsFirst[1] != 4 or lagVsFirst[2] != 10:
        return fail("lag vs first", lagVsFirst)
    flat = np.ones(n)
    flatLag, flatScore = bestPositiveLag(flat, flat, 10)
    if flatLag != 0 or flatScore is not None:
        return fail("flat", (flatLag, flatScore))
    return 0


def testViewPearson():
    x = np.arange(20, dtype=float)
    left = np.arange(20, dtype=float)
    right = left.copy()
    right[10:] = -right[10:]
    full, nFull = pearsonInRange(x, left, right, 0, 19)
    early, nEarly = pearsonInRange(x, left, right, 0, 8)
    if nEarly != 9 or early is None or abs(early - 1) > 1e-9:
        return fail("view early", (early, nEarly))
    if full is None or full > 0.2:
        return fail("view full", (full, nFull))
    late, nLate = pearsonInRange(x, left, right, 15, 16)
    if late is not None or nLate != 2:
        return fail("view short", (late, nLate))
    return 0


def testViewScores():
    x = np.arange(4, dtype=float)
    obs = np.array([1, 2, 3, 4], dtype=float)
    sim = np.array([1, 2, 3, 5], dtype=float)
    scores = viewPairScores(x, obs, sim, 0, 3)
    if scores["n"] != 4:
        return fail("score n", scores)
    if scores["nse"] is None or abs(scores["nse"] - 0.8) > 1e-9:
        return fail("nse", scores["nse"])
    if scores["me"] is None or abs(scores["me"] - 0.25) > 1e-9:
        return fail("me", scores["me"])
    if scores["rmse"] is None or abs(scores["rmse"] - 0.5) > 1e-9:
        return fail("rmse", scores["rmse"])
    if scores["r2"] is None or scores["r2"] <= 0.9:
        return fail("r2", scores["r2"])
    early = viewPairScores(x, obs, sim, 0, 1)
    if early["n"] != 2 or early["r2"] is not None:
        return fail("short window", early)
    return 0


def main():
    errors = 0
    for check in (
        testClock, testMaxLag, testShiftAndSums, testBestLagAndChain,
        testViewPearson, testViewScores,
    ):
        errors += check()
    if errors:
        print(f"{errors} failed")
        return 1
    print("plot lag checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
