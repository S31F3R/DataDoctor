# QueryFlags.py
# Per-item Overlay / Delta / Raw / QAQC flags on the Query list.
#
# Checkboxes bulk-flag every current row and set the default for new rows.
# Right-click toggles one (or the selection) without changing that default.
# Overlay/delta pairing is consecutive flagged neighbors in list order:
#   flagged, unflagged, flagged, flagged  →  first stays flagged but unpaired
#   (unhighlighted); the next two are primary/secondary.

from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QPalette
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QMenu

FLAG_KEYS = ("overlay", "delta", "raw", "qaqc")
FLAG_LABELS = {
    "overlay": "Overlay",
    "delta": "Display Deltas",
    "raw": "Raw Data",
    "qaqc": "QAQC Data",
}
ITEM_ROLE = int(Qt.ItemDataRole.UserRole)
KIND_SERIES = "series"
KIND_EQUATION = "equation"
EQUATION_INTERVAL = "EQUATION"
# Legacy third field on old saves; new saves store the column header there.
EQUATION_DATABASE = "custom"
EQUATION_DEFAULT_HEADER = "Column"


def newItemId() -> str:
    return uuid.uuid4().hex[:12]


def emptyFlags() -> dict:
    return {k: False for k in FLAG_KEYS}


def normalizeFlags(raw=None, defaults=None) -> dict:
    base = emptyFlags()
    if defaults:
        for k in FLAG_KEYS:
            if k in defaults:
                base[k] = bool(defaults[k])
    if isinstance(raw, dict):
        for k in FLAG_KEYS:
            if k in raw:
                base[k] = bool(raw[k])
    return base


def defaultFlagsFromCheckboxes(chkbOverlay=None, chkbDelta=None, chkbRawData=None, chkbQAQC=None):
    return {
        "overlay": bool(chkbOverlay.isChecked()) if chkbOverlay is not None else False,
        "delta": bool(chkbDelta.isChecked()) if chkbDelta is not None else False,
        "raw": bool(chkbRawData.isChecked()) if chkbRawData is not None else False,
        "qaqc": bool(chkbQAQC.isChecked()) if chkbQAQC is not None else False,
    }


def itemPayload(item) -> dict:
    if item is None:
        return {}
    data = item.data(ITEM_ROLE)
    return dict(data) if isinstance(data, dict) else {}


def setItemPayload(item, payload: dict):
    if item is None:
        return
    item.setData(ITEM_ROLE, dict(payload or {}))


def ensurePayload(item, defaults=None) -> dict:
    data = itemPayload(item)
    if not data:
        data = {
            "id": newItemId(),
            "kind": KIND_SERIES,
            "flags": normalizeFlags(defaults=defaults),
        }
        setItemPayload(item, data)
        return data
    data.setdefault("id", newItemId())
    data.setdefault("kind", KIND_SERIES)
    data["flags"] = normalizeFlags(data.get("flags"), defaults)
    setItemPayload(item, data)
    return data


def itemFlags(item) -> dict:
    return normalizeFlags((itemPayload(item) or {}).get("flags"))


def setItemFlags(item, flags, defaults=None):
    data = ensurePayload(item, defaults)
    data["flags"] = normalizeFlags(flags, defaults)
    setItemPayload(item, data)


def itemKind(item) -> str:
    kind = (itemPayload(item) or {}).get("kind") or KIND_SERIES
    text = item.text().strip() if item is not None else ""
    if kind == KIND_EQUATION or _textIsEquation(text):
        return KIND_EQUATION
    return KIND_SERIES


def itemIdOf(item) -> str:
    return str(ensurePayload(item).get("id") or newItemId())


def _textIsEquation(text: str) -> bool:
    s = (text or "").strip()
    if s.startswith("="):
        return True
    parts = s.split("|")
    if not parts:
        return False
    if parts[0].upper() == EQUATION_INTERVAL:
        return True
    return len(parts) >= 3 and parts[1].upper() == EQUATION_INTERVAL


