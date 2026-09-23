# Engine checks for lagged regression. No Qt.
# Run from the repo root: python tests/test_regression.py

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.regression.cliRegression import main as cliMain
from core.regression.fitRegression import SeriesColumn, fitColumns


def column(key, label, col, values, step=900, start=None):
    start = start or datetime(2024, 6, 1)
    values = np.asarray(values, dtype=float)
    times = [start + timedelta(seconds=i * step) for i in range(values.size)]
    return SeriesColumn(key, label, col, times, values)


def _fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def test_two_predictor():
    rng = np.random.default_rng(0)
    n = 960  # 10 days of 15-minute data
    a = rng.normal(size=n)
    d = rng.normal(size=n)
    noise = rng.normal(size=n)  # dead column, must be dropped
    y = np.full(n, np.nan)
    for t in range(n):
        ta = t - 3
        td = t + 2
        if 0 <= ta < n and 0 <= td < n:
            y[t] = 1.037 * a[ta] + 0.214 * d[td] + 8.6
    cols = [
        column("A", "upstream", 0, a),
        column("D", "side", 3, d),
        column("E", "noise", 4, noise),
        column("C", "target", 2, y),
    ]
    result, err = fitColumns(cols, 3)
    if err:
        return _fail("two_predictor", err)
    keys = [p.key for p in result.predictors]
    if keys != ["A", "D"]:
        return _fail("two_predictor", f"predictors {keys}")
    byKey = {p.key: p for p in result.predictors}
    if byKey["A"].lagSteps != -3 or byKey["D"].lagSteps != 2:
        return _fail("two_predictor", f"lags {byKey['A'].lagSteps} {byKey['D'].lagSteps}")
    if abs(byKey["A"].coef - 1.037) > 1e-6 or abs(byKey["D"].coef - 0.214) > 1e-6:
        return _fail("two_predictor", f"coefs {byKey['A'].coef} {byKey['D'].coef}")
    if abs(result.intercept - 8.6) > 1e-6:
        return _fail("two_predictor", f"intercept {result.intercept}")
    if "1.037*A" not in result.equationText or "0.214*D" not in result.equationText:
        return _fail("two_predictor", result.equationText)
    if "[t" in result.equationText or result.copyText != result.equationText:
        return _fail("two_predictor", result.copyText)
    if "copy:" in result.labelText:
        return _fail("two_predictor", result.labelText)
    if "E" in result.copyText:
        return _fail("two_predictor", "noise column kept")
    if result.warnings:
        return _fail("two_predictor", result.warnings)
    if "-3 steps" not in result.labelText or "-45 min" not in result.labelText:
        return _fail("two_predictor", result.labelText)
    if "+2 steps" not in result.labelText or "+30 min" not in result.labelText:
        return _fail("two_predictor", result.labelText)
    # Aligned: value drawn at t equals source at t+lag.
    aligned = {s.key: s for s in result.aligned}
    shown = aligned["A"].values
    if not np.isclose(shown[10], a[10 - 3]):
        return _fail("two_predictor", f"aligned A[10]={shown[10]} src={a[7]}")
    print("ok two_predictor")
    return 0


def test_single_positive_lag():
    rng = np.random.default_rng(1)
    n = 800
    x = rng.normal(size=n)
    y = np.full(n, np.nan)
    for t in range(n):
        j = t + 4
        if j < n:
            y[t] = 2.0 * x[j] - 5.0
    result, err = fitColumns(
        [column("B", "down", 1, x), column("A", "target", 0, y)],
        1,
    )
    if err:
        return _fail("positive_lag", err)
    pred = result.predictors[0]
    if pred.lagSteps != 4 or abs(pred.coef - 2.0) > 1e-6 or abs(result.intercept + 5.0) > 1e-6:
        return _fail("positive_lag", f"lag {pred.lagSteps} coef {pred.coef} b {result.intercept}")
    if result.scatterMode != "lagged":
        return _fail("positive_lag", result.scatterMode)
    if "*B" not in result.equationText or "[t" in result.equationText:
        return _fail("positive_lag", result.equationText)
    if result.copyText != result.equationText:
        return _fail("positive_lag", result.copyText)
    print("ok positive_lag")
    return 0


def test_gaps():
    rng = np.random.default_rng(2)
    n = 700
    x = rng.normal(size=n)
    y = np.full(n, np.nan)
    for t in range(3, n):
        y[t] = 1.5 * x[t - 3] + 8.6
        if t % 7 == 0:
            y[t] = np.nan
    result, err = fitColumns(
        [column("B", "up", 1, x), column("A", "target", 0, y)],
        1,
    )
    if err:
        return _fail("gaps", err)
    pred = result.predictors[0]
    if pred.lagSteps != -3 or abs(pred.coef - 1.5) > 1e-6:
        return _fail("gaps", f"lag {pred.lagSteps} coef {pred.coef}")
    print("ok gaps")
    return 0


