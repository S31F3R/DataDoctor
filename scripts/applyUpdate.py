#!/usr/bin/env python3
"""
Apply a DataDoctor Python zip from the install's Update/ folder.

Expected install layout (launcher package):
  <install root>/
    Data Doctor.exe | Data Doctor.command | …
    applyUpdate.cmd | applyUpdate.sh | this script (or under Project Files/scripts/)
    Update/                 ← drop DataDoctor-Python-*.zip here (from packagePython.py)
    Project Files/
      DataDoctor.py[w]
      core/                 ← live bunker.db stays here
      ui/
      .venv/
      …

What this does:
  1) Pick the newest *.zip in Update/ (or --zip path)
  2) Extract to a temp dir under Update/
  3) Copy DataDoctor.py/.pyw, ui/, core/* (except bunker.db), quickLook/, requirements
  4) If temp/bunker.db present → merge into live core/bunker.db via updateBunker.py
  5) pip install -r requirements.txt into Project Files/.venv (if present)
  6) Remove the zip and extract tree

Does NOT:
  - Touch user config / keyring / AppData
  - Delete user-added quickLook files (only overwrites same names)
  - Overwrite live core/bunker.db wholesale (merge only)

Run from install root:
  python applyUpdate.py
  python applyUpdate.py --zip Update/DataDoctor-Python-20260808.zip
  python "Project Files/scripts/applyUpdate.py"
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def findInstallRoot(start: Path) -> Path:
    """
    Walk up from start to find Project Files/ (install root is its parent).
    Also accept start itself if it contains Project Files/.
    """
    cur = start.resolve()
    for _ in range(6):
        if (cur / "Project Files").is_dir():
            return cur
        if cur.name == "Project Files" and cur.parent.is_dir():
            return cur.parent
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def pickNewestZip(updateDir: Path) -> Path | None:
    if not updateDir.is_dir():
        return None
    zips = sorted(
        updateDir.glob("*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return zips[0] if zips else None


def copyTreeMerge(src: Path, dst: Path, skipNames=None):
    """Copy files from src into dst; never deletes dest-only files."""
    skipNames = set(skipNames or [])
    if not src.is_dir():
        return
    for root, dirs, files in os.walk(src):
        rootPath = Path(root)
        rel = rootPath.relative_to(src)
        dirs[:] = [d for d in dirs if d not in skipNames and not d.startswith('__pycache__')]
        outDir = dst / rel
        outDir.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name in skipNames or name.endswith(('.pyc', '.pyo')):
                continue
            shutil.copy2(rootPath / name, outDir / name)


def resolvePython(projectFiles: Path) -> str:
    candidates = [
        projectFiles / ".venv" / "Scripts" / "python.exe",  # Windows
        projectFiles / ".venv" / "bin" / "python",
        projectFiles / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return sys.executable


def runPipInstall(py: str, requirements: Path) -> int:
    if not requirements.is_file():
        print("No requirements.txt in update — skipping pip install")
        return 0
    cmd = [py, "-m", "pip", "install", "--upgrade", "-r", str(requirements)]
    print("+", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except Exception as e:
        print(f"ERROR: pip install failed: {e}", file=sys.stderr)
        return 1


def runBunkerMerge(py: str, projectFiles: Path, packagedBunker: Path) -> int:
    live = projectFiles / "core" / "bunker.db"
    script = projectFiles / "scripts" / "updateBunker.py"
    if not script.is_file():
        # Try install-root scripts
        alt = projectFiles.parent / "scripts" / "updateBunker.py"
        if alt.is_file():
            script = alt
    if not script.is_file():
        print("WARN: updateBunker.py not found — copying packaged bunker only if live missing")
        if not live.is_file():
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(packagedBunker, live)
            print(f"Installed new bunker.db → {live}")
        return 0

    cmd = [
        py, str(script),
        "--packaged", str(packagedBunker),
        "--user", str(live),
    ]
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def apply(zipPath: Path, installRoot: Path, keepExtract: bool = False) -> int:
    projectFiles = installRoot / "Project Files"
    if not projectFiles.is_dir():
        print(f"ERROR: Project Files/ not found under {installRoot}", file=sys.stderr)
        return 1
    if not zipPath.is_file():
        print(f"ERROR: zip not found: {zipPath}", file=sys.stderr)
        return 1

    updateDir = installRoot / "Update"
    updateDir.mkdir(parents=True, exist_ok=True)
    extractDir = Path(tempfile.mkdtemp(prefix="dd-update-", dir=str(updateDir)))
    print(f"Extracting {zipPath.name} → {extractDir}")

    try:
        with zipfile.ZipFile(zipPath, "r") as zf:
            zf.extractall(extractDir)

        # Payload may be at extract root or nested one level
        payload = extractDir
        if not (payload / "DataDoctor.py").is_file() and not (payload / "core").is_dir():
            kids = [p for p in extractDir.iterdir() if p.is_dir()]
            if len(kids) == 1:
                payload = kids[0]

        # App entry + docs (no .pyw — that is Windows package only)
        for name in ("DataDoctor.py", "requirements.txt", "README.txt", "LICENSE"):
            src = payload / name
            if src.is_file():
                shutil.copy2(src, projectFiles / name)
                print(f"Updated {name}")

        # Trees (do not overwrite live bunker.db here)
        treeNames = (
            "ui",
            "core",
            "quickLook",
            "certs",
            "oracle",
            "scripts",
        )
        for tree in treeNames:
            src = payload / tree
            if not src.is_dir():
                continue
            if tree == "core":
                copyTreeMerge(src, projectFiles / tree, skipNames={"bunker.db"})
                print("Updated core/ (bunker.db skipped — merge path)")
            else:
                copyTreeMerge(src, projectFiles / tree)
                print(f"Updated {tree}/")

        py = resolvePython(projectFiles)
        print(f"Using Python: {py}")

        # Bunker merge
        packagedBunker = payload / "temp" / "bunker.db"
        if not packagedBunker.is_file():
            packagedBunker = payload / "core" / "bunker.db"
        if packagedBunker.is_file():
            rc = runBunkerMerge(py, projectFiles, packagedBunker)
            if rc != 0:
                print(f"WARN: bunker merge exited {rc}", file=sys.stderr)
        else:
            print("No packaged bunker.db in update — skipped dictionary merge")

        # Dependencies
        req = projectFiles / "requirements.txt"
        rc = runPipInstall(py, req)
        if rc != 0:
            print(f"WARN: pip install exited {rc}", file=sys.stderr)

        # Cleanup zip after successful extract/copy
        try:
            zipPath.unlink()
            print(f"Removed {zipPath.name}")
        except Exception as e:
            print(f"WARN: could not remove zip: {e}", file=sys.stderr)

        print("Update complete. Restart Data Doctor.")
        return 0
    finally:
        if not keepExtract and extractDir.exists():
            shutil.rmtree(extractDir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply DataDoctor Python zip from Update/")
    parser.add_argument(
        "--zip",
        default=None,
        help="Path to Python zip (default: newest *.zip in Update/)",
    )
    parser.add_argument(
        "--install-root",
        dest="installRoot",
        default=None,
        help="Install root (folder that contains Project Files/). Default: auto-detect",
    )
    parser.add_argument(
        "--keep-extract",
        dest="keepExtract",
        action="store_true",
        help="Keep extracted files under Update/ for debugging",
    )
    args = parser.parse_args()

    if args.installRoot:
        installRoot = Path(args.installRoot).expanduser().resolve()
    else:
        # Script may live at install root or Project Files/scripts/
        installRoot = findInstallRoot(Path(__file__).resolve().parent)

    print(f"Install root: {installRoot}")
    updateDir = installRoot / "Update"
    updateDir.mkdir(parents=True, exist_ok=True)

    if args.zip:
        zipPath = Path(args.zip).expanduser().resolve()
    else:
        zipPath = pickNewestZip(updateDir)
        if zipPath is None:
            print(
                f"ERROR: No *.zip found in {updateDir}\n"
                "  Place a DataDoctor-Python-*.zip there (scripts/packagePython.py), or pass --zip path",
                file=sys.stderr,
            )
            return 1

    print(f"Python zip: {zipPath}")
    return apply(zipPath, installRoot, keepExtract=args.keepExtract)


if __name__ == "__main__":
    sys.exit(main())
