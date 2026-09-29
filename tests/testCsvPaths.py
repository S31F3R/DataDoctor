# CSV bunker update accepts a file, a folder, or a quoted *.csv pattern.
# Run from the repo root: python tests/testCsvPaths.py

from __future__ import annotations

import os
import tempfile
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

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