def equationHeader(header) -> str:
    """Third query-list field for equations: the column header, not 'custom'."""
    label = (header or "").strip().replace("|", " ").replace("\n", " ").replace("\r", " ")
    if not label or label.lower() == EQUATION_DATABASE:
        return EQUATION_DEFAULT_HEADER
    return label


def parseListText(text: str):
    """
    Series: 'dataID|interval|database'.
    Equation display: 'EQUATION|<header>'.
    Legacy: '=<formula>|EQUATION|<header>' or '<formula>|EQUATION|<header>'.
    Returns (kind, dataId_or_formula, interval, database_or_header) or None.
    """
    s = (text or "").strip()
    if not s:
        return None
    if s.startswith("="):
        parts = s.split("|", 2)
        formula = parts[0]
        label = parts[2] if len(parts) > 2 else ""
        return (KIND_EQUATION, formula, EQUATION_INTERVAL, equationHeader(label))
    parts = s.split("|")
    if len(parts) == 2 and parts[0].upper() == EQUATION_INTERVAL:
        return (KIND_EQUATION, "", EQUATION_INTERVAL, equationHeader(parts[1]))
    if len(parts) != 3:
        return None
    dataId, interval, database = parts
    if dataId.upper() == EQUATION_INTERVAL:
        return (KIND_EQUATION, "", EQUATION_INTERVAL, equationHeader(interval if interval.upper() != EQUATION_INTERVAL else database))
    if interval.upper() == EQUATION_INTERVAL:
        return (KIND_EQUATION, dataId, EQUATION_INTERVAL, equationHeader(database))
    return (KIND_SERIES, dataId, interval, database)


def equationListText(formula: str, header: str | None = None) -> str:
    """Visible query-list / Quick Look text: EQUATION|<header> (formula is payload-only)."""
    return f"{EQUATION_INTERVAL}|{equationHeader(header)}"


def formulaIsBroken(formula) -> bool:
    return "#REF!" in str(formula or "")


def seriesFlagsFromQueryItem(queryItem) -> dict:
    """Flags from a lastQueryItems entry (tuple or dict)."""
    if isinstance(queryItem, dict):
        return normalizeFlags(queryItem.get("flags"))
    if isinstance(queryItem, (tuple, list)) and len(queryItem) > 5:
        return normalizeFlags(queryItem[5])
    return emptyFlags()


def isEquationQueryItem(queryItem) -> bool:
    if isinstance(queryItem, dict):
        return (queryItem.get("kind") or KIND_SERIES) == KIND_EQUATION
    if isinstance(queryItem, (tuple, list)) and len(queryItem) > 2:
        if str(queryItem[1]).upper() == EQUATION_INTERVAL:
            return True
        if str(queryItem[0]).startswith("="):
            return True
    return False


def queryItemDatabase(queryItem) -> str:
    if isinstance(queryItem, dict):
        return str(queryItem.get("database") or "")
    if isinstance(queryItem, (tuple, list)) and len(queryItem) > 2:
        return str(queryItem[2] or "")
    return ""


def _queryItemHasFlags(queryItem) -> bool:
    if isinstance(queryItem, dict) and "flags" in queryItem:
        return True
    if isinstance(queryItem, (tuple, list)) and len(queryItem) > 5:
        return True
    return False


def databaseQueryable(database, isInternal: bool) -> bool:
    """False when this source cannot be queried in the current mode."""
    db = str(database or "").strip().upper()
    if db == "AQUARIUS" and not isInternal:
        return False
    return True


def itemQueryable(queryItem, isInternal: bool) -> bool:
    if isEquationQueryItem(queryItem):
        return True
    return databaseQueryable(queryItemDatabase(queryItem), isInternal)


