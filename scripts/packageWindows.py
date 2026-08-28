#!/usr/bin/env python3
"""
Build a Windows distribution zip for DataDoctor.

Zip layout (launcher is the zip root):
  Data Doctor.exe          (from launcher/)
  applyUpdate.cmd          (full update: code + bunker merge + pip)
  README.txt               (generated each run)
  UPDATE.txt               (how to apply updates / merge dictionary)
  LICENSE
  Update/                  (drop DataDoctor-Python-*.zip here)
  Project Files/
    DataDoctor.pyw
    python-embed/          (official Windows embeddable Python 3.14 — no system Python)
    core/                  (live bunker.db stays here for the user)
    ui/
    quickLook/
    oracle/
    scripts/applyUpdate.py
    scripts/updateBunker.py  (called by applyUpdate; also usable alone)
    temp/bunker.db         (packaged dictionary for merge — do not overwrite live)

The embed zip lives at launcher/python-*-embed-amd64.zip and is extracted at
package time. Pip/site-packages are installed on the user's PC (first
applyUpdate.cmd), not stored in git.

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


def findEmbedZip(root: Path) -> Path | None:
    hits = sorted(root.glob("launcher/python-*-embed-amd64.zip"))
    return hits[-1] if hits else None


def enableEmbedSite(embedDir: Path) -> None:
    """Uncomment `import site` and add Lib\\site-packages so pip packages work."""
    pthFiles = list(embedDir.glob("python*._pth"))
    if not pthFiles:
        print("WARN: no python*._pth in embed dir", file=sys.stderr)
        return
    pth = pthFiles[0]
    lines = pth.read_text(encoding="utf-8").splitlines()
    out = []
    sawSite = False
    sawLib = False
    for line in lines:
        stripped = line.strip()
        if stripped.lstrip("#").strip() == "import site":
            out.append("import site")
            sawSite = True
            continue
        if stripped.replace("\\", "/") == "Lib/site-packages":
            out.append("Lib\\site-packages")
            sawLib = True
            continue
        out.append(line)
    if not sawLib:
        # After the `.` search-path line if present
        inserted = False
        new = []
        for line in out:
            new.append(line)
            if line.strip() == "." and not inserted:
                new.append("Lib\\site-packages")
                inserted = True
        out = new if inserted else out + ["Lib\\site-packages"]
    if not sawSite:
        out.append("import site")
    pth.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Enabled import site in {pth.name}")


def installPythonEmbed(root: Path, dest: Path) -> bool:
    """Extract launcher/python-*-embed-amd64.zip into dest (python-embed/)."""
    zpath = findEmbedZip(root)
    if zpath is None:
        print(
            "ERROR: launcher/python-*-embed-amd64.zip not found — "
            "Windows zip will not be portable",
            file=sys.stderr,
        )
        return False
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    print(f"Extracting {zpath.name} → Project Files/python-embed/")
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(dest)
    enableEmbedSite(dest)
    # get-pip.py so first-run applyUpdate can bootstrap pip without a system Python
    getPip = dest / "get-pip.py"
    if not getPip.is_file():
        url = "https://bootstrap.pypa.io/get-pip.py"
        try:
            import urllib.request
            print(f"Downloading {url}")
            urllib.request.urlretrieve(url, getPip)
        except Exception as e:
            print(f"WARN: could not download get-pip.py ({e}); applyUpdate will try at runtime", file=sys.stderr)
    return (dest / "pythonw.exe").is_file()


def writeReadme(stage: Path, embedOk: bool):
    """Generate README.txt at zip root (rebuilt every package run)."""
    text = f"""DataDoctor — Windows package
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

REQUIREMENTS
------------
- Windows 10/11 (64-bit)
- No system Python install is required. This zip ships Python 3.14
  (Project Files\\python-embed\\).

FIRST RUN
---------
1) Unzip this package to a folder you can write to (e.g. Documents\\DataDoctor).
2) Double-click "Data Doctor.exe".
   If Update\\ contains a DataDoctor-Python-*.zip, the launcher runs
   applyUpdate.cmd first (pip-installs requirements into python-embed,
   merges the data dictionary), then starts the app.
3) Or run applyUpdate.cmd yourself, then Data Doctor.exe.

