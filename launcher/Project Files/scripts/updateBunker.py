#!/usr/bin/env python3
"""
Merge a packaged bunker.db into the user's bunker.db without wiping user edits.

Rules (per To Do List):
  - Match rows on dataID + siteID
  - Always update from packaged: siteName, database (when packaged differs)
  - Prompt y/n (console): commonName, datatype  (existing rows only; new
    rows always take the packaged values)
  - Fill blanks only (never override user values): valuePrecision,
    precisionOverride, expectedMin, expectedMax, cuttoffMin, cutoffMax,
    rateOfChange
  - Insert rows that exist only in the packaged DB
  - Never delete user-only rows
  - No TTY / EOF → leave commonName and datatype on existing rows alone

Typical Windows layout after packageWindows.py:
  <install>/Project Files/temp/bunker.db   ← packaged merge source
  <install>/Project Files/core/bunker.db   ← live user dictionary (destination)
  <install>/Project Files/scripts/updateBunker.py
  <install>/applyUpdate.cmd                ← full update (calls this for bunker merge)

Full app updates run this automatically via applyUpdate.cmd / applyUpdate.py.
Dictionary-only merges can invoke this script directly.

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

from pathlib import Path


# Always update these from packaged when packaged has a non-empty different value
ALWAYS_UPDATE_FIELDS = ("siteName", "database")
# Existing rows: only if the user answers y (or --update-common-names / --update-datatypes)
OPTIONAL_UPDATE_FIELDS = ("commonName", "datatype", "dataType")
# Back-compat alias for callers/docs that still mention UPDATE_FIELDS
UPDATE_FIELDS = ALWAYS_UPDATE_FIELDS + OPTIONAL_UPDATE_FIELDS
# Fill user blanks only — never replace a value the user already set
FILL_BLANK_FIELDS = (
    "valuePrecision",
    "precisionOverride",
    "expectedMin",
    "expectedMax",
    "cuttoffMin",
    "cutoffMax",
    "rateOfChange",
)
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


def askYesNo(prompt: str, default: bool = False) -> bool:
    """Terminal y/n. Empty / EOF / no TTY uses default (n unless default True)."""
    suffix = " [Y/n] " if default else " [y/N] "
    if not sys.stdin.isatty():
        print(f"{prompt} (no console — default {'Y' if default else 'N'})")
        return default
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
        installRoot / "pythonFiles" / "temp" / "bunker.db",
        installRoot / "Project Files" / "temp" / "bunker.db",
        # Legacy fallbacks if someone still drops packaged DB in core/
        projectFiles / "core" / "bunker.db.packaged",
        here / "bunker.db",
    ]
    candidatesUser = [
        projectFiles / "core" / "bunker.db",
        installRoot / "pythonFiles" / "core" / "bunker.db",
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
        parentName = tempDir.parent.name.lower()
        if parentName not in ("pythonfiles", "project files", "projectfiles"):
            if "project" not in parentName and "python" not in parentName:
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


def merge(
    packagedPath: Path,
    userPath: Path,
    dryRun: bool = False,
    updateCommonNames: bool = False,
    updateDatatypes: bool = False,
) -> int:
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

    # One backup only — drop prior bunker.db.bak* then write bunker.db.bak
    if not dryRun:
        for old in userPath.parent.glob(userPath.name + ".bak*"):
            try:
                old.unlink()
                print(f"Removed old backup: {old}")
            except OSError as e:
                print(f"WARN: could not remove {old}: {e}", file=sys.stderr)
        backup = userPath.with_suffix(userPath.suffix + ".bak")
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

        mergeFieldNames = []
        seenLower = set()
        for f in list(ALWAYS_UPDATE_FIELDS) + list(OPTIONAL_UPDATE_FIELDS) + list(FILL_BLANK_FIELDS):
            if f.lower() in seenLower:
                continue
            seenLower.add(f.lower())
            mergeFieldNames.append(f)
        pkgFields = {f: col(pkgMap, f) for f in mergeFieldNames}
        usrFields = {f: col(usrMap, f) for f in mergeFieldNames}
        fillBlankLower = {f.lower() for f in FILL_BLANK_FIELDS}
        optionalAllowed = set()
        if updateCommonNames:
            optionalAllowed.add("commonname")
        if updateDatatypes:
            optionalAllowed.add("datatype")
        optionalFieldLower = {f.lower() for f in OPTIONAL_UPDATE_FIELDS}

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
                # Update labels from packaged; QAQC/precision fields fill blanks only
                sets = []
                params = []
                for field in mergeFieldNames:
                    pCol = pkgFields.get(field)
                    uCol = usrFields.get(field)
                    if not pCol or not uCol:
                        continue
                    newVal = row[pCol]
                    oldVal = existing[uCol]
                    if newVal is None or str(newVal).strip() == "":
                        continue
                    if oldVal is not None and str(oldVal) == str(newVal):
                        continue
                    fillBlank = field.lower() in fillBlankLower
                    if fillBlank:
                        if oldVal is not None and str(oldVal).strip() != "":
                            continue
                    if field.lower() in optionalFieldLower and field.lower() not in optionalAllowed:
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
    parser.add_argument(
        "--update-common-names",
        dest="updateCommonNames",
        action="store_true",
        help="Overwrite existing commonName from packaged (skip prompt)",
    )
    parser.add_argument(
        "--no-update-common-names",
        dest="updateCommonNames",
        action="store_false",
        help="Leave existing commonName alone (skip prompt)",
    )
    parser.add_argument(
        "--update-datatypes",
        dest="updateDatatypes",
        action="store_true",
        help="Overwrite existing datatype from packaged (skip prompt)",
    )
    parser.add_argument(
        "--no-update-datatypes",
        dest="updateDatatypes",
        action="store_false",
        help="Leave existing datatype alone (skip prompt)",
    )
    parser.set_defaults(updateCommonNames=None, updateDatatypes=None)
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
    updateCommon = args.updateCommonNames
    updateTypes = args.updateDatatypes
    if updateCommon is None:
        updateCommon = askYesNo("Update Data Dictionary Common Names?")
    if updateTypes is None:
        updateTypes = askYesNo("Update Data Dictionary Data Types?")
    print(
        f"commonName updates: {'yes' if updateCommon else 'no'}; "
        f"datatype updates: {'yes' if updateTypes else 'no'}"
    )
    code = merge(
        packaged,
        user,
        dryRun=args.dryRun,
        updateCommonNames=updateCommon,
        updateDatatypes=updateTypes,
    )
    if code == 0 and not args.dryRun:
        cleanupTempFolder(Path(packaged))
    return code


if __name__ == "__main__":
    sys.exit(main())
