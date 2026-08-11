#!/usr/bin/env python3
"""
Package DataDoctor for macOS.

Two modes:

  1) Portable zip (default — can stage on any host, intended to run on a Mac):
       dist/DataDoctor-macOS-YYYYMMDD.zip
     Layout:
       Data Doctor.command   (double-click launcher)
       UPDATE.txt
       LICENSE
       README.txt
       Project Files/
         DataDoctor.py
         core/  ui/  quickLook/  oracle/  requirements.txt
         scripts/updateBunker.py
         temp/bunker.db       (packaged dictionary for merge)
         .venv/               (optional, if present and not --skip-venv)

  2) Native .app via PyInstaller (must run on macOS with PyInstaller installed):
       python scripts/packageMac.py --app
       → dist/DataDoctor-macOS-YYYYMMDD.app  (and optional zip of the .app)

Prerequisites for a usable package on the target Mac:
  - Python 3.13.x
  - Project Files/.venv with requirements.txt, or a system/user env that has them

Run from project root:
  python scripts/packageMac.py
  python scripts/packageMac.py --out dist/DataDoctor-macOS.zip
  python scripts/packageMac.py --app
  python scripts/packageMac.py --skip-venv
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
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


def writeReadme(stage: Path):
    text = f"""DataDoctor — macOS package
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

REQUIREMENTS
------------
- macOS 12+ recommended
- Python 3.13.x (https://www.python.org/downloads/ or Homebrew: brew install python@3.13)

FIRST RUN
---------
1) Unzip this package to a folder you can write to (e.g. ~/Applications/DataDoctor
   or ~/Documents/DataDoctor).
2) Prefer: double-click "Data Doctor.command"
   - First launch may ask Gatekeeper to allow the script; right-click → Open if needed.
   - The script prefers Project Files/.venv when present.
3) Or from Terminal:
     cd "/path/to/this folder"
     ./Data\\ Doctor.command
4) If dependencies are missing:
     python3 -m venv "Project Files/.venv"
     "Project Files/.venv/bin/python" -m pip install -r "Project Files/requirements.txt"

UPDATING AN EXISTING INSTALL
----------------------------
See UPDATE.txt. Short version:
  - Copy new files over your install
  - Do NOT overwrite live Project Files/core/bunker.db if you have local
    dictionary edits — merge with Project Files/temp/bunker.db instead
  - From the package root:
      python3 "Project Files/scripts/updateBunker.py"

AQUARIUS CERTIFICATES
---------------------
Create Project Files/certs/ yourself if needed and place aquarius.pem or a
.cer/.crt file there. The app never creates certs folders. .pfx is not supported.

SUPPORT NOTES
-------------
- Config / logs: ~/Library/Application Support/Data Doctor/  (or Qt AppConfigLocation)
- Oracle Instant Client: optional under Project Files/oracle/ when packaged
"""
    (stage / "README.txt").write_text(text.strip() + "\n", encoding="utf-8")


def writeUpdateReadme(stage: Path):
    text = """DataDoctor — updates (macOS)

FULL APP UPDATE
---------------
1) Close DataDoctor.
2) Drop a DataDoctor-Python-*.zip (from packagePython.py) into Update/
3) Run:
     ./applyUpdate.sh
   Or:
     python3 "Project Files/scripts/applyUpdate.py"
4) Restart DataDoctor.

DICTIONARY-ONLY MERGE
---------------------
  python3 "Project Files/scripts/updateBunker.py"
  python3 "Project Files/scripts/updateBunker.py" --dry-run
