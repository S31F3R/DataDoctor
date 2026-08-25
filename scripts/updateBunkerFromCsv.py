#!/usr/bin/env python3
"""
Update core/bunker.db from USBR CSV export(s).

USBR-only. Does not touch USGS/Aquarius rows.

Column map (CSV → dataDictionary):
  SITE_DATATYPE_ID = dataID        (match key; insert only, never rewrite)
  SITE_ID          = siteID        (match key; insert only, never rewrite)
  SITE_NAME        = siteName      (update from CSV)
  SITE_COMMON_NAME = commonName    (insert only; keep user edits)
  DATATYPE_NAME    = datatype      (update from CSV)
  USGS_ID          = ignored
  DB_SITE_CODE     = database      (update from CSV, mapped to USBR-* labels)

Never written: valuePrecision, precisionOverride, expectedMin, expectedMax,
cuttoffMin, cutoffMax, rateOfChange.

DB_SITE_CODE map:
  YAO → USBR-YAOHDB
  UC  → USBR-UCHDB2
  LC  → USBR-LCHDB
  CU  → USBR-CUHDB
  KBO → USBR-KBOHDB
  LBO → USBR-LBOHDB
  ECO → USBR-ECOHDB

Usage (from project root):
  python scripts/updateBunkerFromCsv.py "path/to/export.csv"
  python scripts/updateBunkerFromCsv.py "*.csv" --db "core/bunker.db" --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DB_SITE_CODE_MAP = {
    "YAO": "USBR-YAOHDB",
    "UC": "USBR-UCHDB2",
    "LC": "USBR-LCHDB",
    "CU": "USBR-CUHDB",
    "KBO": "USBR-KBOHDB",
    "LBO": "USBR-LBOHDB",
    "ECO": "USBR-ECOHDB",
}

CSV_ALIASES = {
    "dataid": ("SITE_DATATYPE_ID", "DATAID", "DATA_ID", "SDID"),
    "siteid": ("SITE_ID", "SITEID"),
    "sitename": ("SITE_NAME", "SITENAME"),
    "commonname": ("SITE_COMMON_NAME", "COMMON_NAME", "COMMONNAME"),
    "datatype": ("DATATYPE_NAME", "DATATYPE", "DATA_TYPE"),
    "database": ("DB_SITE_CODE", "DATABASE", "DB_CODE"),
}


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def normalizeHeader(name: str) -> str:
    return "".join(ch for ch in (name or "").strip().upper() if ch.isalnum() or ch == "_")


def mapDatabase(code: str) -> str:
    raw = (code or "").strip()
    if not raw:
        return ""
    if raw.upper().startswith("USBR-"):
        rest = raw.split("-", 1)[1] if "-" in raw else raw
        return f"USBR-{rest.upper()}"
    key = raw.upper()
    if key in DB_SITE_CODE_MAP:
        return DB_SITE_CODE_MAP[key]
    # HDB-style already (LCHDB, UCHDB2, …)
    if key.endswith("HDB") or key.endswith("HDB2"):
        return f"USBR-{key}"
    print(f"WARN: unknown DB_SITE_CODE {raw!r}; storing as USBR-{key}", file=sys.stderr)
    return f"USBR-{key}"


def columnMap(headers: list[str]) -> dict[str, str]:
    """fieldKey → actual CSV header."""
    byNorm = {normalizeHeader(h): h for h in headers}
    out = {}
    for key, aliases in CSV_ALIASES.items():
        for alias in aliases:
            hit = byNorm.get(normalizeHeader(alias))
            if hit:
                out[key] = hit
                break
    return out


def cell(row: dict, header: str | None) -> str:
    if not header:
        return ""
    val = row.get(header)
    if val is None:
        return ""
    return str(val).strip()


def empty(val) -> bool:
    return val is None or str(val).strip() == ""


def openDb(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def resolveCols(conn: sqlite3.Connection):
    cur = conn.execute("PRAGMA table_info(dataDictionary)")
    cols = [row[1] for row in cur.fetchall()]
    lower = {c.lower(): c for c in cols}
    needed = ("dataid", "siteid", "database", "sitename", "commonname", "datatype")
    missing = [n for n in needed if n not in lower]
    if missing:
        die(f"dataDictionary missing columns: {missing}")
    return lower


def readCsvRows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            die(f"no header row in {path}")
        cmap = columnMap(list(reader.fieldnames))
        if "dataid" not in cmap or "siteid" not in cmap:
            die(
                f"{path.name}: need SITE_DATATYPE_ID and SITE_ID columns "
                f"(got {reader.fieldnames})"
            )
        rows = []
        for raw in reader:
            dataId = cell(raw, cmap.get("dataid"))
            siteId = cell(raw, cmap.get("siteid"))
            if not dataId and not siteId:
                continue
            rows.append(
                {
                    "dataID": dataId,
                    "siteID": siteId,
                    "siteName": cell(raw, cmap.get("sitename")),
                    "commonName": cell(raw, cmap.get("commonname")),
                    "datatype": cell(raw, cmap.get("datatype")),
                    "database": mapDatabase(cell(raw, cmap.get("database"))),
                }
            )
        return rows


def mergeCsv(dbPath: Path, csvPaths: list[Path], dryRun: bool) -> int:
    if not dbPath.is_file():
        die(f"bunker.db not found: {dbPath}")
    allRows = []
    for p in csvPaths:
        if not p.is_file():
            die(f"CSV not found: {p}")
        chunk = readCsvRows(p)
        print(f"{p.name}: {len(chunk)} USBR row(s)")
        allRows.extend(chunk)
    if not allRows:
        print("No rows to merge")
        return 0

    conn = openDb(dbPath)
    try:
        cols = resolveCols(conn)
        cDataId = cols["dataid"]
        cSiteId = cols["siteid"]
        cDb = cols["database"]
        cSiteName = cols["sitename"]
        cCommon = cols["commonname"]
        cType = cols["datatype"]

        updated = 0
        inserted = 0
        skipped = 0

        for row in allRows:
            existing = conn.execute(
                f"SELECT * FROM dataDictionary WHERE {cDataId} = ? AND {cSiteId} = ?",
                (row["dataID"], row["siteID"]),
            ).fetchone()
            if existing is None:
                if dryRun:
                    inserted += 1
                    continue
                conn.execute(
                    f"INSERT INTO dataDictionary "
                    f"({cDataId}, {cSiteId}, {cDb}, {cSiteName}, {cCommon}, {cType}) "
                    f"VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        row["dataID"],
                        row["siteID"],
                        row["database"] or None,
                        row["siteName"] or None,
                        row["commonName"] or None,
                        row["datatype"] or None,
                    ),
                )
                inserted += 1
                continue

            sets = []
            params = []
            if row["siteName"] and str(existing[cSiteName] or "") != row["siteName"]:
                sets.append(f"{cSiteName} = ?")
                params.append(row["siteName"])
            if row["datatype"] and str(existing[cType] or "") != row["datatype"]:
                sets.append(f"{cType} = ?")
                params.append(row["datatype"])
            if row["database"] and str(existing[cDb] or "") != row["database"]:
                sets.append(f"{cDb} = ?")
                params.append(row["database"])
            # commonName: only fill when the user/row has none
            if row["commonName"] and empty(existing[cCommon]):
                sets.append(f"{cCommon} = ?")
                params.append(row["commonName"])

            if not sets:
                skipped += 1
                continue
            if not dryRun:
                params.extend([row["dataID"], row["siteID"]])
                conn.execute(
                    f"UPDATE dataDictionary SET {', '.join(sets)} "
                    f"WHERE {cDataId} = ? AND {cSiteId} = ?",
                    params,
                )
            updated += 1

        if not dryRun:
            conn.commit()
        print(
            f"{'DRY-RUN ' if dryRun else ''}CSV merge: "
            f"{updated} updated, {inserted} inserted, {skipped} unchanged"
        )
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Update bunker.db from USBR CSV exports")
    parser.add_argument("csv", nargs="+", type=Path, help="CSV file(s)")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "core" / "bunker.db",
        help="bunker.db path (default: core/bunker.db)",
    )
    parser.add_argument("--dry-run", dest="dryRun", action="store_true")
    args = parser.parse_args()
    print(f"Database: {args.db}")
    return mergeCsv(args.db, args.csv, dryRun=args.dryRun)


if __name__ == "__main__":
    raise SystemExit(main())