def _cloneItemWithFlags(queryItem, flags):
    flags = normalizeFlags(flags)
    if isinstance(queryItem, dict):
        out = dict(queryItem)
        out["flags"] = flags
        return out
    if isinstance(queryItem, (tuple, list)):
        lst = list(queryItem)
        while len(lst) < 6:
            lst.append(None)
        lst[5] = flags
        return tuple(lst)
    return queryItem


def dropUnqueryablePairMembers(queryItems, isInternal, overlayChecked=False, deltaChecked=False):
    """
    Public queries cannot fetch Aquarius. If an overlay/delta pair includes a
    series that will not be queried, do not overlay that pair — keep the
    remaining series as a normal column. Neighbors must not re-pair with the
    next queryable ID.

    Returns a new list (unqueryable series removed; flags rewritten on copies).
    """
    items = list(queryItems or [])
    n = len(items)
    if n == 0:
        return items

    def flagAt(idx, key, bulk):
        it = items[idx]
        if isEquationQueryItem(it):
            return False
        if _queryItemHasFlags(it):
            return bool(seriesFlagsFromQueryItem(it).get(key))
        return bool(bulk)

    overlayFlags = [flagAt(i, "overlay", overlayChecked) for i in range(n)]
    deltaFlags = [flagAt(i, "delta", deltaChecked) for i in range(n)]
    queryable = [itemQueryable(it, isInternal) for it in items]

    overlayKeep = set()
    deltaKeep = set()
    overlayPairs, _ = consecutiveFlagPairs(overlayFlags)
    deltaPairs, _ = consecutiveFlagPairs(deltaFlags)
    for p, s in overlayPairs:
        if queryable[p] and queryable[s]:
            overlayKeep.add(p)
            overlayKeep.add(s)
    for p, s in deltaPairs:
        if queryable[p] and queryable[s]:
            deltaKeep.add(p)
            deltaKeep.add(s)

    kept = []
    for i, it in enumerate(items):
        if not queryable[i]:
            continue
        flags = dict(seriesFlagsFromQueryItem(it))
        if not _queryItemHasFlags(it):
            flags["overlay"] = overlayFlags[i]
            flags["delta"] = deltaFlags[i]
        # Only pairs that can actually be queried stay overlay/delta.
        # Unpaired flags would otherwise re-pair with the next neighbor
        # after an unqueryable ID is dropped.
        flags["overlay"] = i in overlayKeep
        flags["delta"] = i in deltaKeep
        kept.append(_cloneItemWithFlags(it, flags))
    return kept


def consecutiveFlagPairs(flagList):
    """
    Walk flags in order. Two True neighbors become a pair; a True next to
    False (or end) is unpaired. False entries are skipped (not in a pair).
    Returns (pairs, unpaired) where pairs is [(i, i+1), ...] and unpaired [i, ...].
    """
    pairs = []
    unpaired = []
    n = len(flagList)
    i = 0
    while i < n:
        if not flagList[i]:
            i += 1
            continue
        if i + 1 < n and flagList[i + 1]:
            pairs.append((i, i + 1))
            i += 2
        else:
            unpaired.append(i)
            i += 1
    return pairs, unpaired


def pairRoleForIndex(flagList, index):
    """
    'primary', 'secondary', or None (unflagged or flagged-but-unpaired).
    """
    if index < 0 or index >= len(flagList) or not flagList[index]:
        return None
    pairs, _unpaired = consecutiveFlagPairs(flagList)
    for p, s in pairs:
        if index == p:
            return "primary"
        if index == s:
            return "secondary"
    return None