"""
    (stage / "UPDATE.txt").write_text(text.strip() + "\n", encoding="utf-8")


def writeLauncher(stage: Path):
    """Double-clickable .command script (bash) for macOS Finder."""
    script = r'''#!/bin/bash
# Data Doctor launcher (macOS)
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY=""
if [ -x "$ROOT/Project Files/.venv/bin/python" ]; then
  PY="$ROOT/Project Files/.venv/bin/python"
elif [ -x "$ROOT/Project Files/.venv/bin/python3" ]; then
  PY="$ROOT/Project Files/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
else
  osascript -e 'display dialog "Python 3.13 was not found.\nInstall Python 3.13 from python.org or Homebrew, then try again." buttons {"OK"} default button 1 with title "Data Doctor"' 2>/dev/null || \
    echo "ERROR: Python 3 not found" >&2
  exit 1
fi

APP="$ROOT/Project Files/DataDoctor.py"
if [ ! -f "$APP" ]; then
  echo "ERROR: DataDoctor.py missing under Project Files/" >&2
  exit 1
fi

# Prefer bundled Qt / SSL from venv; keep user env otherwise
export PYTHONUNBUFFERED=1
exec "$PY" "$APP" "$@"
'''
    path = stage / "Data Doctor.command"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def stagePortable(root: Path, stage: Path, skipVenv: bool) -> None:
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    projectFiles = stage / "Project Files"
    projectFiles.mkdir(parents=True, exist_ok=True)

    for name in ("core", "ui", "quickLook", "oracle"):
        src = root / name
        if src.exists():
            copyTree(src, projectFiles / name, ignoreNames={'.git', '__pycache__', 'client'})
            if name == "oracle":
                client = root / "oracle" / "client"
                if client.exists():
                    copyTree(
                        client,
                        projectFiles / "oracle" / "client",
                        ignoreNames={'__pycache__'},
                    )

    pySrc = root / "DataDoctor.py"
    if pySrc.is_file():
        shutil.copy2(pySrc, projectFiles / "DataDoctor.py")
    else:
        print("WARN: DataDoctor.py missing", file=sys.stderr)

    req = root / "requirements.txt"
    if req.is_file():
        shutil.copy2(req, projectFiles / "requirements.txt")

    licenseSrc = root / "LICENSE"
    if licenseSrc.is_file():
        shutil.copy2(licenseSrc, stage / "LICENSE")

    scriptsDir = projectFiles / "scripts"
    scriptsDir.mkdir(parents=True, exist_ok=True)
    updateBunkerSrc = root / "launcher" / "Project Files" / "scripts" / "updateBunker.py"
    if not updateBunkerSrc.is_file():
        for alt in (
            root / "scripts" / "updateBunker.py",
            root / "launcher" / "updateBunker.py",
        ):
            if alt.is_file():
                updateBunkerSrc = alt
                break
    if updateBunkerSrc.is_file():
        shutil.copy2(updateBunkerSrc, scriptsDir / "updateBunker.py")
    else:
        print("WARN: updateBunker.py not found", file=sys.stderr)

    applyUpdateSrc = root / "scripts" / "applyUpdate.py"
    if applyUpdateSrc.is_file():
        shutil.copy2(applyUpdateSrc, scriptsDir / "applyUpdate.py")
    else:
        print("WARN: applyUpdate.py not found", file=sys.stderr)

    bunkerSrc = root / "core" / "bunker.db"
    tempDir = projectFiles / "temp"
    if bunkerSrc.is_file():
        tempDir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bunkerSrc, tempDir / "bunker.db")
        print("Packaged bunker.db → Project Files/temp/bunker.db")
    else:
        print("WARN: core/bunker.db missing — temp merge payload not packaged", file=sys.stderr)

    updateDrop = stage / "Update"
    updateDrop.mkdir(parents=True, exist_ok=True)
    (updateDrop / "README.txt").write_text(
        "Drop a DataDoctor-Python-*.zip here (from packagePython.py), then run applyUpdate.sh from the install root.\n",
        encoding="utf-8",
    )
    applySh = stage / "applyUpdate.sh"
    applySh.write_text(
        """#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY=""
if [ -x "$ROOT/Project Files/.venv/bin/python" ]; then
  PY="$ROOT/Project Files/.venv/bin/python"
elif [ -x "$ROOT/Project Files/.venv/bin/python3" ]; then
  PY="$ROOT/Project Files/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  PY="python"
fi
SCRIPT="$ROOT/Project Files/scripts/applyUpdate.py"
if [ ! -f "$SCRIPT" ]; then
  echo "ERROR: applyUpdate.py not found" >&2
  exit 1
