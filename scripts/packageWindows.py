#!/usr/bin/env python3
"""
Build a Windows distribution zip for DataDoctor.

Zip layout (launcher is the zip root):
  Data Doctor.exe          (from launcher/)
  ... other launcher files ...
  LICENSE
  Project Files/
    DataDoctor.pyw         (from DataDoctor.py)
    core/
    ui/
    quickLook/
    oracle/
    .venv/                 (if present)

Run from project root:
  python scripts/packageWindows.py
  python scripts/packageWindows.py --out dist/DataDoctor-Windows.zip
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
        # Skip ignored directory names anywhere in the tree
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


def main():
    root = projectRoot()
    parser = argparse.ArgumentParser(description="Package DataDoctor for Windows")
    parser.add_argument(
        "--out",
        default=None,
        help="Output zip path (default: dist/DataDoctor-Windows-YYYYMMDD.zip)",
    )
    parser.add_argument(
        "--skip-venv",
        dest="skipVenv",
        action="store_true",
        help="Do not copy .venv into Project Files",
    )
    args = parser.parse_args()

    launcher = root / "launcher"
    if not launcher.is_dir():
        print(f"ERROR: launcher/ not found at {launcher}", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    outZip = Path(args.out) if args.out else (root / "dist" / f"DataDoctor-Windows-{stamp}.zip")
    outZip.parent.mkdir(parents=True, exist_ok=True)

    stage = root / "dist" / f"winStage{stamp}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # 1) Everything under launcher → zip root
    copyTree(
        launcher,
        stage,
        ignoreNames={'.git', 'src'},  # src is empty / build leftovers
    )

    # 2) LICENSE at zip root
    licenseSrc = root / "LICENSE"
    if licenseSrc.is_file():
        shutil.copy2(licenseSrc, stage / "LICENSE")

    # 3) Project Files/
    projectFiles = stage / "Project Files"
    projectFiles.mkdir(parents=True, exist_ok=True)

    for name in ("core", "ui", "quickLook", "oracle"):
        src = root / name
        if src.exists():
            copyTree(src, projectFiles / name, ignoreNames={'.git', '__pycache__', 'client'})
            # oracle/client is large / platform-specific — include if present
            if name == "oracle":
                client = root / "oracle" / "client"
                if client.exists():
                    copyTree(client, projectFiles / "oracle" / "client", ignoreNames={'__pycache__'})

    # DataDoctor.py → DataDoctor.pyw
    pySrc = root / "DataDoctor.py"
    if pySrc.is_file():
        shutil.copy2(pySrc, projectFiles / "DataDoctor.pyw")
    else:
        print("WARN: DataDoctor.py missing", file=sys.stderr)

    # requirements for reference
    req = root / "requirements.txt"
    if req.is_file():
        shutil.copy2(req, projectFiles / "requirements.txt")

    # .venv optional
    venv = root / ".venv"
    if not args.skipVenv and venv.is_dir():
        print("Copying .venv (this may take a while)...")
        copyTree(
            venv,
            projectFiles / ".venv",
            ignoreNames={'__pycache__', '.git'},
        )
    elif args.skipVenv:
        print("Skipping .venv (--skip-venv)")
    else:
        print("WARN: .venv not found; package will need a local Python env", file=sys.stderr)

    # Zip it
    if outZip.exists():
        outZip.unlink()
    print(f"Writing {outZip} ...")
    with zipfile.ZipFile(outZip, "w", compression=zipfile.ZIP_DEFLATED) as zipFile:
        for dirPath, dirNames, fileNames in os.walk(stage):
            for fileName in fileNames:
                full = Path(dirPath) / fileName
                arc = full.relative_to(stage).as_posix()
                zipFile.write(full, arcname=arc)

    # Cleanup stage
    shutil.rmtree(stage, ignore_errors=True)
    sizeMb = outZip.stat().st_size / (1024 * 1024)
    print(f"Done: {outZip} ({sizeMb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
