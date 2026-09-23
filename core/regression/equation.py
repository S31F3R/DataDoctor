# equation.py
# Regression label text and the Formula-ready clipboard line.
# Lag is commentary only — Formula.py has no lag function.

from __future__ import annotations


def formatNumber(value) -> str:
    """Short decimal, trailing zeros removed. Sign is kept."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    if v != v:  # NaN
        return "0"
    av = abs(v)
    # Numerical dust from an exact fit (RMSE ~ 1e-15) is a zero.
    if av < 1e-6:
        return "0"
    if av >= 100:
        s = f"{v:.2f}"
    elif av >= 1:
        s = f"{v:.3f}"
    elif av >= 0.01:
        s = f"{v:.4f}"
    else:
        s = f"{v:.4g}"
    if "." in s and "e" not in s.lower():
        s = s.rstrip("0").rstrip(".")
    return s


def formatStep(stepSeconds: float) -> str:
    """'1 min', '15 min', '1 hour', '1 day'."""
    s = abs(float(stepSeconds))
    if abs(s - 60.0) < 1:
        return "1 min"
    if abs(s - 3600.0) < 1:
        return "1 hour"
    if abs(s - 86400.0) < 30:
        return "1 day"
    if s < 3600 and abs(s - round(s / 60.0) * 60.0) < 1:
        return f"{int(round(s / 60.0))} min"
    if s < 86400 and abs(s / 3600.0 - round(s / 3600.0)) < 0.02:
        h = int(round(s / 3600.0))
        unit = "hour" if h == 1 else "hours"
        return f"{h} {unit}"
    return formatClock(s).lstrip("+")


def formatClock(seconds: float) -> str:
    """Signed clock span: '-45 min', '+2 hours', '0 min'.

    ASCII hyphen: Press Start and Silkscreen have no U+2212 minus.
    """
    s = float(seconds)
    if abs(s) < 1:
        return "0 min"
    sign = "-" if s < 0 else "+"
    a = abs(s)
    if a < 3600:
        minutes = a / 60.0
        if abs(minutes - round(minutes)) < 0.05:
            return f"{sign}{int(round(minutes))} min"
        return f"{sign}{minutes:.1f} min"
    if a < 86400 * 2:
        hours = a / 3600.0
        if abs(hours - round(hours)) < 0.02:
            h = int(round(hours))
            unit = "hour" if h == 1 else "hours"
            return f"{sign}{h} {unit}"
        return f"{sign}{hours:.1f} hours"
    days = a / 86400.0
    if abs(days - round(days)) < 0.02:
        d = int(round(days))
        unit = "day" if d == 1 else "days"
        return f"{sign}{d} {unit}"
    return f"{sign}{days:.1f} days"


def formatSteps(lagSteps: int) -> str:
    n = int(lagSteps)
    if n < 0:
        return f"-{abs(n)} steps"
    if n > 0:
        return f"+{n} steps"
    return "0 steps"


def renderEquation(terms, intercept) -> tuple[str, str]:
    """
    terms: list of (key, coef, lagSteps) in table order.

    The line is `Y = 1.037*B + 8.6`. Lag lives in the lag section, not in
    [t-3] brackets. Double-click copies this same line.
    """
    eqParts = []
    for i, (key, coef, _lagSteps) in enumerate(terms):
        mag = formatNumber(abs(float(coef)))
        body = str(key)
        if i == 0:
            if float(coef) < 0:
                eqParts.append(f"-{mag}*{body}")
            else:
                eqParts.append(f"{mag}*{body}")
        else:
            if float(coef) < 0:
                eqParts.append(f" - {mag}*{body}")
            else:
                eqParts.append(f" + {mag}*{body}")

    b = float(intercept)
    bText = formatNumber(abs(b))
    if not eqParts:
        equation = f"Y = {formatNumber(b)}"
        return equation, equation
    if b < 0:
        eqParts.append(f" - {bText}")
    elif b > 0:
        eqParts.append(f" + {bText}")
    equation = "Y = " + "".join(eqParts)
    return equation, equation


def renderLabel(equationText, copyText, lagParts, r2, me, rmse, n, stepLabel, warnings) -> str:
    """
    lagParts: list of (key, lagSteps, stepSeconds) for kept predictors.
    copyText is unused; double-click copies the Y line itself.
    """
    lines = [equationText]
    if lagParts:
        bits = []
        for key, lagSteps, stepSeconds in lagParts:
            clock = formatClock(float(lagSteps) * float(stepSeconds))
            bits.append(f"lag {key} = {formatSteps(lagSteps)} ({clock})")
        lines.append("   ".join(bits))
    lines.append(
        f"r² = {formatNumber(r2)}   ME = {formatNumber(me)}   "
        f"RMSE = {formatNumber(rmse)}   N = {int(n)}"
    )
    lines.append(f"dt = {stepLabel}")
    for warning in warnings or []:
        text = str(warning).strip()
        if text:
            lines.append(f"Warning: {text}")
    return "\n".join(lines)


def legendLag(key: str, lagSteps: int, stepSeconds: float) -> str:
    """Aligned legend row: 'B  (-3 steps, -45 min)'."""
    clock = formatClock(float(lagSteps) * float(stepSeconds))
    return f"{key}  ({formatSteps(lagSteps)}, {clock})"