fi
exec "$PY" "$SCRIPT" "$@"
""",
        encoding="utf-8",
    )
    applySh.chmod(0o755)

    writeLauncher(stage)
    writeReadme(stage)
    writeUpdateReadme(stage)

    venv = root / ".venv"
    if not skipVenv and venv.is_dir():
        print("Copying .venv (this may take a while)...")
        print("NOTE: A Linux-built .venv will not run on macOS. Build the package on a Mac,")
        print("      or use --skip-venv and create the venv on the target machine.")
        copyTree(
            venv,
            projectFiles / ".venv",
            ignoreNames={'__pycache__', '.git'},
        )
    elif skipVenv:
        print("Skipping .venv (--skip-venv)")
    else:
        print("WARN: .venv not found; package will need a local Python env", file=sys.stderr)


def zipStage(stage: Path, outZip: Path) -> None:
    outZip.parent.mkdir(parents=True, exist_ok=True)
    if outZip.exists():
        outZip.unlink()
    with zipfile.ZipFile(outZip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(stage):
            for name in files:
                full = Path(root) / name
                rel = full.relative_to(stage)
                zf.write(full, rel.as_posix())
    print(f"Wrote {outZip} ({outZip.stat().st_size // 1024} KiB)")


def buildApp(root: Path, outApp: Path, workPath: Path) -> int:
    """PyInstaller windowed .app — must run on macOS."""
    if sys.platform != "darwin":
        print(
            "ERROR: --app requires macOS (PyInstaller .app is host-native).\n"
            "  On a Mac: python scripts/packageMac.py --app\n"
            "  Or use the portable zip (default) without --app.",
            file=sys.stderr,
        )
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "ERROR: PyInstaller not installed.\n"
            "  pip install pyinstaller",
            file=sys.stderr,
        )
        return 1

    if workPath.exists():
        shutil.rmtree(workPath)
    workPath.mkdir(parents=True)
    distPath = workPath / "dist"

    datas = [
        ("ui", "ui"),
        ("quickLook", "quickLook"),
        ("core", "core"),
        ("oracle", "oracle"),
    ]
    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--noupx",
        "--onedir",
        "--name", "DataDoctor",
        "--distpath", str(distPath),
        "--workpath", str(workPath / "build"),
        "--specpath", str(workPath),
    ]
    iconIcns = root / "ui" / "icons" / "DataDoctor.icns"
    iconPng = root / "ui" / "icons" / "DataDoctor.png"
    if iconIcns.is_file():
        args.extend(["--icon", str(iconIcns)])
    elif iconPng.is_file():
        args.extend(["--icon", str(iconPng)])

    for src, dest in datas:
        srcPath = root / src
        if srcPath.exists():
            args.extend(["--add-data", f"{srcPath}{sep}{dest}"])

    for package in ("oracledb", "cryptography", "keyring", "matplotlib", "pygame"):
        args.extend(["--collect-all", package])

    for mod in (
        "PyQt6",
        "keyring",
        "keyring.backends",
        "keyring.backends.macOS",
        "keyring.backends.chainer",
        "keyring.backends.fail",
        "oracledb",
        "numpy",
        "matplotlib",
        "matplotlib.backends.backend_qtagg",
        "getpass",
        "secrets",
        "ssl",
        "socket",
        "decimal",
        "json",
        "platform",
        "cryptography",
    ):
        args.extend(["--hidden-import", mod])

    args.append(str(root / "DataDoctor.py"))
    print("+", " ".join(args))
    subprocess.check_call(args)

    built = distPath / "DataDoctor.app"
    if not built.is_dir():
        # onedir without .app fallback
        builtDir = distPath / "DataDoctor"
        if builtDir.is_dir():
            print(f"WARN: expected .app; found onedir at {builtDir}", file=sys.stderr)
            if outApp.exists():
                shutil.rmtree(outApp)
            shutil.copytree(builtDir, outApp)
            print(f"Copied onedir → {outApp}")
            return 0
        print(f"ERROR: PyInstaller did not produce DataDoctor.app under {distPath}", file=sys.stderr)
        return 1

    if outApp.exists():
        shutil.rmtree(outApp)
    shutil.copytree(built, outApp)
    print(f"Wrote {outApp}")
    return 0


def main() -> int:
    root = projectRoot()
    parser = argparse.ArgumentParser(description="Package DataDoctor for macOS")
    parser.add_argument(
        "--out",
        default=None,
        help="Output zip or .app path (default under dist/)",
    )
    parser.add_argument(
        "--app",
        action="store_true",
        help="Build a native .app with PyInstaller (macOS host required)",
    )
    parser.add_argument(
        "--skip-venv",
        dest="skipVenv",
        action="store_true",
        help="Do not copy .venv into Project Files (recommended when packaging off-Mac)",
    )
    parser.add_argument(
        "--keep-build",
        dest="keepBuild",
        action="store_true",
        help="Keep intermediate staging / PyInstaller work dirs",
    )
    args = parser.parse_args()

    if not (root / "DataDoctor.py").is_file():
        print("ERROR: DataDoctor.py not found — run from project root", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    host = platform.system()
    print(f"Host: {host} / {platform.machine()}")

    if args.app:
        outApp = Path(args.out) if args.out else (root / "dist" / f"DataDoctor-macOS-{stamp}.app")
        workPath = root / "dist" / f"macAppWork{stamp}"
        try:
            rc = buildApp(root, outApp, workPath)
        finally:
            if not args.keepBuild and workPath.exists():
                shutil.rmtree(workPath, ignore_errors=True)
        return rc

    # Portable zip
    outZip = Path(args.out) if args.out else (root / "dist" / f"DataDoctor-macOS-{stamp}.zip")
    stage = root / "dist" / f"macStage{stamp}"
    try:
        # Off-Mac packaging: skip venv by default so we do not ship a broken Linux env
        skipVenv = args.skipVenv or (sys.platform != "darwin")
        if skipVenv and not args.skipVenv and sys.platform != "darwin":
            print("Not on macOS — staging portable zip with --skip-venv (implicit).")
        stagePortable(root, stage, skipVenv=skipVenv)
        zipStage(stage, outZip)
    finally:
        if not args.keepBuild and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)

    print("Done. On a Mac: unzip, then double-click Data Doctor.command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
