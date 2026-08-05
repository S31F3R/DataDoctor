#!/usr/bin/env python3
"""
Build a Windows distribution zip for DataDoctor.

Zip layout (launcher is the zip root):
  Data Doctor.exe          (from launcher/)
  updateBunker.cmd
  README.txt               (generated each run)
  UPDATE.txt               (how to merge bunker.db)
  LICENSE
  python-3.13.x-amd64.exe  (if present under launcher/)
  Project Files/
    DataDoctor.pyw
    core/                  (live bunker.db stays here for the user)
    ui/
    quickLook/
    oracle/
    scripts/updateBunker.py
    temp/bunker.db         (packaged dictionary for merge — do not overwrite live)
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


def writeReadme(stage: Path, hasPythonInstaller: bool, installerName: str | None):
    """Generate README.txt at zip root (rebuilt every package run)."""
    installerBlock = ""
    if hasPythonInstaller and installerName:
        installerBlock = f"""
2) Install Python 3.13 (if needed)
   - Double-click: {installerName}
   - Or open a Command Prompt and check what you already have:
       python --version
     You want something like: Python 3.13.x
   - If the command is not found or the version is older than 3.13, run the
     installer above (or download Python 3.13 from python.org).
   - During install, enable "Add python.exe to PATH" if offered.
"""
    else:
        installerBlock = """
2) Install Python 3.13 (if needed)
   - Open a Command Prompt and run:
       python --version
     You want something like: Python 3.13.x
   - If the command is not found or the version is older than 3.13, install
     Python 3.13 from https://www.python.org/downloads/
   - During install, enable "Add python.exe to PATH" if offered.
"""

    text = f"""DataDoctor — Windows package
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

REQUIREMENTS
------------
- Windows 10/11
- Python 3.13.x (the app is tested with 3.13)
{installerBlock}
FIRST RUN
---------
1) Unzip this package to a folder you can write to (e.g. Documents\\DataDoctor).
3) Prefer: double-click "Data Doctor.exe" (VB launcher).
   Or: open Project Files and run DataDoctor.pyw with Python 3.13.
4) If dependencies are missing and you use a Project Files\\.venv, that env is
   preferred. Otherwise install from Project Files\\requirements.txt:
       python -m pip install -r "Project Files\\requirements.txt"

UPDATING AN EXISTING INSTALL
----------------------------
See UPDATE.txt next to this file. Short version:
  - Copy new files over your install
  - Do NOT overwrite your live Project Files\\core\\bunker.db with the zip's
    core copy if you have local dictionary edits — use updateBunker.cmd instead
  - Packaged dictionary for merge: Project Files\\temp\\bunker.db

AQUARIUS CERTIFICATES
---------------------
Create Project Files\\certs\\ yourself if needed and place aquarius.pem or a
.cer/.crt file there. The app never creates certs folders. .pfx is not supported.

SUPPORT NOTES
-------------
- Logs live under your user AppData config folder for Data Doctor.
- SQL / Oracle Instant Client may be under Project Files\\oracle\\ when packaged.
"""
    (stage / "README.txt").write_text(text.strip() + "\n", encoding="utf-8")


def writeUpdateReadme(stage: Path):
    text = """DataDoctor — updating bunker.db (data dictionary)

When you install a new package over an existing copy, your live data dictionary
is Project Files\\core\\bunker.db. The package also ships a fresh dictionary at:

  Project Files\\temp\\bunker.db

That temp file is the *source* for merges. Your live core\\bunker.db is the
*destination* (user data you keep).

HOW TO MERGE
------------
1) Close DataDoctor.
2) From the install root (where Data Doctor.exe and updateBunker.cmd live),
   double-click updateBunker.cmd
   Or in Command Prompt:
     updateBunker.cmd