def pairColors(widget=None):
    """
    Query-list overlay primary/secondary colors.
    Options → Appearance overrides (overlayPrimaryFlag / overlaySecondaryFlag)
    win when set; otherwise derive from the theme Highlight color.
    """
    try:
        from core import TableColors
        p = TableColors.qcolor("overlayPrimaryFlag", "fg")
        s = TableColors.qcolor("overlaySecondaryFlag", "fg")
        if p is not None and s is not None:
            return p, s
    except Exception:
        pass
    pal = None
    if widget is not None:
        pal = widget.palette()
    if pal is None:
        app = QApplication.instance()
        pal = app.palette() if app is not None else QPalette()
    base = pal.color(QPalette.ColorRole.Base)
    text = pal.color(QPalette.ColorRole.Text)
    highlight = pal.color(QPalette.ColorRole.Highlight)
    primary = QColor(highlight)
    if _contrastRatio(primary, base) < 2.4:
        primary = QColor(text)
    secondary = _shiftHue(primary, 110)
    if _contrastRatio(secondary, base) < 2.4 or _colorDistance(secondary, primary) < 40:
        secondary = _shiftHue(primary, -90)
    if _contrastRatio(secondary, base) < 2.4:
        secondary = QColor(text)
        secondary.setHsv(
            (secondary.hue() + 80) % 360,
            max(secondary.saturation(), 90),
            min(255, secondary.value() + 20) if secondary.value() < 200 else max(80, secondary.value() - 40),
        )
    return primary, secondary


def _shiftHue(color: QColor, degrees: int) -> QColor:
    c = QColor(color)
    h, s, v, a = c.getHsv()
    if h < 0:
        h = 200
    s = max(90, min(255, s if s > 40 else 140))
    v = max(90, min(230, v if v > 60 else 180))
    out = QColor()
    out.setHsv((h + degrees) % 360, s, v, a if a >= 0 else 255)
    return out


def _relLuma(c: QColor) -> float:
    def lin(x):
        x = x / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def _contrastRatio(a: QColor, b: QColor) -> float:
    l1, l2 = _relLuma(a), _relLuma(b)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _colorDistance(a: QColor, b: QColor) -> float:
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())


def recolorQueryList(listWidget):
    """Color paired overlay primary/secondary; leave unpaired/unflagged as default."""
    if listWidget is None:
        return
    n = listWidget.count()
    overlayFlags = []
    for i in range(n):
        item = listWidget.item(i)
        if itemKind(item) == KIND_EQUATION:
            overlayFlags.append(False)
        else:
            overlayFlags.append(bool(itemFlags(item).get("overlay")))
    primary, secondary = pairColors(listWidget)
    defaultFg = listWidget.palette().color(QPalette.ColorRole.Text)
    brokenFg = _equationBrokenColor(listWidget)
    for i in range(n):
        item = listWidget.item(i)
        if item is None:
            continue
        if itemKind(item) == KIND_EQUATION:
            payload = itemPayload(item)
            if formulaIsBroken(payload.get("formula")) or formulaIsBroken(item.text()):
                item.setForeground(QBrush(brokenFg))
            else:
                item.setForeground(QBrush(defaultFg))
            continue
        role = pairRoleForIndex(overlayFlags, i)
        if role == "primary":
            item.setForeground(QBrush(primary))
        elif role == "secondary":
            item.setForeground(QBrush(secondary))
        else:
            item.setForeground(QBrush(defaultFg))


def _equationBrokenColor(widget=None):
    """Red that stays readable on light and dark Base."""
    pal = widget.palette() if widget is not None else None
    if pal is None:
        app = QApplication.instance()
        pal = app.palette() if app is not None else QPalette()
    base = pal.color(QPalette.ColorRole.Base)
    if _relLuma(base) < 0.45:
        return QColor(255, 90, 90)
    return QColor(178, 0, 0)


def applyFlagToAll(listWidget, key: str, value: bool):
    if listWidget is None or key not in FLAG_KEYS:
        return
    for i in range(listWidget.count()):
        item = listWidget.item(i)
        if itemKind(item) == KIND_EQUATION:
            continue
        flags = itemFlags(item)
        flags[key] = bool(value)
        setItemFlags(item, flags)
    recolorQueryList(listWidget)