def test_zero_lag():
    rng = np.random.default_rng(3)
    n = 400
    x = rng.normal(size=n)
    y = 0.5 * x + 4.0
    result, err = fitColumns(
        [column("A", "same", 0, x), column("B", "target", 1, y)],
        1,
    )
    if err:
        return _fail("zero_lag", err)
    if result.predictors[0].lagSteps != 0:
        return _fail("zero_lag", result.predictors[0].lagSteps)
    if "[t" in result.equationText:
        return _fail("zero_lag", result.equationText)
    if result.copyText != result.equationText or result.equationText != "Y = 0.5*A + 4":
        return _fail("zero_lag", result.copyText)
    print("ok zero_lag")
    return 0


def test_unrelated_refuses():
    rng = np.random.default_rng(4)
    n = 500
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    result, err = fitColumns(
        [column("A", "x", 0, x), column("B", "y", 1, y)],
        1,
    )
    if result is not None or not err:
        return _fail("unrelated", "expected refusal")
    print("ok unrelated")
    return 0


def test_too_few_rows():
    rng = np.random.default_rng(5)
    n = 12
    x = rng.normal(size=n)
    y = np.full(n, np.nan)
    for t in range(1, n):
        y[t] = x[t - 1]
    result, err = fitColumns(
        [column("A", "x", 0, x), column("B", "y", 1, y)],
        1,
    )
    if result is not None or not err or "Not enough overlapping rows" not in err:
        return _fail("too_few", err)
    print("ok too_few")
    return 0


def test_weekly_refuses():
    rng = np.random.default_rng(6)
    n = 40
    x = rng.normal(size=n)
    y = np.roll(x, 1)
    y[0] = np.nan
    result, err = fitColumns(
        [column("A", "x", 0, x, step=7 * 86400), column("B", "y", 1, y, step=7 * 86400)],
        1,
    )
    if result is not None or not err or "1 minute" not in err:
        return _fail("weekly", err)
    print("ok weekly")
    return 0


def test_daily_short_warns():
    rng = np.random.default_rng(7)
    n = 25
    x = rng.normal(size=n)
    y = np.full(n, np.nan)
    for t in range(1, n):
        y[t] = 3.0 * x[t - 1] + 2.0
    result, err = fitColumns(
        [column("A", "x", 0, x, step=86400), column("B", "y", 1, y, step=86400)],
        1,
    )
    if err:
        return _fail("daily", err)
    text = " ".join(result.warnings)
    if "30 days" not in text:
        return _fail("daily", result.warnings)
    if result.predictors[0].lagSteps != -1:
        return _fail("daily", result.predictors[0].lagSteps)
    print("ok daily")
    return 0


def test_edge_lag_warns():
    rng = np.random.default_rng(8)
    # 15-minute step, window edge is 12 hours = 48 steps.
    n = 960
    x = rng.normal(size=n)
    lag = 48
    y = np.full(n, np.nan)
    for t in range(lag, n):
        y[t] = x[t - lag] + 1.0
    result, err = fitColumns(
        [column("A", "x", 0, x), column("B", "y", 1, y)],
        1,
    )
    if err:
        return _fail("edge", err)
    if result.predictors[0].lagSteps != -lag:
        return _fail("edge", result.predictors[0].lagSteps)
    if not any("window edge" in w for w in result.warnings):
        return _fail("edge", result.warnings)
    print("ok edge")
    return 0


def test_split_half():
    rng = np.random.default_rng(9)
    n = 800
    x = rng.normal(size=n)
    y = np.full(n, np.nan)
    mid = n // 2
    for t in range(n):
        k = 2 if t < mid else 8
        j = t - k
        if j >= 0:
            y[t] = x[j]
    result, err = fitColumns(
        [column("A", "x", 0, x), column("B", "y", 1, y)],
        1,
    )
    if err:
        return _fail("split", err)
    if result.predictors[0].agrees:
        return _fail("split", "expected split-half disagreement")
    if not any("Split-half" in w for w in result.warnings):
        return _fail("split", result.warnings)
    print("ok split")
    return 0


