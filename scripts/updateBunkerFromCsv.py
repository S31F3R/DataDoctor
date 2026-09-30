#!/usr/bin/env python3
"""
Update core/bunker.db from USBR CSV export(s).

USBR-only. Does not touch USGS/Aquarius rows.

Column map (CSV → dataDictionary):
  SITE_DATATYPE_ID = dataID        (match key; insert only, never rewrite)
  SITE_ID          = siteID        (match key; insert only, never rewrite)
  SITE_NAME        = siteName      (update from CSV)
  SITE_COMMON_NAME = commonName    (insert always; update existing only if you answer y)
  DATATYPE_NAME    = datatype      (insert always; update existing only if you answer y)
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
  python scripts/updateBunkerFromCsv.py "C:\\Temp\\Exports"
  python scripts/updateBunkerFromCsv.py "C:\\Temp\\Exports\\*.csv" --db "core/bunker.db" --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CSV_THREADS = 6

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


def askYesNo(prompt: str, default: bool = False) -> bool:
    """Terminal y/n. Empty uses default (n unless default True)."""
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        raw = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    if not raw:
        return default
    if raw in ("y", "yes"):
        return True
    if raw in ("n", "no"):
        return False
    print("Please answer y or n.")
    return askYesNo(prompt, default)


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


def expandCsvPaths(items) -> list[Path]:
    """
    Accept a csv file, a folder of csv files, or a *.csv pattern.

    The shell does not expand a quoted glob, so "*.csv" arrives here as text.
    """
    found = []
    seen = set()

    def add(path: Path) -> None:
        try:
            key = os.path.normcase(str(path.resolve()))
        except OSError:
            key = os.path.normcase(str(path))
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    for raw in items:
        text = str(raw)
        path = Path(text)
        if any(ch in text for ch in "*?["):
            parent = path.parent
            name = path.name
            if str(parent) in ("", "."):
                parent = Path(".")
            matches = sorted(
                p for p in parent.glob(name)
                if p.is_file() and p.suffix.lower() == ".csv"
            )
            if not matches:
                die(f"CSV not found: {text}")
            for match in matches:
                add(match)
            continue
        if path.is_dir():
            matches = sorted(p for p in path.glob("*.csv") if p.is_file())
            if not matches:
                die(f"No CSV files in {path}")
            for match in matches:
                add(match)
            continue
        if not path.is_file():
            die(f"CSV not found: {path}")
        add(path)
    return found


def loadCsvRows(csvPaths: list[Path]) -> list[tuple[Path, list]]:
    """Read CSV files on several threads. sqlite writes stay on one connection."""
    if len(csvPaths) <= 1:
        return [(csvPaths[0], readCsvRows(csvPaths[0]))] if csvPaths else []
    workers = min(CSV_THREADS, len(csvPaths))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        loaded = list(pool.map(readCsvRows, csvPaths))
    return list(zip(csvPaths, loaded))


def rowKey(dataId, siteId):
    def norm(val):
        if val is None:
            return None
        text = str(val).strip()
        return text or None
    return (norm(dataId), norm(siteId))


def loadDictionary(conn, dataIdCol, siteIdCol) -> dict:
    """One read of dataDictionary. Later rows match in memory, not one query each."""
    found = {}
    for row in conn.execute("SELECT * FROM dataDictionary"):
        item = dict(row)
        found[rowKey(item.get(dataIdCol), item.get(siteIdCol))] = item
    return found


def mergeCsv(
    dbPath: Path,
    csvPaths: list[Path],
    dryRun: bool,
    updateCommonNames: bool = False,
    updateDatatypes: bool = False,
) -> int:
    if not dbPath.is_file():
        die(f"bunker.db not found: {dbPath}")
    csvPaths = expandCsvPaths(csvPaths)
    allRows = []
    for p, chunk in loadCsvRows(csvPaths):
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
        byKey = loadDictionary(conn, cDataId, cSiteId)

        updated = 0
        inserted = 0
        skipped = 0
        insertSql = (
            f"INSERT INTO dataDictionary "
            f"({cDataId}, {cSiteId}, {cDb}, {cSiteName}, {cCommon}, {cType}) "
            f"VALUES (?, ?, ?, ?, ?, ?)"
        )
        inserts = []
        updates = []

        for row in allRows:
            key = rowKey(row["dataID"], row["siteID"])
            existing = byKey.get(key)
            if existing is None:
                inserted += 1
                fresh = {
                    cDataId: row["dataID"],
                    cSiteId: row["siteID"],
                    cDb: row["database"] or None,
                    cSiteName: row["siteName"] or None,
                    cCommon: row["commonName"] or None,
                    cType: row["datatype"] or None,
                }
                byKey[key] = fresh
                if not dryRun:
                    inserts.append((
                        row["dataID"],
                        row["siteID"],
                        row["database"] or None,
                        row["siteName"] or None,
                        row["commonName"] or None,
                        row["datatype"] or None,
                    ))
                continue

            sets = []
            params = []
            changed = {}
            if row["siteName"] and str(existing.get(cSiteName) or "") != row["siteName"]:
                sets.append(f"{cSiteName} = ?")
                params.append(row["siteName"])
                changed[cSiteName] = row["siteName"]
            if (
                updateDatatypes
                and row["datatype"]
                and str(existing.get(cType) or "") != row["datatype"]
            ):
                sets.append(f"{cType} = ?")
                params.append(row["datatype"])
                changed[cType] = row["datatype"]
            if row["database"] and str(existing.get(cDb) or "") != row["database"]:
                sets.append(f"{cDb} = ?")
                params.append(row["database"])
                changed[cDb] = row["database"]
            if row["commonName"]:
                if empty(existing.get(cCommon)) or (
                    updateCommonNames
                    and str(existing.get(cCommon) or "") != row["commonName"]
                ):
                    sets.append(f"{cCommon} = ?")
                    params.append(row["commonName"])
                    changed[cCommon] = row["commonName"]

            if not sets:
                skipped += 1
                continue
            updated += 1
            existing.update(changed)
            if not dryRun:
                params.extend([row["dataID"], row["siteID"]])
                sql = (
                    f"UPDATE dataDictionary SET {', '.join(sets)} "
                    f"WHERE {cDataId} = ? AND {cSiteId} = ?"
                )
                updates.append((sql, params))

        if not dryRun:
            if inserts:
                conn.executemany(insertSql, inserts)
            grouped = {}
            for sql, params in updates:
                grouped.setdefault(sql, []).append(params)
            for sql, batch in grouped.items():
                conn.executemany(sql, batch)
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
    parser.add_argument(
        "csv",
        nargs="+",
        help="CSV file, folder, or a *.csv pattern (quote the pattern)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "core" / "bunker.db",
        help="bunker.db path (default: core/bunker.db)",
    )
    parser.add_argument("--dry-run", dest="dryRun", action="store_true")
    args = parser.parse_args()
    print(f"Database: {args.db}")
    updateCommon = askYesNo("Update Data Dictionary Common Names?")
    updateTypes = askYesNo("Update Data Dictionary Data Types?")
    return mergeCsv(
        args.db,
        args.csv,
        dryRun=args.dryRun,
        updateCommonNames=updateCommon,
        updateDatatypes=updateTypes,
    )


if __name__ == "__main__":
    raise SystemExit(main())