3) The script will:
     - Back up your live bunker.db
     - Merge dictionary rows from Project Files\\temp\\bunker.db into
       Project Files\\core\\bunker.db
     - Only update dataType / siteName / valuePrecision / database on match
       (dataID + siteID); insert new rows; never delete your rows
     - Remove Project Files\\temp\\ (and the packaged bunker.db) when done

If paths differ, pass them explicitly:
  python "Project Files\\scripts\\updateBunker.py" --packaged "Project Files\\temp\\bunker.db" --user "Project Files\\core\\bunker.db"

Dry run (no writes):
  python "Project Files\\scripts\\updateBunker.py" --dry-run
"""
    (stage / "UPDATE.txt").write_text(text.strip() + "\n", encoding="utf-8")


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
    #    Skip nested Project Files content we rebuild below (except we re-add scripts)
    copyTree(
        launcher,
        stage,
        ignoreNames={'.git', 'src', '__pycache__'},
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

    # Windows taskbar/window icon: .ico must sit next to the .pyw for some shells
    icoSrc = root / "ui" / "icons" / "DataDoctor.ico"
    if icoSrc.is_file():
        shutil.copy2(icoSrc, projectFiles / "DataDoctor.ico")
        print("Copied DataDoctor.ico next to DataDoctor.pyw")
    else:
        print("WARN: ui/icons/DataDoctor.ico missing", file=sys.stderr)

    # requirements for reference
    req = root / "requirements.txt"
    if req.is_file():
        shutil.copy2(req, projectFiles / "requirements.txt")

    # scripts: updateBunker.py lives under Project Files/scripts (not zip root)
    scriptsDir = projectFiles / "scripts"
    scriptsDir.mkdir(parents=True, exist_ok=True)
    updateBunkerSrc = (
        root / "launcher" / "Project Files" / "scripts" / "updateBunker.py"
    )
    if not updateBunkerSrc.is_file():
        # Fallbacks if moved later
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

    # Packaged bunker.db for merge → Project Files/temp/ (live user DB is core/)
    bunkerSrc = root / "core" / "bunker.db"
    tempDir = projectFiles / "temp"
    if bunkerSrc.is_file():
        tempDir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bunkerSrc, tempDir / "bunker.db")
        print(f"Packaged bunker.db → Project Files/temp/bunker.db")
    else:
        print("WARN: core/bunker.db missing — temp merge payload not packaged", file=sys.stderr)

    # updateBunker.cmd at zip root must call Project Files\\scripts\\updateBunker.py
    cmdPath = stage / "updateBunker.cmd"
    cmdPath.write_text(
        "\r\n".join([
            "@echo off",
            "REM Merge packaged Project Files\\temp\\bunker.db into live core\\bunker.db",
            "setlocal",
            'cd /d "%~dp0"',
            'set "PY="',
            'if exist "Project Files\\.venv\\Scripts\\python.exe" set "PY=Project Files\\.venv\\Scripts\\python.exe"',
            'if not defined PY if exist ".venv\\Scripts\\python.exe" set "PY=.venv\\Scripts\\python.exe"',
            'if not defined PY set "PY=python"',
            'set "SCRIPT=%~dp0Project Files\\scripts\\updateBunker.py"',
            'if not exist "%SCRIPT%" (',
            "  echo ERROR: updateBunker.py not found at Project Files\\scripts\\",
            "  pause",
            "  exit /b 1",
            ")",
            '"%PY%" "%SCRIPT%" %*',
            "set ERR=%ERRORLEVEL%",
            "if %ERR% neq 0 (",
            "  echo.",
            "  echo updateBunker failed with exit code %ERR%",
            "  pause",
            ")",
            "endlocal",
            "exit /b %ERR%",
            "",
        ]),
        encoding="utf-8",
        newline="\r\n",
    )

    # README + UPDATE (generated every run so installer version notes stay current)
    installerName = None
    hasInstaller = False
    for p in stage.glob("python-*.exe"):
        hasInstaller = True
        installerName = p.name
        break
    writeReadme(stage, hasInstaller, installerName)
    writeUpdateReadme(stage)

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