UPDATING AN EXISTING INSTALL
----------------------------
See UPDATE.txt next to this file.

  Code-only (already on bundled Python 3.14):
    Drop DataDoctor-Python-*.zip into Update\\ and run applyUpdate.cmd
    (or just restart Data Doctor.exe — it applies zips in Update\\).

  Launcher + bundled Python (first 3.1 / coming from a 3.0.x .venv install):
    Drop DataDoctor-Windows-*.zip into Update\\ and run applyUpdate.cmd.
    That replaces Data Doctor.exe and installs python-embed. Your
    Project Files\\core\\bunker.db is merged, not overwritten.

  Do NOT copy a zip's core\\bunker.db over your live dictionary.

AQUARIUS CERTIFICATES
---------------------
Project Files\\certs\\ is included (empty). Place aquarius.pem or a .cer/.crt
there. Updates do not replace this folder. .pfx is not supported.

SUPPORT NOTES
-------------
- Logs live under your user AppData config folder for Data Doctor.
- SQL / Oracle Instant Client may be under Project Files\\oracle\\ when packaged.
- python-embed already includes vcruntime140.dll (numpy / PyQt).
"""
    if not embedOk:
        text += (
            "\nWARNING: This build was packaged without python-embed. "
            "The launcher will not start until python-embed\\pythonw.exe is present.\n"
        )
    (stage / "README.txt").write_text(text.strip() + "\n", encoding="utf-8")


def writeUpdateReadme(stage: Path):
    text = """DataDoctor — updates

CODE UPDATE (already on bundled python-embed)
--------------------------------------------
1) Close Data Doctor.
2) Drop DataDoctor-Python-*.zip into Update\\
3) Double-click applyUpdate.cmd  (or restart Data Doctor.exe — it applies
   zips in Update\\ first).
4) applyUpdate refreshes Project Files code (DataDoctor.pyw, ui/, core/*
   except live bunker.db), merges the dictionary, pip-installs into
   python-embed, and deletes the zip.

LAUNCHER + BUNDLED PYTHON (3.0.x .venv installs → 3.1+)
------------------------------------------------------
The old zip needed a system Python + Project Files\\.venv. This one ships
Python 3.14 under Project Files\\python-embed\\ and a launcher that starts
pythonw.exe there.

1) Close Data Doctor.
2) Drop DataDoctor-Windows-*.zip (the full Windows package) into Update\\
3) Double-click applyUpdate.cmd
4) That replaces Data Doctor.exe / applyUpdate.cmd and installs python-embed.
   bunker.db is merged, not overwritten. certs\\ is left alone.

DICTIONARY-ONLY MERGE
--------------------
1) Close Data Doctor.
2) From the install root:
     "Project Files\\python-embed\\python.exe" "Project Files\\scripts\\updateBunker.py"
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
        help="Ignored: Windows zip ships python-embed, never .venv",
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
        ignoreNames={
            '.git', 'src', '__pycache__', 'updateBunker.cmd',
            # Full CPython installer — replaced by python-embed
            'python-3.13.14-amd64.exe',
        },
    )
    # Never ship the embed *zip* at zip root; it is extracted into Project Files.
    for leftover in stage.glob("python-*-embed-amd64.zip"):
        leftover.unlink()
    for leftover in stage.glob("python-*.exe"):
        leftover.unlink()
        print(f"Omitted system Python installer {leftover.name} (using python-embed)")

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
        "Code update (already on python-embed): drop DataDoctor-Python-*.zip here, "
        "then run applyUpdate.cmd (or restart Data Doctor.exe).\n"
        "Launcher + Python 3.14 (coming from 3.0.x): drop DataDoctor-Windows-*.zip "
        "here, close Data Doctor, then run applyUpdate.cmd.\n",
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
                'if exist "Project Files\\python-embed\\python.exe" set "PY=Project Files\\python-embed\\python.exe"',
                'if not defined PY if exist "Project Files\\.venv\\Scripts\\python.exe" set "PY=Project Files\\.venv\\Scripts\\python.exe"',
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
        "Apply newest zip in Update\\ (code refresh + bunker merge + pip into python-embed)",
    )

    embedOk = installPythonEmbed(root, projectFiles / "python-embed")
    if not embedOk:
        print("WARN: python-embed missing — launcher will not start", file=sys.stderr)
    # Ensure no leftover root updateBunker.cmd (legacy launcher copy / old stages)
    legacyBunkerCmd = stage / "updateBunker.cmd"
    if legacyBunkerCmd.is_file():
        legacyBunkerCmd.unlink()

    writeReadme(stage, embedOk)
    writeUpdateReadme(stage)
    print("Skipping .venv (replaced by Project Files\\python-embed)")

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
