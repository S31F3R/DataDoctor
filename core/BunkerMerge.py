# BunkerMerge.py
# Merge a packaged bunker.db into the live user dictionary without wiping edits.
#
# Existing rows: siteName/database always; commonName/datatype only if allowed.
# New rows (packaged keys the user does not have): always insert with packaged
# commonName and datatype, even when the user said N to those updates.

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MERGE_THREADS = 6

ALWAYS_UPDATE_FIELDS = ("siteName", "database")
OPTIONAL_UPDATE_FIELDS = ("commonName", "datatype", "dataType")
UPDATE_FIELDS = ALWAYS_UPDATE_FIELDS + OPTIONAL_UPDATE_FIELDS
FILL_BLANK_FIELDS = (
    "valuePrecision",
    "precisionOverride",
    "expectedMin",
    "expectedMax",
    "cuttoffMin",
    "cutoffMax",
    "rateOfChange",
)


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


def filesIdentical(a: Path, b: Path) -> bool:
    try:
        if a.resolve() == b.resolve():
            return True
    except Exception:
        pass
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    h1 = hashlib.sha256()
    h2 = hashlib.sha256()
    try:
        with open(a, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h1.update(chunk)
        with open(b, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h2.update(chunk)
    except OSError:
        return False
    return h1.digest() == h2.digest()


def _rowKey(dataId, siteId):
    return (
        None if dataId is None else str(dataId),
        None if siteId is None else str(siteId),
    )


def _splitRows(rows, n):
    if not rows:
        return []
    n = max(1, min(n, len(rows)))
    length = len(rows)
    base, extra = divmod(length, n)
    out = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        if size <= 0:
            continue
        out.append(rows[start:start + size])
        start += size
    return out


def _planChunk(
    rows,
    userByKey,
    pkgCols,
    pkgDataId,
    pkgSiteId,
    usrDataId,
    usrSiteId,
    usrMap,
    mergeFieldNames,
    pkgFields,
    usrFields,
    fillBlankLower,
    optionalFieldLower,
    optionalAllowed,
):
    updates = []
    inserts = []
    skipped = 0
    for row in rows:
        dataId = row.get(pkgDataId)
        siteId = row.get(pkgSiteId)
        if dataId is None and siteId is None:
            skipped += 1
            continue
        existing = userByKey.get(_rowKey(dataId, siteId))
        if existing is not None:
            sets = []
            params = []
            for field in mergeFieldNames:
                pCol = pkgFields.get(field)
                uCol = usrFields.get(field)
                if not pCol or not uCol:
                    continue
                newVal = row.get(pCol)
                oldVal = existing.get(uCol)
                if newVal is None or str(newVal).strip() == "":
                    continue
                if oldVal is not None and str(oldVal) == str(newVal):
                    continue
                if field.lower() in fillBlankLower:
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
                updates.append((sql, params))
            else:
                skipped += 1
        else:
            # New row: always take packaged commonName/datatype (N does not skip these)
            insertCols = []
            insertVals = []
            for c in pkgCols:
                if c.lower() in usrMap:
                    insertCols.append(usrMap[c.lower()])
                    insertVals.append(row.get(c))
            if not insertCols:
                skipped += 1
                continue
            placeholders = ", ".join("?" * len(insertCols))
            colList = ", ".join(insertCols)
            sql = f"INSERT INTO dataDictionary ({colList}) VALUES ({placeholders})"
            inserts.append((sql, insertVals))
    return updates, inserts, skipped


def merge(
    packagedPath: Path,
    userPath: Path,
    dryRun: bool = False,
    updateCommonNames: bool = False,
    updateDatatypes: bool = False,
    log=print,
) -> int:
    packagedPath = Path(packagedPath)
    userPath = Path(userPath)
    if not packagedPath.is_file():
        log(f"ERROR: packaged bunker not found: {packagedPath}")
        return 1
    if not userPath.is_file():
        log(f"ERROR: user bunker not found: {userPath}")
        return 1
    if packagedPath.resolve() == userPath.resolve():
        log(
            "ERROR: packaged and user paths are the same file. "
            "Pass a separate --packaged (from the update) and --user (live) path."
        )
        return 1

    if not dryRun:
        for old in userPath.parent.glob(userPath.name + ".bak*"):
            try:
                old.unlink()
                log(f"Removed old backup: {old}")
            except OSError as e:
                log(f"WARN: could not remove {old}: {e}")
        backup = userPath.with_suffix(userPath.suffix + ".bak")
        shutil.copy2(userPath, backup)
        log(f"Backup: {backup}")

    log("Merging...")

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
            log("ERROR: dataID/siteID columns missing in one of the databases")
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

        pkgRows = [dict(row) for row in pkg.execute("SELECT * FROM dataDictionary").fetchall()]
        userByKey = {}
        for row in usr.execute("SELECT * FROM dataDictionary").fetchall():
            d = dict(row)
            userByKey[_rowKey(d.get(usrDataId), d.get(usrSiteId))] = d

        workers = min(MERGE_THREADS, max(1, len(pkgRows)))
        chunks = _splitRows(pkgRows, workers)
        updates = []
        inserts = []
        skipped = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _planChunk,
                    chunk,
                    userByKey,
                    pkgCols,
                    pkgDataId,
                    pkgSiteId,
                    usrDataId,
                    usrSiteId,
                    usrMap,
                    mergeFieldNames,
                    pkgFields,
                    usrFields,
                    fillBlankLower,
                    optionalFieldLower,
                    optionalAllowed,
                )
                for chunk in chunks
            ]
            for fut in as_completed(futures):
                chunkUpdates, chunkInserts, chunkSkipped = fut.result()
                updates.extend(chunkUpdates)
                inserts.extend(chunkInserts)
                skipped += chunkSkipped

        if not dryRun:
            for sql, params in updates:
                usr.execute(sql, params)
            for sql, params in inserts:
                usr.execute(sql, params)
            usr.commit()

        log(
            f"{'DRY-RUN ' if dryRun else ''}Merge complete: "
            f"{len(updates)} updated, {len(inserts)} inserted, {skipped} unchanged/skipped"
        )
        return 0
    finally:
        pkg.close()
        usr.close()


def promptAndMergeGui(parent, packagedPath, userPath) -> int:
    """Qt y/n for AppImage startup merge. New rows still get packaged names/types."""
    from PyQt6.QtWidgets import QMessageBox

    packagedPath = Path(packagedPath)
    userPath = Path(userPath)
    if filesIdentical(packagedPath, userPath):
        return 0

    def _ask(title, text):
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(
            "New dictionary rows (IDs you do not already have) still receive "
            "the packaged common name and data type."
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    updateCommon = _ask(
        "Data Dictionary",
        "Update Data Dictionary Common Names on existing rows?",
    )
    updateTypes = _ask(
        "Data Dictionary",
        "Update Data Dictionary Data Types on existing rows?",
    )

    def _log(msg):
        try:
            from core import Logic
            Logic.logMessage("INFO", f"BunkerMerge: {msg}")
        except Exception:
            print(msg)

    return merge(
        packagedPath,
        userPath,
        dryRun=False,
        updateCommonNames=updateCommon,
        updateDatatypes=updateTypes,
        log=_log,
    )
