#!/usr/bin/env python3
"""
Build a Windows distribution zip for DataDoctor.

Zip layout (launcher is the zip root):
  Data Doctor.exe          (from launcher/)
  updateBunker.cmd         (generated)
  README.txt               (generated each run)
  UPDATE.txt               (how to merge bunker.db)
  LICENSE
  DataDoctor.ico           (optional, next to launcher)
  python-3.13.x-amd64.exe  (if present under launcher/)
  Project Files/
    DataDoctor.pyw
    DataDoctor.ico
    requirements.txt
    core/                  (live bunker.db stays here for the user)
    ui/
    quickLook/
    oracle/                (optional Instant Client under oracle/client)
    scripts/updateBunker.py
    temp/bunker.db         (packaged dictionary for merge — do not overwrite live)
    .venv/                 ONLY if --include-venv (OFF by default)

IMPORTANT
---------
- .venv is NOT included by default. Shipping a whole venv made zips look like
  "just a Python environment" and ballooned size. Use --include-venv only when
  you intentionally want a portable env.
- launcher/ is copied SELECTIVELY (exe, ico, python installer). Nested
  launcher/Project Files and build junk (src, .pdb, .xml) are never the zip root.
- Stage is validated before zipping; missing DataDoctor.pyw / core / ui aborts.

Run from project root:
  python scripts/packageWindows.py
  python scripts/packageWindows.py --out dist/DataDoctor-Windows.zip
  python scripts/packageWindows.py --include-venv
  python scripts/packageWindows.py --keep-stage   # leave dist/winStage* for inspection
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


# Top-level names under launcher/ that must NEVER be copied wholesale into the zip
LAUNCHER_SKIP_DIRS = frozenset({
    'Project Files',   # rebuilt from project sources
    'src',             # VB project source, not runtime
    '__pycache__',
    '.git',
    '.venv',
    'venv',
    'build',
    'dist',
})

# File suffixes / names under launcher/ to skip (debug / designer junk)
LAUNCHER_SKIP_SUFFIXES = ('.pdb', '.xml', '.user', '.suo', '.cache')
LAUNCHER_SKIP_FILES = frozenset({
    'Data Doctor.xml',  # often next to .exe from VB builds
})


def projectRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def copyTree(src: Path, dst: Path, ignoreNames=None, ignoreSuffixes=None):
    """
    Copy a directory tree. Always skips __pycache__ / .pyc.
    ignoreNames: directory or file basenames to skip at any depth.
    """
    ignoreNames = set(ignoreNames or [])
    ignoreNames.update({'__pycache__', '.git', '.venv', 'venv'})
    ignoreSuffixes = tuple(ignoreSuffixes or ())
    if not src.exists():
        return 0
    fileCount = 0
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
            if ignoreSuffixes and fileName.endswith(ignoreSuffixes):
                continue
            shutil.copy2(rootPath / fileName, outDir / fileName)
            fileCount += 1
    return fileCount


def writeReadme(stage: Path, hasPythonInstaller: bool, installerName: str | None, hasVenv: bool):
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

    venvNote = ""
    if hasVenv:
        venvNote = """
- This package includes Project Files\\.venv (pre-bundled dependencies).
  The launcher will prefer that interpreter when present.
"""
    else:
        venvNote = """
- This package does NOT include a .venv. After unzip, install deps once:
      cd "Project Files"
      python -m pip install -r requirements.txt
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
4) Dependencies:{venvNote}
   Or always:
       python -m pip install -r "Project Files\\requirements.txt"

FOLDER LAYOUT
-------------
  Data Doctor.exe          ← launcher (zip root)
  updateBunker.cmd
  README.txt / UPDATE.txt
  Project Files\\
    DataDoctor.pyw         ← application entry
    core\\  ui\\  quickLook\\  oracle\\
    temp\\bunker.db         ← packaged dictionary for merge only
    requirements.txt

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


def writeUpdateBunkerCmd(stage: Path):
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


