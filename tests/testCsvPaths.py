# CSV bunker update accepts a file, a folder, or a quoted *.csv pattern.
# Run from the repo root: python tests/testCsvPaths.py

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "updateBunkerFromCsv.py")

import importlib.util

spec = importlib.util.spec_from_file_location("updateBunkerFromCsv", SCRIPT)
csvUpdate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(csvUpdate)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def touch(path: Path, text="SITE_DATATYPE_ID,SITE_ID\n1,2\n"):
    path.write_text(text, encoding="utf-8")


def main():
    errors = 0
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "Exports"
        folder.mkdir()
        touch(folder / "a.csv")
        touch(folder / "b.csv")
        (folder / "notes.txt").write_text("nope", encoding="utf-8")
        one = Path(tmp) / "only.csv"
        touch(one)

        files = csvUpdate.expandCsvPaths([one])
        if [p.name for p in files] != ["only.csv"]:
            errors += fail("file", files)

        fromFolder = csvUpdate.expandCsvPaths([folder])
        names = sorted(p.name for p in fromFolder)
        if names != ["a.csv", "b.csv"]:
            errors += fail("folder", names)

        pattern = str(folder / "*.csv")
        fromGlob = csvUpdate.expandCsvPaths([pattern])
        globNames = sorted(p.name for p in fromGlob)
        if globNames != ["a.csv", "b.csv"]:
            errors += fail("glob", globNames)

        try:
            csvUpdate.expandCsvPaths([str(folder / "*.csvx")])
        except SystemExit:
            pass
        else:
            errors += fail("missing glob", "should exit")

        try:
            csvUpdate.expandCsvPaths([folder / "missing"])
        except SystemExit:
            pass
        else:
            errors += fail("missing file", "should exit")

        empty = Path(tmp) / "empty"
        empty.mkdir()
        try:
            csvUpdate.expandCsvPaths([empty])
        except SystemExit:
            pass
        else:
            errors += fail("empty folder", "should exit")

        db = Path(tmp) / "bunker.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE dataDictionary ("
            "dataID TEXT, siteID TEXT, database TEXT, siteName TEXT, "
            "commonName TEXT, datatype TEXT, precisionOverride TEXT)"
        )
        for i in range(3000):
            common = "" if i == 7 else "Keep"
            conn.execute(
                "INSERT INTO dataDictionary VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(i), str(i), "USBR-LCHDB", f"Old{i}", common, "Flow", "DEC(2)"),
            )
        conn.commit()
        conn.close()
        lines = [
            "SITE_DATATYPE_ID,SITE_ID,SITE_NAME,SITE_COMMON_NAME,DATATYPE_NAME,DB_SITE_CODE"
        ]
        for i in range(3500):
            common = "Filled" if i == 7 else "Nope"
            lines.append(f"{i},{i},New{i},{common},Stage,LC")
        csvPath = folder / "bulk.csv"
        csvPath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        started = time.perf_counter()
        rc = csvUpdate.mergeCsv(
            db, [csvPath], dryRun=False,
            updateCommonNames=False, updateDatatypes=False,
        )
        elapsed = time.perf_counter() - started
        if rc != 0:
            errors += fail("merge rc", rc)
        if elapsed > 3:
            errors += fail("merge speed", f"{elapsed:.2f}s")
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        kept = conn.execute(
            "SELECT * FROM dataDictionary WHERE dataID = ? AND siteID = ?",
            ("0", "0"),
        ).fetchone()
        filled = conn.execute(
            "SELECT * FROM dataDictionary WHERE dataID = ? AND siteID = ?",
            ("7", "7"),
        ).fetchone()
        added = conn.execute(
            "SELECT * FROM dataDictionary WHERE dataID = ? AND siteID = ?",
            ("3200", "3200"),
        ).fetchone()
        conn.close()
        if kept["siteName"] != "New0" or kept["commonName"] != "Keep":
            errors += fail("kept common", dict(kept))
        if kept["precisionOverride"] != "DEC(2)":
            errors += fail("qaqc", kept["precisionOverride"])
        if filled["commonName"] != "Filled":
            errors += fail("blank common", filled["commonName"])
        if added is None or added["siteName"] != "New3200":
            errors += fail("insert", added)

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
