#!/usr/bin/env python3
"""
Export published Aquarius time-series at a location into Data Dictionary CSV.

Uses Data Doctor Options → Aquarius credentials (keyring) and the same TLS
login as queries. Not USBR/HDB-specific: location identifier (or 32-char
location UniqueId), or ALL, in; published series out.

Dictionary mapping (no stationID column exists — Location Identifier is siteID):
  dataID          = time-series UniqueId
  siteID          = location Identifier
  database        = AQUARIUS
  siteName        = location Name
  commonName      = time-series Label
  datatype        = valuePrecision Identifier only on an exact Parameter match
  valuePrecision  = same Identifier on that match; else blank

Usage (project root, same env / keyring as Data Doctor):
  python scripts/aquariusDictionary.py TFLC
  python scripts/aquariusDictionary.py ALL
  python scripts/aquariusDictionary.py TFLC --out tflc.csv
  python scripts/aquariusDictionary.py ALL --apply
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DICT_COLUMNS = (
    "dataID",
    "siteID",
    "database",
    "siteName",
    "commonName",
    "datatype",
    "valuePrecision",
    "precisionOverride",
    "expectedMin",
    "expectedMax",
    "cuttoffMin",
    "cutoffMax",
    "rateOfChange",
)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def dictionaryRow(series: dict, location: dict) -> dict:
    from core import Aquarius

    locId = Aquarius.locationIdentifierOf(location) or str(
        series.get("LocationIdentifier") or ""
    ).strip()
    locName = Aquarius.locationNameOf(location) or locId
    matched = Aquarius.matchValuePrecision(series.get("Parameter") or "")
    return {
        "dataID": str(series.get("UniqueId") or "").strip(),
        "siteID": locId,
        "database": "AQUARIUS",
        "siteName": locName,
        "commonName": Aquarius.seriesLabelOf(series),
        "datatype": matched,
        "valuePrecision": matched,
        "precisionOverride": "",
        "expectedMin": "",
        "expectedMax": "",
        "cuttoffMin": "",
        "cutoffMax": "",
        "rateOfChange": "",
    }


def rowsForLocation(auth, locationArg: str) -> list[dict]:
    from core import Aquarius

    location = Aquarius.resolveLocation(auth, locationArg)
    if not location:
        die(f"Aquarius location not found: {locationArg}")
    ident = Aquarius.locationIdentifierOf(location)
    name = Aquarius.locationNameOf(location)
    if not ident:
        die(f"Location {locationArg!r} has no Identifier")
    series = Aquarius.publishedSeriesAtLocation(auth, ident)
    rows = []
    skipped = 0
    for item in series:
        row = dictionaryRow(item, location)
        if not row["dataID"]:
            skipped += 1
            continue
        rows.append(row)
    print(
        f"{locationArg}: {ident} ({name}) — {len(rows)} published series"
        + (f", {skipped} without UniqueId" if skipped else "")
    )
    return rows


def rowsForAllLocations(auth) -> list[dict]:
    from core import Aquarius

    print("ALL: listing locations and published series…")
    lookup = Aquarius.locationLookup(auth)
    series = Aquarius.publishedSeriesAll(auth)
    rows = []
    skipped = 0
    for item in series:
        locId = str(item.get("LocationIdentifier") or "").strip()
        location = lookup.get(locId) or {
            "Identifier": locId,
            "LocationName": locId,
        }
        row = dictionaryRow(item, location)
        if not row["dataID"]:
            skipped += 1
            continue
        rows.append(row)
    print(
        f"ALL: {len(lookup)} location(s), {len(rows)} published series"
        + (f", {skipped} without UniqueId" if skipped else "")
    )
    return rows


def writeCsv(path: Path | None, rows: list[dict]) -> None:
    out = sys.stdout if path is None else path.open("w", encoding="utf-8", newline="")
    close = path is not None
    try:
        writer = csv.DictWriter(out, fieldnames=list(DICT_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in DICT_COLUMNS})
    finally:
        if close:
            out.close()
    if path is not None:
        print(f"Wrote {len(rows)} row(s) to {path}")


def applyToBunker(dbPath: Path, rows: list[dict], dryRun: bool) -> None:
    from core import Logic

    if not dbPath.is_file():
        die(f"bunker.db not found: {dbPath}")
    Logic.ensureDataDictionarySchema()
    conn = sqlite3.connect(str(dbPath))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("PRAGMA table_info(dataDictionary)")
        cols = [row[1] for row in cur.fetchall()]
        lower = {c.lower(): c for c in cols}
        needed = ("dataid", "siteid", "database", "sitename", "commonname", "datatype")
        missing = [n for n in needed if n not in lower]
        if missing:
            die(f"dataDictionary missing columns: {missing}")
        cDataId = lower["dataid"]
        cDb = lower["database"]
        insertCols = [lower[k.lower()] for k in DICT_COLUMNS if k.lower() in lower]
        inserted = 0
        skipped = 0
        for row in rows:
            existing = conn.execute(
                f"SELECT rowid FROM dataDictionary WHERE {cDataId} = ? AND {cDb} = ?",
                (row["dataID"], row["database"]),
            ).fetchone()
            if existing is not None:
                skipped += 1
                continue
            if not dryRun:
                placeholders = ", ".join("?" for _ in insertCols)
                colSql = ", ".join(f'"{c}"' for c in insertCols)
                values = []
                byLower = {k.lower(): v for k, v in row.items()}
                for col in insertCols:
                    values.append(byLower.get(col.lower(), "") or None)
                conn.execute(
                    f"INSERT INTO dataDictionary ({colSql}) VALUES ({placeholders})",
                    values,
                )
            inserted += 1
        if not dryRun:
            conn.commit()
        print(
            f"{'DRY-RUN ' if dryRun else ''}bunker.db: "
            f"{inserted} inserted, {skipped} already present"
        )
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export published Aquarius series at a location to Data Dictionary CSV"
    )
    parser.add_argument(
        "location",
        nargs="*",
        help="Aquarius location Identifier (e.g. TFLC), 32-char location UniqueId, or ALL",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="every location (same as passing ALL)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="CSV path (default: stdout). Dictionary column headers.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="insert new rows into bunker.db (skip existing dataID + AQUARIUS)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "core" / "bunker.db",
        help="bunker.db path (default: core/bunker.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --apply, count inserts without writing",
    )
    parser.add_argument("--debug", action="store_true", help="DEBUG log lines")
    args = parser.parse_args()

    try:
        osChdir()
        from core import Aquarius, Config

        if args.debug:
            Config.debug = True
        auth = Aquarius.authenticate()
        if not auth:
            die("Aquarius login failed (Options → Aquarius server / user / password)")
        wantAll = args.all or any(str(loc).strip().upper() == "ALL" for loc in args.location)
        if not wantAll and not args.location:
            die("pass a location Identifier or ALL")
        rows = []
        seen = set()
        if wantAll:
            chunk = rowsForAllLocations(auth)
        else:
            chunk = []
            for loc in args.location:
                chunk.extend(rowsForLocation(auth, loc))
        for row in chunk:
            key = (row["dataID"], row["database"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        if not rows:
            print("No published series")
        if args.out is not None or not args.apply:
            writeCsv(args.out, rows)
        if args.apply:
            applyToBunker(args.db, rows, dryRun=args.dry_run)
        return 0
    except SystemExit:
        raise
    except Exception as e:
        die(str(e))
        return 1


def osChdir() -> None:
    import os
    os.chdir(ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