def copyLauncherArtifacts(launcher: Path, stage: Path) -> list[str]:
    """
    Selectively copy launcher runtime files to zip root.
    Does NOT copy launcher/Project Files (rebuilt later) or VB source.
    """
    copied = []
    if not launcher.is_dir():
        return copied

    for entry in sorted(launcher.iterdir()):
        name = entry.name
        if entry.is_dir():
            if name in LAUNCHER_SKIP_DIRS:
                print(f"  skip launcher dir: {name}/")
                continue
            # Unknown dir — only copy if it looks like a needed runtime folder
            print(f"  skip unknown launcher dir: {name}/")
            continue

        # Files
        if name in LAUNCHER_SKIP_FILES:
            print(f"  skip launcher file: {name}")
            continue
        if name.endswith(LAUNCHER_SKIP_SUFFIXES):
            # Keep Data Doctor.exe.config (needed by some .NET/VB hosts)
            if not (name.endswith('.exe.config') or name.endswith('.dll.config')):
                print(f"  skip launcher file: {name}")
                continue

        # Accept: .exe (launcher + python installer), .cmd, .ico, .config next to exe
        lower = name.lower()
        allowed = (
            lower.endswith('.exe')
            or lower.endswith('.cmd')
            or lower.endswith('.ico')
            or lower.endswith('.exe.config')
            or lower.endswith('.dll')
            or lower == 'readme.txt'
        )
        if not allowed:
            print(f"  skip launcher file: {name}")
            continue

        shutil.copy2(entry, stage / name)
        copied.append(name)
        print(f"  launcher → {name}")
    return copied


def summarizeStage(stage: Path, maxDepth: int = 2) -> str:
    """Human-readable top of the stage tree for the packager log."""
    lines = []
    stage = stage.resolve()
    for dirPath, dirNames, fileNames in os.walk(stage):
        rel = Path(dirPath).relative_to(stage)
        depth = 0 if str(rel) == '.' else len(rel.parts)
        if depth > maxDepth:
            dirNames.clear()
            continue
        indent = "  " * depth
        label = "." if str(rel) == '.' else rel.as_posix()
        lines.append(f"{indent}{label}/")
        # Sort for stable logs; hide huge venv internals at depth limit
        if 'venv' in str(rel).lower() and depth >= 1:
            lines.append(f"{indent}  … ({len(dirNames)} dirs, {len(fileNames)} files)")
            dirNames.clear()
            continue
        for f in sorted(fileNames)[:40]:
            lines.append(f"{indent}  {f}")
        if len(fileNames) > 40:
            lines.append(f"{indent}  … +{len(fileNames) - 40} more files")
    return "\n".join(lines)


def validateStage(stage: Path) -> list[str]:
    """Return list of hard errors if the stage is not a valid Windows package."""
    errors = []
    projectFiles = stage / "Project Files"
    if not projectFiles.is_dir():
        errors.append("Missing Project Files/")
        return errors

    required = [
        projectFiles / "DataDoctor.pyw",
        projectFiles / "core",
        projectFiles / "ui",
        projectFiles / "requirements.txt",
    ]
    for p in required:
        if not p.exists():
            errors.append(f"Missing required path: {p.relative_to(stage).as_posix()}")

    # Zip root must not BE a venv (common failure mode)
    venvMarkers = ("pyvenv.cfg", "Scripts", "Lib", "lib", "bin", "include")
    topNames = {p.name for p in stage.iterdir()}
    if "pyvenv.cfg" in topNames or (
        "Scripts" in topNames and "Lib" in topNames and "Project Files" not in topNames
    ):
        errors.append(
            "Stage root looks like a Python venv (pyvenv.cfg / Scripts+Lib). "
            "Refusing to zip — package layout is wrong."
        )

    # App code must not be empty shells
    corePy = list((projectFiles / "core").glob("*.py")) if (projectFiles / "core").is_dir() else []
    if (projectFiles / "core").is_dir() and not corePy:
        errors.append("Project Files/core/ has no .py modules")

    uiPy = list((projectFiles / "ui").glob("*.py")) if (projectFiles / "ui").is_dir() else []
    if (projectFiles / "ui").is_dir() and not uiPy:
        errors.append("Project Files/ui/ has no .py modules")

    return errors