def makeListItem(text: str, flags=None, kind=KIND_SERIES, extra=None) -> QListWidgetItem:
    item = QListWidgetItem(text)
    payload = {
        "id": newItemId(),
        "kind": kind,
        "flags": normalizeFlags(flags),
    }
    if extra:
        payload.update(extra)
    setItemPayload(item, payload)
    return item


def serializeItem(item) -> dict:
    """Quick Look entry (object form)."""
    data = ensurePayload(item)
    flags = normalizeFlags(data.get("flags"))
    kind = itemKind(item)
    text = item.text().strip() if item is not None else ""
    out = {
        "kind": kind,
        "q": text,
        "overlay": flags["overlay"],
        "delta": flags["delta"],
        "raw": flags["raw"],
        "qaqc": flags["qaqc"],
        "id": data.get("id") or newItemId(),
    }
    if kind == KIND_EQUATION:
        parsed = parseListText(text)
        formula = data.get("formula") or (parsed[1] if parsed else text)
        header = data.get("header") or (parsed[3] if parsed else EQUATION_DEFAULT_HEADER)
        out["formula"] = formula
        out["header"] = equationHeader(header)
        out["q"] = equationListText(formula, header)
        if data.get("refs"):
            out["refs"] = list(data["refs"])
    return out


def parseSavedEntry(entry, defaultFlags=None) -> dict | None:
    """
    Normalize a Quick Look queries[] element to
    {kind, text, flags, id, formula?, header?, refs?}.
    Legacy strings inherit defaultFlags (the file's top-level checkboxes).
    """
    defaults = normalizeFlags(defaults=defaultFlags)
    if isinstance(entry, str):
        text = entry.strip()
        parsed = parseListText(text)
        if parsed is None:
            return None
        kind, dataId, interval, database = parsed
        if kind == KIND_EQUATION:
            text = equationListText(dataId, database)
            return {
                "kind": kind,
                "text": text,
                "flags": emptyFlags(),
                "id": newItemId(),
                "formula": dataId,
                "header": equationHeader(database),
            }
        text = f"{dataId}|{interval}|{database}"
        return {
            "kind": kind,
            "text": text,
            "flags": dict(defaults),
            "id": newItemId(),
            "formula": None,
        }
    if not isinstance(entry, dict):
        return None
    kind = entry.get("kind") or KIND_SERIES
    text = (entry.get("q") or entry.get("text") or "").strip()
    formula = entry.get("formula")
    header = entry.get("header")
    flags = emptyFlags()
    if kind == KIND_EQUATION or (formula and str(formula).startswith("=")) or _textIsEquation(text):
        kind = KIND_EQUATION
        parsed = parseListText(text) if text else None
        formula = formula or (parsed[1] if parsed else text)
        if not header and parsed:
            header = parsed[3]
        header = equationHeader(header)
        text = equationListText(formula, header)
        flags = emptyFlags()
    else:
        if not text:
            dataId = entry.get("dataID") or entry.get("dataId")
            interval = entry.get("interval")
            database = entry.get("database")
            if dataId and interval and database:
                text = f"{dataId}|{interval}|{database}"
        parsed = parseListText(text)
        if parsed is None:
            return None
        kind, dataId, interval, database = parsed
        if kind == KIND_EQUATION:
            header = equationHeader(header or database)
            text = equationListText(dataId, header)
            formula = dataId
            flags = emptyFlags()
        else:
            text = f"{dataId}|{interval}|{database}"
            flags = normalizeFlags(entry, defaults)
            if isinstance(entry.get("flags"), dict):
                flags = normalizeFlags(entry.get("flags"), defaults)
    return {
        "kind": kind,
        "text": text,
        "flags": flags,
        "id": entry.get("id") or newItemId(),
        "formula": formula,
        "header": header,
        "refs": entry.get("refs"),
    }


class StickyFlagMenu(QMenu):
    """Ctrl+click toggles a checkable action without closing the menu."""

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        action = self.actionAt(event.pos())
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if action is not None and not action.isSeparator() and ctrl:
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)