def test_collinear_sandwich():
    """Upstream and downstream of the same wave both stay in the equation."""
    rng = np.random.default_rng(11)
    n = 500
    upstream = np.zeros(n)
    upstream[0] = rng.normal()
    for t in range(1, n):
        upstream[t] = 0.97 * upstream[t - 1] + 0.15 * rng.normal()
    downstream = np.roll(upstream, 9) + 0.01 * rng.normal(size=n)
    downstream[:9] = np.nan
    target = np.full(n, np.nan)
    for t in range(n):
        tu = t - 3
        td = t + 6
        if 0 <= tu < n and 0 <= td < n and np.isfinite(upstream[tu]) and np.isfinite(downstream[td]):
            target[t] = 0.55 * upstream[tu] + 0.45 * downstream[td] + 2.0
    result, err = fitColumns(
        [
            column("A", "upstream", 0, upstream, step=3600),
            column("B", "target", 1, target, step=3600),
            column("C", "downstream", 2, downstream, step=3600),
        ],
        1,
    )
    if err:
        return _fail("sandwich", err)
    keys = [p.key for p in result.predictors]
    if keys != ["A", "C"]:
        return _fail("sandwich", f"{keys} {result.equationText}")
    print("ok sandwich", result.equationText)
    return 0


def test_column_letters_follow_insert_and_move():
    from core.Formula import remapFormulaColumns, shiftFormulaColumns
    inserted = shiftFormulaColumns("=0.5*D1+A1", 3, 1)
    if inserted != "=0.5*E1+A1":
        return _fail("letters", inserted)
    # D (index 3) moves one slot right; A stays.
    moved = remapFormulaColumns("=0.5*D1+A1", {0: 0, 1: 1, 2: 2, 3: 4, 4: 3})
    if moved != "=0.5*E1+A1":
        return _fail("letters", moved)
    print("ok letters")
    return 0


def test_lag_fill_starts_on_row_4():
    """A lag -3 and C lag +6, written on row 4 as A1 and C10."""
    from core.Formula import formulaShifted
    formula = "=0.532*A1+0.466*C10+3.516"
    anchor = 3  # row 4, 0-based
    n = 20
    if formulaShifted(formula, 0, 0 - anchor, rowCount=n) is not None:
        return _fail("lagfill", "row 1 should stay blank")
    if formulaShifted(formula, 0, anchor - anchor, rowCount=n) != formula:
        return _fail("lagfill", formulaShifted(formula, 0, 0, rowCount=n))
    nxt = formulaShifted(formula, 0, 4 - anchor, rowCount=n)
    if nxt != "=0.532*A2+0.466*C11+3.516":
        return _fail("lagfill", nxt)
    if formulaShifted(formula, 0, 14 - anchor, rowCount=n) is not None:
        return _fail("lagfill", "row past C should stay blank")
    print("ok lagfill")
    return 0


def test_formula_keeps_a1():
    from core.Formula import templateAtRowZero
    if templateAtRowZero("=1.037*B1+0.214*D1+8.6", 8) != "=1.037*B1+0.214*D1+8.6":
        return _fail("formula", templateAtRowZero("=1.037*B1+0.214*D1+8.6", 8))
    if templateAtRowZero("=A6+B12", 5) != "=A1+B7":
        return _fail("formula", templateAtRowZero("=A6+B12", 5))
    print("ok formula")
    return 0


def test_cli():
    rng = np.random.default_rng(10)
    n = 400
    x = rng.normal(size=n)
    y = np.full(n, np.nan)
    start = datetime(2024, 6, 1)
    lines = ["timestamp,B,Y"]
    for i in range(n):
        if i >= 3:
            y[i] = 1.25 * x[i - 3] + 2.0
        ts = (start + timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M:%S")
        yCell = "" if not np.isfinite(y[i]) else f"{y[i]:.6f}"
        lines.append(f"{ts},{x[i]:.6f},{yCell}")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "series.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cliMain([path, "--target", "Y"])
        if code != 0:
            return _fail("cli", f"exit {code}: {buf.getvalue()}")
        text = buf.getvalue()
        if "Y = 1.25*B + 2" not in text or "[t" in text.splitlines()[0]:
            return _fail("cli", text)
    print("ok cli")
    return 0


def main():
    failed = 0
    for fn in (
        test_two_predictor,
        test_single_positive_lag,
        test_gaps,
        test_zero_lag,
        test_unrelated_refuses,
        test_too_few_rows,
        test_weekly_refuses,
        test_daily_short_warns,
        test_edge_lag_warns,
        test_split_half,
        test_collinear_sandwich,
        test_column_letters_follow_insert_and_move,
        test_lag_fill_starts_on_row_4,
        test_formula_keeps_a1,
        test_cli,
    ):
        failed += fn()
    if failed:
        print(f"{failed} failed")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