def main():
    root = projectRoot()
    parser = argparse.ArgumentParser(
        description="Package DataDoctor for Windows (clean layout; venv opt-in)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output zip path (default: dist/DataDoctor-Windows-YYYYMMDD.zip)",
    )
    parser.add_argument(
        "--include-venv",
        dest="includeVenv",
        action="store_true",
        help="Copy project .venv into Project Files/.venv (OFF by default — large)",
    )
    parser.add_argument(
        "--skip-venv",
        dest="skipVenv",
        action="store_true",
        help=argparse.SUPPRESS,  # legacy alias; venv is already skipped by default
    )
    parser.add_argument(
        "--keep-stage",
        dest="keepStage",
        action="store_true",
        help="Do not delete dist/winStage* after zipping (for inspection)",
    )
    args = parser.parse_args()

    # Legacy flag: --skip-venv was the old default-on opt-out; now no-op
    if args.skipVenv and args.includeVenv:
        print("WARN: both --include-venv and --skip-venv; skipping venv", file=sys.stderr)
        args.includeVenv = False

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

    print(f"Project root: {root}")
    print(f"Stage:        {stage}")
    print(f"Output:       {outZip}")
    print()

    # 1) Selective launcher → zip root (NOT a full tree copy)
    print("=== Launcher artifacts (zip root) ===")
    launcherFiles = copyLauncherArtifacts(launcher, stage)
    if not any(n.lower().endswith('.exe') and 'python' not in n.lower() for n in launcherFiles):
        # Soft warning — maybe renamed
        if not any(n.lower().endswith('.exe') for n in launcherFiles):
            print("WARN: no .exe found under launcher/ for zip root", file=sys.stderr)

    # 2) LICENSE at zip root
    licenseSrc = root / "LICENSE"
    if licenseSrc.is_file():
        shutil.copy2(licenseSrc, stage / "LICENSE")
        print("  LICENSE")

    # 3) Project Files/ — always rebuilt from project sources (never from launcher/)
    print()
    print("=== Project Files/ (app) ===")
    projectFiles = stage / "Project Files"
    if projectFiles.exists():
        # Should not exist yet; wipe if a bad launcher copy left anything
        shutil.rmtree(projectFiles)
    projectFiles.mkdir(parents=True, exist_ok=True)

    for name in ("core", "ui", "quickLook", "oracle"):
        src = root / name
        if not src.exists():
            print(f"  WARN: missing source {name}/", file=sys.stderr)
            continue
        n = copyTree(
            src,
            projectFiles / name,
            ignoreNames={'.git', '__pycache__', 'client', '.venv', 'venv'},
        )
        print(f"  {name}/  ({n} files)")
        if name == "oracle":
            client = root / "oracle" / "client"
            if client.exists():
                nClient = copyTree(
                    client,
                    projectFiles / "oracle" / "client",
                    ignoreNames={'__pycache__', '.venv', 'venv'},
                )
                print(f"  oracle/client/  ({nClient} files)")

    # DataDoctor.py → DataDoctor.pyw
    pySrc = root / "DataDoctor.py"
    if pySrc.is_file():
        shutil.copy2(pySrc, projectFiles / "DataDoctor.pyw")
        print("  DataDoctor.pyw")
    else:
        print("ERROR: DataDoctor.py missing", file=sys.stderr)
        return 1

    # Windows taskbar/window icon next to .pyw
    icoSrc = root / "ui" / "icons" / "DataDoctor.ico"
    if icoSrc.is_file():
        shutil.copy2(icoSrc, projectFiles / "DataDoctor.ico")
        # Also at zip root if not already from launcher
        if not (stage / "DataDoctor.ico").is_file():
            shutil.copy2(icoSrc, stage / "DataDoctor.ico")
        print("  DataDoctor.ico")
    else:
        print("  WARN: ui/icons/DataDoctor.ico missing", file=sys.stderr)

    req = root / "requirements.txt"
    if req.is_file():
        shutil.copy2(req, projectFiles / "requirements.txt")
        print("  requirements.txt")
    else:
        print("  WARN: requirements.txt missing", file=sys.stderr)

    # scripts/updateBunker.py
    scriptsDir = projectFiles / "scripts"
    scriptsDir.mkdir(parents=True, exist_ok=True)
    updateBunkerSrc = None
    for candidate in (
        root / "launcher" / "Project Files" / "scripts" / "updateBunker.py",
        root / "scripts" / "updateBunker.py",
        root / "launcher" / "updateBunker.py",
    ):
        if candidate.is_file():
            updateBunkerSrc = candidate
            break
    if updateBunkerSrc is not None:
        shutil.copy2(updateBunkerSrc, scriptsDir / "updateBunker.py")
        print(f"  scripts/updateBunker.py  (from {updateBunkerSrc.relative_to(root)})")
    else:
        print("  WARN: updateBunker.py not found", file=sys.stderr)

    # Packaged bunker.db for merge
    bunkerSrc = root / "core" / "bunker.db"
    tempDir = projectFiles / "temp"
    if bunkerSrc.is_file():
        tempDir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bunkerSrc, tempDir / "bunker.db")
        print("  temp/bunker.db")
    else:
        print("  WARN: core/bunker.db missing — temp merge payload not packaged", file=sys.stderr)

    # updateBunker.cmd at zip root
    writeUpdateBunkerCmd(stage)
    print("  (zip root) updateBunker.cmd")

    # Optional .venv — OFF by default
    hasVenv = False
    venv = root / ".venv"
    if args.includeVenv and venv.is_dir():
        print()
        print("=== Including .venv (--include-venv) — this may take a while ===")
        nVenv = copyTree(
            venv,
            projectFiles / ".venv",
            ignoreNames={'__pycache__', '.git'},
        )
        hasVenv = True
        print(f"  Project Files/.venv/  ({nVenv} files)")
    elif args.includeVenv:
        print("WARN: --include-venv set but project .venv not found", file=sys.stderr)
    else:
        print()
        print("=== .venv skipped (default). Pass --include-venv to bundle it. ===")

    # README + UPDATE
    installerName = None
    hasInstaller = False
    for p in stage.glob("python-*.exe"):
        hasInstaller = True
        installerName = p.name
        break
    writeReadme(stage, hasInstaller, installerName, hasVenv)
    writeUpdateReadme(stage)

    # Validate before zip
    print()
    print("=== Stage tree (preview) ===")
    print(summarizeStage(stage, maxDepth=2))
    print()

    errors = validateStage(stage)
    if errors:
        print("ERROR: package validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        if not args.keepStage:
            print(f"Stage left at {stage} for inspection (validation failed).")
        return 1

    # Zip it
    if outZip.exists():
        outZip.unlink()
    print(f"Writing {outZip} ...")
    fileCount = 0
    with zipfile.ZipFile(outZip, "w", compression=zipfile.ZIP_DEFLATED) as zipFile:
        for dirPath, dirNames, fileNames in os.walk(stage):
            # Never walk into accidental nested venv at stage root
            dirNames[:] = [d for d in dirNames if d not in ('.git',)]
            for fileName in fileNames:
                full = Path(dirPath) / fileName
                arc = full.relative_to(stage).as_posix()
                zipFile.write(full, arcname=arc)
                fileCount += 1

    if not args.keepStage:
        shutil.rmtree(stage, ignore_errors=True)
    else:
        print(f"Stage kept: {stage}")

    sizeMb = outZip.stat().st_size / (1024 * 1024)
    print(f"Done: {outZip} ({sizeMb:.1f} MB, {fileCount} files)")
    print("Top-level zip entries should be: Data Doctor.exe, Project Files/, README.txt, …")
    print("NOT a bare Scripts/ Lib/ pyvenv.cfg tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
