#!/usr/bin/env python3
"""
Build a Windows distribution zip for DataDoctor.

Zip layout (launcher is the zip root):
  Data Doctor.exe          (from launcher/)
  applyUpdate.cmd          (full update: code + bunker merge + pip)
  README.txt               (generated each run)
  UPDATE.txt               (how to apply updates / merge dictionary)
  LICENSE
  python-3.13.x-amd64.exe  (if present under launcher/)
  Update/                  (drop DataDoctor-Python-*.zip here)
  Project Files/
    DataDoctor.pyw
    core/                  (live bunker.db stays here for the user)
    ui/
    quickLook/
    oracle/
    scripts/applyUpdate.py
    scripts/updateBunker.py  (called by applyUpdate; also usable alone)
    temp/bunker.db         (packaged dictionary for merge — do not overwrite live)
    .venv/                 (if present)

Note: root updateBunker.cmd is intentionally NOT packaged — applyUpdate.cmd
merges bunker.db. Dictionary-only merges use Project Files/scripts/updateBunker.py.

Run from project root:
  python scripts/packageWindows.py
  python scripts/packageWindows.py --out dist/DataDoctor-Windows.zip
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from oracleBundle import installOracleClient


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
3) Install Python 3.13 if needed (step 2). Enable "Add python.exe to PATH".
4) Run applyUpdate.cmd once. A Linux .venv cannot run on Windows, so this
   package does not ship one. applyUpdate.cmd:
     - Uses the DataDoctor-Python-*.zip already in Update\\
     - Creates Project Files\\.venv for Windows
     - pip installs requirements
     - Merges the data dictionary
5) Double-click "Data Doctor.exe" (VB launcher).
   Or: run Project Files\\DataDoctor.pyw with the venv Python.

UPDATING AN EXISTING INSTALL
----------------------------
See UPDATE.txt next to this file. Short version:
  - Prefer: drop a DataDoctor-Python-*.zip into Update\\ and run applyUpdate.cmd
    (refreshes code, merges dictionary, runs pip)
  - Do NOT overwrite your live Project Files\\core\\bunker.db with a zip's
    core copy if you have local dictionary edits
  - Dictionary-only merge (from a full package's temp bunker):
      python "Project Files\\scripts\\updateBunker.py"

AQUARIUS CERTIFICATES
---------------------
Project Files\\certs\\ is included (empty). Place aquarius.pem or a .cer/.crt
there. Updates do not replace this folder. .pfx is not supported.

SUPPORT NOTES
-------------
- Logs live under your user AppData config folder for Data Doctor.
- SQL / Oracle Instant Client may be under Project Files\\oracle\\ when packaged.
"""
    (stage / "README.txt").write_text(text.strip() + "\n", encoding="utf-8")


