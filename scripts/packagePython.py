#!/usr/bin/env python3
"""
Build a raw Python runtime zip for DataDoctor (no launcher, no .venv).

Contents are the app files you point Python at under Project Files/:
  DataDoctor.py / DataDoctor.pyw
  requirements.txt
  core/          (bunker.db also under temp/ as merge source for applyUpdate)
  ui/
  quickLook/     (stock snippets; apply does not delete user-added files)
  VERSION.txt
  scripts/updateBunker.py  (optional merge helper)

Typical uses:
  - Drop into an existing launcher install's Update/ folder → run applyUpdate
  - Manual/raw install: unzip and run with a local Python 3.13 + venv

Run from project root:
  python scripts/packagePython.py
  python scripts/packagePython.py --out dist/DataDoctor-Python.zip
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


def projectRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def copyTree(src: Path, dst: Path, ignoreNames=None):
    ignoreNames = set(ignoreNames or [])
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rootPath = Path(root)
        rel = rootPath.relative_to(src)
        dirs[:] = [
            d for d in dirs
            if d not in ignoreNames and not d.startswith('__pycache__')
        ]
        outDir = dst / rel
        outDir.mkdir(parents=True, exist_ok=True)
        for fileName in files:
            if fileName.endswith(('.pyc', '.pyo')):
                continue
            if fileName in ignoreNames:
                continue
            shutil.copy2(rootPath / fileName, outDir / fileName)


def main() -> int:
    root = projectRoot()
    parser = argparse.ArgumentParser(
        description="Package DataDoctor as a raw Python runtime zip"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output zip path (default: dist/DataDoctor-Python-YYYYMMDD.zip)",
    )
    parser.add_argument(
        "--keep-build",
        dest="keepBuild",
        action="store_true",
        help="Keep staging directory under dist/",
    )
    args = parser.parse_args()

    if not (root / "DataDoctor.py").is_file():
        print("ERROR: DataDoctor.py not found — run from project root", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    outZip = Path(args.out) if args.out else (root / "dist" / f"DataDoctor-Python-{stamp}.zip")
    outZip.parent.mkdir(parents=True, exist_ok=True)
    stage = root / "dist" / f"pythonStage{stamp}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # Payload root = contents that land under Project Files/
    for name in ("core", "ui", "quickLook"):
        src = root / name
        if src.exists():
            copyTree(src, stage / name, ignoreNames={'.git', '__pycache__', 'client'})

    shutil.copy2(root / "DataDoctor.py", stage / "DataDoctor.py")
    # Windows launcher expects .pyw name in some installs — include both
    shutil.copy2(root / "DataDoctor.py", stage / "DataDoctor.pyw")

    req = root / "requirements.txt"
    if req.is_file():
        shutil.copy2(req, stage / "requirements.txt")

    # Bunker as merge source (applyUpdate uses temp/ for updateBunker)
    bunker = root / "core" / "bunker.db"
    if bunker.is_file():
        (stage / "temp").mkdir(parents=True, exist_ok=True)
        shutil.copy2(bunker, stage / "temp" / "bunker.db")

    updateBunker = root / "launcher" / "Project Files" / "scripts" / "updateBunker.py"
    if not updateBunker.is_file():
        updateBunker = root / "scripts" / "updateBunker.py"
    if updateBunker.is_file():
        (stage / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(updateBunker, stage / "scripts" / "updateBunker.py")

    versionText = (
        f"DataDoctor Python package\n"
        f"Built: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Raw runtime tree (no launcher / venv).\n"
        f"Update path: drop into install Update/ and run applyUpdate.\n"
        f"Manual path: unzip, create a venv, pip install -r requirements.txt, run DataDoctor.py.\n"
    )
    (stage / "VERSION.txt").write_text(versionText, encoding="utf-8")

    if outZip.exists():
        outZip.unlink()
    with zipfile.ZipFile(outZip, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(stage):
            for name in files:
                full = Path(dirpath) / name
                rel = full.relative_to(stage)
                zf.write(full, rel.as_posix())

    sizeKiB = outZip.stat().st_size // 1024
    print(f"Wrote {outZip} ({sizeKiB} KiB)")
    print("Use: drop into <install>/Update/ then applyUpdate, or unzip for a raw Python run.")

    if not args.keepBuild and stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
