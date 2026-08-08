#!/usr/bin/env python3
"""
Build a raw Python runtime zip for DataDoctor (no launcher, no .venv, no apply scripts).

Contents = what you need to run the app with a local Python:
  DataDoctor.py
  requirements.txt
  README.txt
  LICENSE          (if present)
  core/            (includes bunker.db)
  ui/
  quickLook/
  certs/           (optional Aquarius certs — folder always present)
  oracle/          (optional network admin / Instant Client; client/ skipped by default)

Update / bunker-merge tooling lives on the *launcher* install side (applyUpdate,
updateBunker), not in this zip.

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


def ensureDirInZip(stage: Path, rel: str, readmeText: str | None = None):
    """
    Guarantee a folder is represented in the zip.
    Zip has no empty dirs; write a small README when the folder has no files.
    """
    d = stage / rel
    d.mkdir(parents=True, exist_ok=True)
    hasFiles = any(p.is_file() for p in d.rglob('*'))
    if not hasFiles and readmeText:
        (d / "README.txt").write_text(readmeText.strip() + "\n", encoding="utf-8")


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
    parser.add_argument(
        "--include-oracle-client",
        dest="includeOracleClient",
        action="store_true",
        help="Include oracle/client if present (large / platform-specific)",
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

    # App trees (bunker.db ships inside core/ as normal)
    for name in ("core", "ui", "quickLook"):
        src = root / name
        if src.exists():
            copyTree(src, stage / name, ignoreNames={'.git', '__pycache__'})

    # oracle: network/admin always useful; Instant Client optional/huge
    oracleSrc = root / "oracle"
    if oracleSrc.exists():
        ignore = {'.git', '__pycache__'}
        if not args.includeOracleClient:
            ignore.add('client')
        copyTree(oracleSrc, stage / "oracle", ignoreNames=ignore)
        if not args.includeOracleClient and (oracleSrc / "client").exists():
            print("NOTE: oracle/client skipped (use --include-oracle-client to bundle)")
    ensureDirInZip(
        stage,
        "oracle",
        "Optional Oracle Instant Client / network config.\n"
        "Place Instant Client under oracle/client if needed, or set TNS_ADMIN.\n"
        "sqlnet.ora may live under oracle/network/admin/.\n",
    )

    # certs: user drops Aquarius .pem / .cer here
    certsSrc = root / "certs"
    if certsSrc.exists():
        copyTree(certsSrc, stage / "certs", ignoreNames={'.git', '__pycache__'})
    ensureDirInZip(
        stage,
        "certs",
        "Optional Aquarius TLS certificates.\n"
        "Place aquarius.pem or a .cer/.crt here. .pfx is not supported.\n"
        "The app never creates this folder — keep it next to the app root.\n",
    )

    shutil.copy2(root / "DataDoctor.py", stage / "DataDoctor.py")

    req = root / "requirements.txt"
    if req.is_file():
        shutil.copy2(req, stage / "requirements.txt")

    licenseSrc = root / "LICENSE"
    if licenseSrc.is_file():
        shutil.copy2(licenseSrc, stage / "LICENSE")

    # Version for release notes (tag on GitHub should match core/Version.py)
    try:
        from core.Version import VERSION as appVersion
    except Exception:
        appVersion = "unknown"

    readme = f"""DataDoctor — Python package
Version: {appVersion}
Built: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Raw app tree only (no launcher, no .venv, no update scripts).

LAYOUT
------
  DataDoctor.py
  requirements.txt
  core/          (includes bunker.db)
  ui/
  quickLook/
  certs/         Optional Aquarius certs (aquarius.pem / .cer)
  oracle/        Optional Oracle network admin / Instant Client

MANUAL INSTALL
--------------
1) Unzip somewhere writable.
2) python3 -m venv .venv
3) .venv/bin/pip install -r requirements.txt   (Windows: .venv\\Scripts\\pip ...)
4) .venv/bin/python DataDoctor.py

GITHUB RELEASES
---------------
Attach this zip as DataDoctor-Python.zip (or DataDoctor-Python-vX.Y.Z.zip).
Tag the release vX.Y.Z to match core/Version.py (e.g. v3.0.0 or v3.0.1-rc.1).
Mark beta/RC releases as Pre-release on GitHub.

UPDATING A LAUNCHER INSTALL
---------------------------
Launcher packages ship applyUpdate + updateBunker. Drop this zip into that
install's Update/ folder and run applyUpdate — merge/pip are handled on the
launcher side, not by anything inside this zip.
"""
    (stage / "README.txt").write_text(readme.strip() + "\n", encoding="utf-8")

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
    print("Raw Python tree only. Launcher installs apply this via Update/ + applyUpdate.")

    if not args.keepBuild and stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
