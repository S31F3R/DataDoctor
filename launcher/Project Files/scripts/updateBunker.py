#!/usr/bin/env python3
"""
Merge a packaged bunker.db into the user's bunker.db without wiping user edits.

CLI wrapper around core.BunkerMerge. Rules:
  - Match rows on dataID + siteID
  - Always update from packaged: siteName, database (when packaged differs)
  - Prompt y/n (console): commonName, datatype  (existing rows only; new
    rows always take the packaged values — answering N does not skip inserts)
  - Fill blanks only: valuePrecision, precisionOverride, expectedMin,
    expectedMax, cuttoffMin, cutoffMax, rateOfChange
  - Insert rows that exist only in the packaged DB
  - Never delete user-only rows
  - No TTY / EOF → leave commonName and datatype on existing rows alone
  - Identical live vs packaged files → skip merge (no prompts)

Usage:
  python updateBunker.py
  python updateBunker.py --packaged path/to/packaged/bunker.db --user path/to/user/bunker.db
  python updateBunker.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _loadMerge():
    try:
        from core.BunkerMerge import askYesNo, filesIdentical, merge
        return askYesNo, filesIdentical, merge
    except ImportError:
        pass
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "core" / "BunkerMerge.py").is_file():
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
            from core.BunkerMerge import askYesNo, filesIdentical, merge
            return askYesNo, filesIdentical, merge
    raise ImportError("core.BunkerMerge not found (looked next to this script)")


askYesNo, filesIdentical, merge = _loadMerge()


def findDefaultPaths():
    """
    Heuristic paths relative to this script.

    Script location (packaged): <install>/pythonFiles/scripts/updateBunker.py
      packaged → ../temp/bunker.db
      user     → ../core/bunker.db
    """
    here = Path(__file__).resolve().parent
    projectFiles = here.parent
    installRoot = projectFiles.parent

    candidatesPackaged = [
        projectFiles / "temp" / "bunker.db",
        installRoot / "pythonFiles" / "temp" / "bunker.db",
        installRoot / "Project Files" / "temp" / "bunker.db",
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
    """After a successful merge, remove pythonFiles/temp/ when the packaged bunker lived there."""
    try:
        if packagedPath is None or not packagedPath.name.lower().startswith("bunker"):
            return
        tempDir = packagedPath.parent
        if tempDir.name.lower() != "temp":
            return
        parentName = tempDir.parent.name.lower()
        if parentName not in ("pythonfiles", "project files", "projectfiles"):
            if "project" not in parentName and "python" not in parentName:
                return
        if packagedPath.is_file():
            packagedPath.unlink()
            print(f"Removed packaged file: {packagedPath}")
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
                print(f"Note: could not remove temp folder (not empty?): {tempDir}")
    except Exception as e:
        print(f"WARN: temp cleanup failed: {e}", file=sys.stderr)


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
    if user is None:
        here = Path(__file__).resolve().parent
        user = here.parent / "core" / "bunker.db"

    if not packaged or not Path(packaged).is_file():
        print(
            "Could not auto-detect packaged bunker.db. Pass --packaged explicitly.\n"
            f"  packaged={packaged}\n  user={user}",
            file=sys.stderr,
        )
        return 1

    print(f"Packaged: {packaged}")
    print(f"User:     {user}")

    if not Path(user).is_file():
        dest = Path(user)
        if args.dryRun:
            print(f"No existing bunker.db — would install packaged dictionary → {dest}")
            return 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packaged, dest)
        print(f"No existing bunker.db — installed packaged dictionary → {dest}")
        cleanupTempFolder(Path(packaged))
        return 0
    if filesIdentical(Path(packaged), Path(user)):
        print(
            "Live bunker.db already matches packaged — skip merge "
            "(no Common Name / Data Type prompts)"
        )
        if not args.dryRun:
            cleanupTempFolder(Path(packaged))
        return 0

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
    if not updateCommon or not updateTypes:
        print("New rows still receive packaged commonName and datatype.")
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
