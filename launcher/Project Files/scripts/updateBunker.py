#!/usr/bin/env python3
"""
Merge a packaged bunker.db into the user's bunker.db without wiping user edits.

Rules (per To Do List):
  - Match rows on dataID + siteID
  - Only update fields: dataType, siteName, valuePrecision, database
    (and only when those differ — never replace other user columns)
  - Insert rows that exist only in the packaged DB
  - Never delete user-only rows

Typical Windows layout after packageWindows.py:
  <install>/Project Files/temp/bunker.db   ← packaged merge source
  <install>/Project Files/core/bunker.db   ← live user dictionary (destination)
  <install>/updateBunker.cmd               ← runs this script
  <install>/Project Files/scripts/updateBunker.py

After a successful merge (not dry-run), Project Files/temp/ is removed.

Usage:
  python updateBunker.py
  python updateBunker.py --packaged path/to/packaged/bunker.db --user path/to/user/bunker.db
  python updateBunker.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


# Only these columns are written from packaged → user on match
MERGE_FIELDS = ("dataType", "siteName", "valuePrecision", "database")
# Match keys (case-insensitive column resolve)
MATCH_KEYS = ("dataID", "siteID")


def resolveColumns(conn: sqlite3.Connection, table: str = "dataDictionary"):
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    lowerMap = {c.lower(): c for c in cols}
    return cols, lowerMap


def col(lowerMap, *candidates):
    for name in candidates:
        if name.lower() in lowerMap:
            return lowerMap[name.lower()]
    return None


def openDb(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def findDefaultPaths():
    """
    Heuristic paths relative to this script.

    Script location (packaged): <install>/Project Files/scripts/updateBunker.py
      packaged → ../temp/bunker.db
      user     → ../core/bunker.db
    """
    here = Path(__file__).resolve().parent  # .../Project Files/scripts
    projectFiles = here.parent              # .../Project Files
    installRoot = projectFiles.parent       # zip / install root

    candidatesPackaged = [
        projectFiles / "temp" / "bunker.db",
        installRoot / "Project Files" / "temp" / "bunker.db",
        # Legacy fallbacks if someone still drops packaged DB in core/
        projectFiles / "core" / "bunker.db.packaged",
        here / "bunker.db",
    ]
    candidatesUser = [
        projectFiles / "core" / "bunker.db",
        installRoot / "Project Files" / "core" / "bunker.db",
        Path(os.environ.get("APPDATA", "")) / "Data Doctor" / "bunker.db",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Data Doctor" / "bunker.db",
    ]
    packaged = next((p for p in candidatesPackaged if p.is_file()), None)
    user = next((p for p in candidatesUser if p.is_file()), None)
    return packaged, user


def cleanupTempFolder(packagedPath: Path):
    """
    After a successful merge, remove Project Files/temp/ when the packaged
    bunker lived there (so users are not left with a stale merge source).
    """
    try:
        if packagedPath is None or not packagedPath.name.lower().startswith("bunker"):
            return
        tempDir = packagedPath.parent
        if tempDir.name.lower() != "temp":
            return
        # Only remove temp if it sits under Project Files
        if tempDir.parent.name.lower() not in ("project files", "projectfiles"):
            # Still allow plain "temp" under Project Files even if name casing differs
            if "project" not in tempDir.parent.name.lower():
                return
        if packagedPath.is_file():
            packagedPath.unlink()
            print(f"Removed packaged file: {packagedPath}")
        # Remove empty temp dir (and any leftover files we created)
        if tempDir.is_dir():
            for child in tempDir.iterdir():
                try:
                    if child.is_file():
                        child.unlink()
                except Exception:
                    pass
            try:
                tempDir.rmdir()
                print(f"Removed temp folder: {tempDir}")
            except OSError:
                # Non-empty or busy — leave it
                print(f"Note: could not remove temp folder (not empty?): {tempDir}")
    except Exception as e:
        print(f"WARN: temp cleanup failed: {e}", file=sys.stderr)


def merge(packagedPath: Path, userPath: Path, dryRun: bool = False) -> int:
    if not packagedPath.is_file():
        print(f"ERROR: packaged bunker not found: {packagedPath}", file=sys.stderr)
        return 1
    if not userPath.is_file():
        print(f"ERROR: user bunker not found: {userPath}", file=sys.stderr)
        return 1
    if packagedPath.resolve() == userPath.resolve():
        print(
            "ERROR: packaged and user paths are the same file. "
            "Pass a separate --packaged (from the update) and --user (live) path.",
            file=sys.stderr,
        )
        return 1

    # Backup user DB
    if not dryRun:
        backup = userPath.with_suffix(
            userPath.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        shutil.copy2(userPath, backup)
        print(f"Backup: {backup}")

    pkg = openDb(packagedPath)
    usr = openDb(userPath)
    try:
        pkgCols, pkgMap = resolveColumns(pkg)
        usrCols, usrMap = resolveColumns(usr)

        pkgDataId = col(pkgMap, "dataID", "dataId", "dataid")
        pkgSiteId = col(pkgMap, "siteID", "siteId", "siteid")
        usrDataId = col(usrMap, "dataID", "dataId", "dataid")
        usrSiteId = col(usrMap, "siteID", "siteId", "siteid")
        if not all([pkgDataId, pkgSiteId, usrDataId, usrSiteId]):
            print("ERROR: dataID/siteID columns missing in one of the databases", file=sys.stderr)
            return 1

        # Map merge field names in each DB
        pkgFields = {f: col(pkgMap, f) for f in MERGE_FIELDS}
        usrFields = {f: col(usrMap, f) for f in MERGE_FIELDS}

        pkgRows = pkg.execute("SELECT * FROM dataDictionary").fetchall()
        updated = 0
        inserted = 0
        skipped = 0

        for row in pkgRows:
            dataId = row[pkgDataId]
            siteId = row[pkgSiteId]
            if dataId is None and siteId is None:
                skipped += 1
                continue

            existing = usr.execute(
                f"SELECT * FROM dataDictionary WHERE {usrDataId} = ? AND {usrSiteId} = ?",
                (dataId, siteId),
            ).fetchone()

            if existing is not None:
                # Update only allowed fields when packaged has a non-empty value
                sets = []
                params = []
                for field in MERGE_FIELDS:
                    pCol = pkgFields.get(field)
                    uCol = usrFields.get(field)
                    if not pCol or not uCol:
                        continue
                    newVal = row[pCol]
                    oldVal = existing[uCol]
                    # Only push packaged value when it is non-empty and different
                    if newVal is None or str(newVal).strip() == "":
                        continue
                    if oldVal is not None and str(oldVal) == str(newVal):
                        continue
                    sets.append(f"{uCol} = ?")
                    params.append(newVal)
                if sets:
                    params.extend([dataId, siteId])
                    sql = (
                        f"UPDATE dataDictionary SET {', '.join(sets)} "
                        f"WHERE {usrDataId} = ? AND {usrSiteId} = ?"
                    )
                    if not dryRun:
                        usr.execute(sql, params)
                    updated += 1
                else:
                    skipped += 1
            else:
                # Insert full packaged row into columns that exist on user side
                insertCols = []
                insertVals = []
                for c in pkgCols:
                    if c.lower() in usrMap:
                        insertCols.append(usrMap[c.lower()])
                        insertVals.append(row[c])
                if not insertCols:
                    skipped += 1
                    continue
                placeholders = ", ".join("?" * len(insertCols))
                colList = ", ".join(insertCols)
                sql = f"INSERT INTO dataDictionary ({colList}) VALUES ({placeholders})"
                if not dryRun:
                    usr.execute(sql, insertVals)
                inserted += 1

        if not dryRun:
            usr.commit()

        print(
            f"{'DRY-RUN ' if dryRun else ''}Merge complete: "
            f"{updated} updated, {inserted} inserted, {skipped} unchanged/skipped"
        )
        return 0
    finally:
        pkg.close()
        usr.close()


def main():
    parser = argparse.ArgumentParser(description="Merge packaged bunker.db into user bunker.db")
    parser.add_argument("--packaged", type=Path, help="Packaged (new) bunker.db path")
    parser.add_argument("--user", type=Path, help="User (live) bunker.db path")
    parser.add_argument(
        "--dry-run",
        dest="dryRun",
        action="store_true",
        help="Report only; no writes",
    )
    args = parser.parse_args()

    packaged, user = findDefaultPaths()
    if args.packaged:
        packaged = args.packaged
    if args.user:
        user = args.user

    if not packaged or not user:
        print(
            "Could not auto-detect paths. Pass --packaged and --user explicitly.\n"
            f"  packaged={packaged}\n  user={user}",
            file=sys.stderr,
        )
        return 1

    print(f"Packaged: {packaged}")
    print(f"User:     {user}")
    code = merge(packaged, user, dryRun=args.dryRun)
    if code == 0 and not args.dryRun:
        cleanupTempFolder(Path(packaged))
    return code


if __name__ == "__main__":
    sys.exit(main())
