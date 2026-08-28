# TableColors.py
# Data-query cell colors (QAQC, overlay, delta, pending upload).
# Defaults can differ by light/dark; user overrides live in user.config.

from __future__ import annotations

from PyQt6.QtGui import QBrush, QColor, QPalette
from PyQt6.QtCore import Qt

from core import Config

# id, label, description, which side the swatch edits (bg | fg | both)
ROWS = (
    ("qaqcMissing", "Missing data",
     "Empty cell whose timestamp is now or earlier (QAQC). Also HDB r_base fallback.",
     "bg"),
    ("qaqcExpectedMin", "Below expected min",
     "Value is less than expectedMin.", "bg"),
    ("qaqcExpectedMax", "Above expected max",
     "Value is greater than expectedMax.", "bg"),
    ("qaqcCutoffMin", "Below cutoff min",
     "Value is less than cuttoffMin.", "bg"),
    ("qaqcCutoffMax", "Above cutoff max",
     "Value is greater than cutoffMax.", "bg"),
    ("qaqcRateOfChange", "Rate of change",
     "Step between adjacent values is greater than rateOfChange.", "bg"),
    ("qaqcEqual", "Consecutive equal",
     "Two adjacent values are equal.", "bg"),
    ("deltaPositive", "Delta positive",
     "Delta column, value greater than zero.", "fg"),
    ("deltaNegative", "Delta negative",
     "Delta column, value less than zero.", "fg"),
    ("overlayMismatch", "Overlay differs",
     "Overlay pair both present but not equal (after the display limiter).", "fg"),
    ("overlaySecondaryOnly", "Overlay secondary only",
     "Secondary has a value, primary does not (auto-marked for upload).", "bg"),
    ("overlayPrimaryOnly", "Overlay primary only",
     "Primary has a value, secondary does not.", "bg"),
    ("editPending", "Pending edit / upload",
     "User edit or overlay fill waiting to upload.", "both"),
    ("uploadOk", "Uploaded this session",
     "Write succeeded this session.", "both"),
)

# Same RGB as the previous hardcoded table paints (both themes).
_SHARED = {
    "qaqcMissing": {"bg": "#64C3F7", "fg": "#000000"},
    "qaqcExpectedMin": {"bg": "#F9F06B", "fg": "#000000"},
    "qaqcExpectedMax": {"bg": "#F9C211", "fg": "#000000"},
    "qaqcCutoffMin": {"bg": "#FFA348", "fg": "#000000"},
    "qaqcCutoffMax": {"bg": "#C01C28", "fg": "#FFFFFF"},
    "qaqcRateOfChange": {"bg": "#F66151", "fg": "#000000"},
    "qaqcEqual": {"bg": "#57E389", "fg": "#000000"},
    "deltaPositive": {"fg": "#FFA500"},
    "deltaNegative": {"fg": "#44A5FF"},
    "overlayMismatch": {"fg": "#FF0000"},
    "overlaySecondaryOnly": {"bg": "#DDA0DD", "fg": "#000000"},
    "overlayPrimaryOnly": {"bg": "#FFB6C1", "fg": "#000000"},
    "editPending": {"bg": "#C2185B", "fg": "#FFFFFF"},
    "uploadOk": {"bg": "#00695C", "fg": "#FFFFFF"},
}

DEFAULTS = {
    "light": {k: dict(v) for k, v in _SHARED.items()},
    "dark": {k: dict(v) for k, v in _SHARED.items()},
}

_overrides: dict = {}


def setOverrides(data) -> None:
    global _overrides
    _overrides = {}
    if not isinstance(data, dict):
        return
    for key, spec in data.items():
        if not isinstance(spec, dict):
            continue
        out = {}
        for part in ("bg", "fg"):
            val = spec.get(part)
            if isinstance(val, str) and val.strip():
                out[part] = val.strip()
        if out:
            _overrides[str(key)] = out


def overrides() -> dict:
    return {k: dict(v) for k, v in _overrides.items()}


def reloadFromConfig(settings=None) -> None:
    if settings is None:
        from core import Utils
        settings = Utils.loadConfig()
    setOverrides(settings.get("tableColors") if isinstance(settings, dict) else None)


def currentThemeName() -> str:
    t = str(getattr(Config, "colorTheme", None) or "system").strip().lower()
    if t in ("light", "dark"):
        return t
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            c = app.palette().color(QPalette.ColorRole.Window)
            if c.lightness() < 128:
                return "dark"
    except Exception:
        pass
    return "light"


def resolved(key: str) -> dict:
    theme = currentThemeName()
    base = dict(DEFAULTS.get(theme, DEFAULTS["light"]).get(key) or {})
    over = _overrides.get(key) or {}
    base.update(over)
    return base


def qcolor(key: str, part: str = "bg"):
    hexVal = resolved(key).get(part)
    if not hexVal:
        return None
    c = QColor(hexVal)
    return c if c.isValid() else None


def applyToItem(item, key: str) -> None:
    if item is None:
        return
    spec = resolved(key)
    bg = spec.get("bg")
    fg = spec.get("fg")
    if bg:
        c = QColor(bg)
        if c.isValid():
            item.setBackground(c)
    if fg:
        c = QColor(fg)
        if c.isValid():
            item.setForeground(c)
            item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(c))


def wikiHex(key: str, part: str) -> str:
    """Default hex for wiki docs (not user overrides)."""
    return (DEFAULTS["light"].get(key) or {}).get(part) or ""