def writeUpdateReadme(stage: Path):
    text = """DataDoctor — updates

FULL APP UPDATE (recommended after first install)
------------------------------------------------
1) Close DataDoctor.
2) Download a DataDoctor-Python-*.zip (raw Python payload from packagePython.py).
3) Place the zip in this folder:
     Update\\
4) Double-click applyUpdate.cmd
   Or:
     applyUpdate.cmd
5) applyUpdate will:
     - Extract the zip
     - Refresh Project Files code (DataDoctor.pyw, ui/, core/* except live bunker)
     - Rename DataDoctor.py from the zip to DataDoctor.pyw (Windows launcher)
     - Merge data dictionary into Project Files\\core\\bunker.db
     - pip install -r requirements.txt into Project Files\\.venv
     - Delete the zip when finished
6) Restart DataDoctor.

DICTIONARY-ONLY MERGE (temp bunker from a full package)
------------------------------------------------------
When you install a new *full* package over an existing copy, your live data
dictionary is Project Files\\core\\bunker.db. The package also ships a fresh
dictionary at Project Files\\temp\\bunker.db (merge source).

Full updates already merge via applyUpdate.cmd. For dictionary-only:

1) Close DataDoctor.
2) From the install root:
     python "Project Files\\scripts\\updateBunker.py"
   Or with explicit paths:
     python "Project Files\\scripts\\updateBunker.py" --packaged "Project Files\\temp\\bunker.db" --user "Project Files\\core\\bunker.db"
     python "Project Files\\scripts\\updateBunker.py" --dry-run
3) The script backs up live bunker.db, merges rows, never deletes yours.
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
    #    Skip nested Project Files content we rebuild below (except we re-add scripts).
    #    updateBunker.cmd is NOT shipped — applyUpdate.cmd handles bunker merge.
    copyTree(
        launcher,
        stage,
        ignoreNames={'.git', 'src', '__pycache__', 'updateBunker.cmd'},
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
    installOracleClient(root, projectFiles / "oracle" / "client", "windows")

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

    # scripts under Project Files/scripts (not zip root)
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

    applyUpdateSrc = root / "scripts" / "applyUpdate.py"
    if applyUpdateSrc.is_file():
        shutil.copy2(applyUpdateSrc, scriptsDir / "applyUpdate.py")
    else:
        print("WARN: applyUpdate.py not found", file=sys.stderr)

    # Empty Update/ drop folder for DataDoctor-Python-*.zip (from packagePython.py)
    updateDrop = stage / "Update"
    updateDrop.mkdir(parents=True, exist_ok=True)
    (updateDrop / "README.txt").write_text(
        "Drop a DataDoctor-Python-*.zip here (from packagePython.py), then run applyUpdate.cmd from the install root.\n",
        encoding="utf-8",
    )

    # Empty certs/ so users have the right folder without creating it
    certsDir = projectFiles / "certs"
    certsDir.mkdir(parents=True, exist_ok=True)
    certsSrc = root / "certs"
    if certsSrc.is_dir():
        copyTree(certsSrc, certsDir, ignoreNames={".git", "__pycache__"})
    if not any(p.is_file() for p in certsDir.rglob("*")):
        (certsDir / "README.txt").write_text(
            "Optional Aquarius TLS certificates.\n"
            "Place aquarius.pem or a .cer/.crt here. .pfx is not supported.\n"
            "Updates never replace files in this folder.\n",
            encoding="utf-8",
        )
    print("Packaged Project Files/certs/")

    # Packaged bunker.db for merge → Project Files/temp/ (live user DB is core/)
    bunkerSrc = root / "core" / "bunker.db"
    tempDir = projectFiles / "temp"
    if bunkerSrc.is_file():
        tempDir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bunkerSrc, tempDir / "bunker.db")
        print(f"Packaged bunker.db → Project Files/temp/bunker.db")
    else:
        print("WARN: core/bunker.db missing — temp merge payload not packaged", file=sys.stderr)

    def writeRootCmd(name: str, scriptRel: str, banner: str):
        path = stage / name
        path.write_text(
            "\r\n".join([
                "@echo off",
                f"REM {banner}",
                "setlocal",
                'cd /d "%~dp0"',
                'set "PY="',
                'if exist "Project Files\\.venv\\Scripts\\python.exe" set "PY=Project Files\\.venv\\Scripts\\python.exe"',
                'if not defined PY if exist ".venv\\Scripts\\python.exe" set "PY=.venv\\Scripts\\python.exe"',
                'if not defined PY set "PY=python"',
                f'set "SCRIPT=%~dp0{scriptRel}"',
                'if not exist "%SCRIPT%" (',
                f"  echo ERROR: script not found at {scriptRel}",
                "  pause",
                "  exit /b 1",
                ")",
                '"%PY%" "%SCRIPT%" %*',
                "set ERR=%ERRORLEVEL%",
                "if %ERR% neq 0 (",
                "  echo.",
                "  echo Command failed with exit code %ERR%",
                "  pause",
                ")",
                "endlocal",
                "exit /b %ERR%",
                "",
            ]),
            encoding="utf-8",
            newline="\r\n",
        )

    writeRootCmd(
        "applyUpdate.cmd",
        "Project Files\\scripts\\applyUpdate.py",
        "Apply newest zip in Update\\ (code refresh + bunker merge + pip)",
    )
    # Ensure no leftover root updateBunker.cmd (legacy launcher copy / old stages)
    legacyBunkerCmd = stage / "updateBunker.cmd"
    if legacyBunkerCmd.is_file():
        legacyBunkerCmd.unlink()

    # README + UPDATE (generated every run so installer version notes stay current)
    installerName = None
    hasInstaller = False
    for p in stage.glob("python-*.exe"):
        hasInstaller = True
        installerName = p.name
        break
    writeReadme(stage, hasInstaller, installerName)
    writeUpdateReadme(stage)

    # .venv is OS-specific (Linux bin/ + .so vs Windows Scripts/ + .pyd).
    # Never copy a non-Windows venv into a Windows zip.
    venv = root / ".venv"
    hostIsWindows = platform.system() == "Windows"
    if not hostIsWindows:
        print(
            "Skipping .venv (this host is not Windows; "
            "a Linux/mac venv cannot run on Windows). First-run applyUpdate.cmd "
            "creates Project Files\\.venv from the Python zip in Update\\."
        )
    elif not args.skipVenv and venv.is_dir():
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

    # First-install payload: same layout as packagePython.py so applyUpdate.cmd
    # can create the Windows venv and pip-install without a second download.
    pyZip = updateDrop / "DataDoctor-Python.zip"
    print(f"Writing first-install payload {pyZip.name} ...")
    with zipfile.ZipFile(pyZip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        pyw = projectFiles / "DataDoctor.pyw"
        if pyw.is_file():
            zf.write(pyw, "DataDoctor.py")
        reqPf = projectFiles / "requirements.txt"
        if reqPf.is_file():
            zf.write(reqPf, "requirements.txt")
        licensePf = stage / "LICENSE"
        if licensePf.is_file():
            zf.write(licensePf, "LICENSE")
        for tree in ("core", "ui", "quickLook", "oracle", "certs"):
            srcTree = projectFiles / tree
            if not srcTree.exists():
                continue
            for dirPath, dirNames, fileNames in os.walk(srcTree):
                # Instant Client stays in Project Files/oracle/client only —
                # do not also stuff it into the Update python zip.
                dirNames[:] = [
                    d for d in dirNames
                    if d != "__pycache__" and not (tree == "oracle" and d == "client")
                ]
                for fileName in fileNames:
                    if fileName.endswith((".pyc", ".pyo")):
                        continue
                    full = Path(dirPath) / fileName
                    rel = full.relative_to(projectFiles).as_posix()
                    zf.write(full, rel)

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
