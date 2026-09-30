# Dictionary merge fills blank QAQC fields and keeps values already set.
# Run from the repo root: python tests/testBunkerFill.py

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.BunkerMerge import merge

COLUMNS = (
    "dataID", "siteID", "database", "siteName", "commonName", "datatype",
    "valuePrecision", "precisionOverride",
    "expectedMin", "expectedMax", "cuttoffMin", "cutoffMax", "rateOfChange",
)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def makeDb(path: Path, rows):
    conn = sqlite3.connect(path)
    cols = ", ".join(f"{name} TEXT" for name in COLUMNS)
    conn.execute(f"CREATE TABLE dataDictionary ({cols})")
    placeholders = ", ".join("?" * len(COLUMNS))
    for row in rows:
        values = [row.get(name) for name in COLUMNS]
        conn.execute(
            f"INSERT INTO dataDictionary ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            values,
        )
    conn.commit()
    conn.close()


def readRow(path: Path, dataId, siteId):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM dataDictionary WHERE dataID = ? AND siteID = ?",
        (dataId, siteId),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def main():
    errors = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        packaged = tmp / "packaged.db"
        user = tmp / "user.db"
        makeDb(packaged, [
            {
                "dataID": "10", "siteID": "1", "database": "USBR-LCHDB",
                "siteName": "Pack Site", "commonName": "Pack Name", "datatype": "Flow",
                "valuePrecision": "Discharge", "precisionOverride": "DEC(4)",
                "expectedMin": "0", "expectedMax": "100",
                "cuttoffMin": "1", "cutoffMax": "90", "rateOfChange": "5",
            },
            {
                "dataID": "11", "siteID": "1", "database": "USBR-LCHDB",
                "siteName": "Blank Site", "commonName": "Blank Name", "datatype": "Stage",
                "precisionOverride": "SIG(3)", "expectedMax": "12",
            },
            {
                "dataID": "12", "siteID": "2", "database": "USBR-YAOHDB",
                "siteName": "New Site", "commonName": "New Name", "datatype": "Flow",
                "precisionOverride": "DEC(1)", "expectedMin": "3",
            },
        ])
        makeDb(user, [
            {
                "dataID": "10", "siteID": "1", "database": "USBR-LCHDB",
                "siteName": "Old Site", "commonName": "My Name", "datatype": "Flow",
                "valuePrecision": "Stage", "precisionOverride": "DEC(2)",
                "expectedMin": "0", "expectedMax": "8",
                "cuttoffMin": "0", "cutoffMax": "7", "rateOfChange": "2",
            },
            {
                "dataID": "11", "siteID": "1", "database": "USBR-LCHDB",
                "siteName": "Blank Site", "commonName": "Keep", "datatype": "Stage",
                "precisionOverride": "", "expectedMin": None, "expectedMax": "",
            },
        ])
        seen = []

        def onProgress(percent, message):
            seen.append((percent, message))

        rc = merge(
            packaged, user, dryRun=False,
            updateCommonNames=False, updateDatatypes=False, log=lambda *_a, **_k: None,
            onProgress=onProgress,
        )
        if rc != 0:
            errors += fail("merge", f"exit {rc}")
        if not seen or seen[-1][0] != 100:
            errors += fail("progress end", seen[-1] if seen else "no ticks")
        if any(seen[i][0] > seen[i + 1][0] for i in range(len(seen) - 1)):
            errors += fail("progress order", seen)
        if not any("Merging" in message or "Writing" in message for _pct, message in seen):
            errors += fail("progress label", seen)
        conn = sqlite3.connect(user)
        indexes = conn.execute("PRAGMA index_list(dataDictionary)").fetchall()
        conn.close()
        if indexes:
            errors += fail("merge index", indexes)
        kept = readRow(user, "10", "1")
        if kept["precisionOverride"] != "DEC(2)":
            errors += fail("precisionOverride", kept["precisionOverride"])
        if str(kept["expectedMin"]) != "0":
            errors += fail("expectedMin zero", kept["expectedMin"])
        if str(kept["expectedMax"]) != "8":
            errors += fail("expectedMax", kept["expectedMax"])
        if str(kept["cuttoffMin"]) != "0":
            errors += fail("cuttoffMin zero", kept["cuttoffMin"])
        if str(kept["rateOfChange"]) != "2":
            errors += fail("rateOfChange", kept["rateOfChange"])
        if kept["valuePrecision"] != "Stage":
            errors += fail("valuePrecision", kept["valuePrecision"])
        if kept["commonName"] != "My Name":
            errors += fail("commonName", kept["commonName"])
        if kept["siteName"] != "Pack Site":
            errors += fail("siteName", kept["siteName"])

        filled = readRow(user, "11", "1")
        if filled["precisionOverride"] != "SIG(3)":
            errors += fail("fill override", filled["precisionOverride"])
        if str(filled["expectedMax"]) != "12":
            errors += fail("fill expectedMax", filled["expectedMax"])
        if filled["commonName"] != "Keep":
            errors += fail("blank row name", filled["commonName"])

        inserted = readRow(user, "12", "2")
        if inserted is None:
            errors += fail("insert", "new row missing")
        elif inserted["precisionOverride"] != "DEC(1)":
            errors += fail("insert override", inserted["precisionOverride"])

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
