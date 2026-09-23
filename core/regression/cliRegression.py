# cliRegression.py
# CSV in, equation and stats out. No Qt.
#
#   python -m core.regression.cliRegression series.csv --target Y
#
# First column is the timestamp. Remaining columns are numeric.
# --target names a header; omitted, the last column is predicted.

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

from core.regression.fitRegression import SeriesColumn, fitColumns


def _parseTime(text: str):
    s = (text or "").strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("Z", "")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%y %H:%M",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def loadCsv(path: str):
    """(list[SeriesColumn], headers) from a timestamp + numeric CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        raise SystemExit(f"Not enough rows in {path}")
    headers = [h.strip() for h in rows[0]]
    if len(headers) < 3:
        raise SystemExit("CSV needs a timestamp column and at least two series.")
    times = []
    columns = [[] for _ in headers[1:]]
    for row in rows[1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        t = _parseTime(row[0] if row else "")
        times.append(t)
        for i in range(len(columns)):
            cell = row[i + 1].strip() if i + 1 < len(row) else ""
            try:
                columns[i].append(float(cell) if cell else float("nan"))
            except ValueError:
                columns[i].append(float("nan"))
    series = []
    for i, name in enumerate(headers[1:]):
        key = name or chr(ord("A") + i)
        series.append(SeriesColumn(key, name or key, i, times, columns[i]))
    return series


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    targetName = None
    path = None
    i = 0
    while i < len(args):
        if args[i] == "--target" and i + 1 < len(args):
            targetName = args[i + 1]
            i += 2
            continue
        if args[i].startswith("-"):
            print(f"Unknown option {args[i]}", file=sys.stderr)
            return 2
        path = args[i]
        i += 1
    if not path:
        print(
            "Usage: python -m core.regression.cliRegression series.csv [--target NAME]",
            file=sys.stderr,
        )
        return 2
    if not Path(path).is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2
    series = loadCsv(path)
    if targetName:
        idx = next((i for i, s in enumerate(series) if s.key == targetName or s.label == targetName), None)
        if idx is None:
            print(f"No column named {targetName}", file=sys.stderr)
            return 2
    else:
        idx = len(series) - 1
    result, err = fitColumns(series, idx)
    if err:
        print("REFUSED")
        print(err)
        return 1
    print(result.labelText)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
