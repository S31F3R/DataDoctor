# QuickLookDates.py
# Infer and apply relative custom date ranges for Query Quick Looks (#3).

from __future__ import annotations

import json
from datetime import datetime, timedelta

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def intervalMinutes(interval: str) -> int:
    text = str(interval or "").strip().upper()
    if text == "HOUR":
        return 60
    if text.startswith("INSTANT:"):
        try:
            return max(1, int(text.split(":", 1)[1]))
        except (TypeError, ValueError):
            return 1
    if text == "DAY":
        return 1440
    if text == "MONTH":
        return 43200
    if text in ("YEAR", "WATER YEAR"):
        return 525600
    return 60


def finestIntervalMinutes(queryTexts, fallbackInterval="HOUR") -> int:
    mins = []
    for raw in queryTexts or []:
        parts = str(raw).split("|")
        if len(parts) >= 2:
            mins.append(intervalMinutes(parts[1]))
    if not mins:
        return intervalMinutes(fallbackInterval)
    return min(mins)


def nearThresholdMinutes(intervalMin: int) -> int:
    if intervalMin <= 1:
        return 15
    return max(1, intervalMin)


def isNearNow(dt: datetime, now: datetime, intervalMin: int) -> bool:
    if dt is None or now is None:
        return False
    deltaMin = abs((now - dt).total_seconds()) / 60.0
    return deltaMin <= nearThresholdMinutes(intervalMin) + 0.01


def integerDays(start: datetime, end: datetime, intervalMin: int):
    span = (end - start).total_seconds() / 86400.0
    rounded = int(round(span))
    slackMin = max(nearThresholdMinutes(intervalMin), 1)
    if abs(span - rounded) * 1440 <= slackMin + 1:
        return rounded
    return None


def durationMinutes(start: datetime, end: datetime) -> int:
    return int(round((end - start).total_seconds() / 60.0))


def weekdayIndexInMonth(dt: datetime) -> int:
    """1–4 for nth weekday, -1 if last of that weekday in the month."""
    n = 1 + (dt.day - 1) // 7
    nxt = dt + timedelta(days=7)
    if nxt.month != dt.month:
        return -1
    return n


def nthWeekday(year: int, month: int, weekday: int, nth: int, hour: int, minute: int):
    if nth >= 1:
        d = datetime(year, month, 1, hour, minute, 0)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        d += timedelta(weeks=nth - 1)
        if d.month != month:
            return None
        return d
    if month == 12:
        d = datetime(year + 1, 1, 1, hour, minute, 0) - timedelta(days=1)
    else:
        d = datetime(year, month + 1, 1, hour, minute, 0) - timedelta(days=1)
    d = d.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def mostRecentWeekday(now: datetime, weekday: int, hour: int, minute: int) -> datetime:
    d = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    if d > now and d.date() != now.date():
        d -= timedelta(days=7)
    return d


def nextQuarterHour(now: datetime) -> datetime:
    d = now.replace(second=0, microsecond=0)
    rem = d.minute % 15
    add = 15 - rem if rem else 15
    return d + timedelta(minutes=add)


def parseStamp(text):
    if text is None:
        return None
    if isinstance(text, datetime):
        return text.replace(second=0, microsecond=0)
    raw = str(text).strip().replace("T", " ")
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%y %H:%M:00",
        "%m/%d/%y %H:%M",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def displayStamp(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y %H:%M")


def evenIntervalSuggestion(end: datetime, intervalMin: int) -> str:
    if intervalMin <= 0:
        intervalMin = 60
    epoch = datetime(end.year, end.month, end.day)
    minutes = int((end - epoch).total_seconds() // 60)
    snapped = epoch + timedelta(minutes=(minutes // intervalMin) * intervalMin)
    if snapped == end:
        snapped = epoch + timedelta(minutes=((minutes // intervalMin) + 1) * intervalMin)
    return (
        f"Try ending on an even interval, e.g. {displayStamp(snapped)} "
        f"({intervalMin}-minute step)."
    )


def _ruleKey(rule: dict) -> str:
    return json.dumps(rule, sort_keys=True, default=str)


def _add(options: list, seen: set, optionId: str, label: str, rule: dict | None):
    key = optionId if rule is None else _ruleKey(rule)
    if key in seen:
        return
    seen.add(key)
    options.append({"id": optionId, "label": label, "rule": rule})


def _spanLabel(days, minutes) -> str:
    if days is not None and days != 0:
        n = abs(days)
        return f"{n} day(s)"
    if minutes is not None:
        if abs(minutes) >= 1440 and abs(minutes) % 1440 == 0:
            return f"{abs(minutes) // 1440} day(s)"
        if abs(minutes) >= 60 and abs(minutes) % 60 == 0:
            return f"{abs(minutes) // 60} hour(s)"
        return f"{abs(minutes)} minute(s)"
    return "the same duration"


def propose(start: datetime, end: datetime, now: datetime, intervalMin: int) -> list:
    """Candidate interpretations of a custom start/end (plus always-on choices)."""
    options = []
    seen = set()
    if start is None or end is None:
        end = end or now
        start = start or (now - timedelta(hours=72))
    if end < start:
        start, end = end, start
    days = integerDays(start, end, intervalMin)
    minutes = durationMinutes(start, end)
    startNear = isNearNow(start, now, intervalMin)
    endNear = isNearNow(end, now, intervalMin)
    startToday = start.date() == now.date()
    oneMin = intervalMin <= 1
    onQuarter = start.minute in (0, 15, 30, 45)
    spanText = _spanLabel(days, minutes)
    clock = f"{start.hour:02d}:{start.minute:02d}"

    def endSpec():
        if days is not None:
            return {"ref": "start", "offsetDays": days}
        return {"ref": "start", "offsetMinutes": minutes}

    if startNear and end >= now:
        _add(
            options,
            seen,
            "nowForward",
            f"From current time through {spanText} later (same clock)",
            {"kind": "relative", "start": {"ref": "now"}, "end": endSpec()},
        )
    if (startToday or startNear) and not (startNear and start.hour == now.hour and start.minute == now.minute):
        _add(
            options,
            seen,
            "todayClockForward",
            f"Today at {clock} through {spanText} later at {clock}",
            {
                "kind": "relative",
                "start": {
                    "ref": "todayClock",
                    "hour": start.hour,
                    "minute": start.minute,
                },
                "end": endSpec(),
            },
        )
    if oneMin:
        if startNear:
            _add(
                options,
                seen,
                "nowForward",
                f"From current time through {spanText} later (same clock)",
                {"kind": "relative", "start": {"ref": "now"}, "end": endSpec()},
            )
        if onQuarter:
            _add(
                options,
                seen,
                "quarterClock",
                f"Today at {clock} (15-minute clock) through {spanText} later",
                {
                    "kind": "relative",
                    "start": {
                        "ref": "todayClock",
                        "hour": start.hour,
                        "minute": start.minute,
                    },
                    "end": endSpec(),
                },
            )
        _add(
            options,
            seen,
            "nextQuarter",
            f"From the next 15-minute clock time through {spanText} later",
            {"kind": "relative", "start": {"ref": "nextQuarter"}, "end": endSpec()},
        )
    if endNear and start <= now:
        backDays = integerDays(start, now, intervalMin)
        if backDays is not None and backDays != 0:
            _add(
                options,
                seen,
                "pastToNow",
                f"Last {abs(backDays)} day(s) through current time "
                f"(start clock {clock})",
                {
                    "kind": "relative",
                    "start": {
                        "ref": "now",
                        "offsetDays": -abs(backDays),
                        "hour": start.hour,
                        "minute": start.minute,
                    },
                    "end": {"ref": "now"},
                },
            )
        _add(
            options,
            seen,
            "fixedStartToNow",
            f"From {displayStamp(start)} through current time",
            {
                "kind": "relative",
                "start": {"ref": "fixed", "iso": stamp(start)},
                "end": {"ref": "now"},
            },
        )
    if start < now < end:
        back = integerDays(start, now, intervalMin)
        fwd = integerDays(now, end, intervalMin)
        if back is not None and fwd is not None and (back or fwd):
            _add(
                options,
                seen,
                "straddle",
                f"From {abs(back)} day(s) ago through {abs(fwd)} day(s) ahead of now",
                {
                    "kind": "relative",
                    "start": {
                        "ref": "now",
                        "offsetDays": -abs(back),
                        "hour": start.hour,
                        "minute": start.minute,
                    },
                    "end": {"ref": "now", "offsetDays": abs(fwd)},
                },
            )
    dailyish = intervalMin >= 1440 or (days is not None and days % 7 == 0 and days != 0)
    if dailyish and start.date() != now.date():
        wd = start.weekday()
        wdName = WEEKDAYS[wd]
        _add(
            options,
            seen,
            "weeklyWeekday",
            f"Each {wdName} at {clock} through {spanText} later",
            {
                "kind": "relative",
                "start": {
                    "ref": "weekday",
                    "weekday": wd,
                    "hour": start.hour,
                    "minute": start.minute,
                },
                "end": endSpec(),
            },
        )
        nth = weekdayIndexInMonth(start)
        nthWord = {1: "First", 2: "Second", 3: "Third", 4: "Fourth", -1: "Last"}.get(nth)
        if nthWord:
            _add(
                options,
                seen,
                "nthWeekday",
                f"{nthWord} {wdName} of this month at {clock} through {spanText} later",
                {
                    "kind": "relative",
                    "start": {
                        "ref": "nthWeekday",
                        "nth": nth,
                        "weekday": wd,
                        "hour": start.hour,
                        "minute": start.minute,
                    },
                    "end": endSpec(),
                },
            )

    _add(
        options,
        seen,
        "omit",
        "Don't restore dates when this Quick Look is loaded",
        {"kind": "omit"},
    )
    _add(
        options,
        seen,
        "fixed",
        f"Keep these exact dates ({displayStamp(start)} – {displayStamp(end)})",
        {"kind": "fixed", "startDate": stamp(start), "endDate": stamp(end)},
    )
    options.append(
        {
            "id": "cancelAdjust",
            "label": "None of these — cancel so I can adjust the times",
            "rule": None,
        }
    )
    return options


def resolveAnchor(spec: dict, now: datetime, start: datetime | None) -> datetime:
    spec = spec or {}
    ref = str(spec.get("ref") or "now")
    hour = spec.get("hour")
    minute = spec.get("minute")
    offsetDays = int(spec.get("offsetDays") or 0)
    offsetMinutes = int(spec.get("offsetMinutes") or 0)
    extra = timedelta(days=offsetDays, minutes=offsetMinutes)
    if ref == "start":
        base = start or now
        return base + extra
    if ref == "todayClock":
        h = int(hour if hour is not None else now.hour)
        m = int(minute if minute is not None else now.minute)
        return now.replace(hour=h, minute=m, second=0, microsecond=0) + extra
    if ref == "nextQuarter":
        return nextQuarterHour(now) + extra
    if ref == "weekday":
        h = int(hour if hour is not None else 1)
        m = int(minute if minute is not None else 0)
        return mostRecentWeekday(now, int(spec.get("weekday") or 0), h, m) + extra
    if ref == "nthWeekday":
        h = int(hour if hour is not None else 1)
        m = int(minute if minute is not None else 0)
        nth = int(spec.get("nth") or 1)
        wd = int(spec.get("weekday") or 0)
        dt = nthWeekday(now.year, now.month, wd, nth, h, m)
        if dt is None:
            month = now.month - 1
            year = now.year
            if month < 1:
                month = 12
                year -= 1
            dt = nthWeekday(year, month, wd, nth, h, m) or now
        return dt + extra
    if ref == "fixed":
        dt = parseStamp(spec.get("iso")) or now
        return dt + extra
    # now
    dt = now.replace(second=0, microsecond=0)
    if hour is not None:
        dt = dt.replace(hour=int(hour), minute=int(minute or 0))
    return dt + extra


def applyRule(rule: dict | None, now: datetime | None = None):
    """
    Returns:
      None — use stored startDate/endDate (fixed / missing)
      'omit' — do not change pickers
      (start, end) datetimes
    """
    now = now or datetime.now()
    if not isinstance(rule, dict):
        return None
    kind = str(rule.get("kind") or "").strip().lower()
    if kind == "omit":
        return "omit"
    if kind in ("", "fixed"):
        return None
    start = resolveAnchor(rule.get("start") or {"ref": "now"}, now, None)
    end = resolveAnchor(rule.get("end") or {"ref": "now"}, now, start)
    if end < start:
        start, end = end, start
    return (start.replace(second=0, microsecond=0), end.replace(second=0, microsecond=0))
