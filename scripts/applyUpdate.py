#!/usr/bin/env python3
"""
Apply a DataDoctor zip from the install's Update/ folder.

Expected install layout (Windows launcher package):
  <install root>/
    Data Doctor.exe | Data Doctor.command | …
    applyUpdate.cmd | applyUpdate.sh | this script (or under Project Files/scripts/)
    Update/                 ← DataDoctor-Python-*.zip (code) or
                              DataDoctor-Windows-*.zip (launcher + python-embed)
    Project Files/
      DataDoctor.py[w]
      python-embed/         ← bundled CPython 3.14 (Windows); no system Python
      core/                 ← live bunker.db stays here
      ui/
      …

What this does:
  1) Pick a zip in Update/ (Windows zip if python-embed is missing, else Python zip)
  2) Extract to a temp dir under Update/
  3) Copy DataDoctor.py as DataDoctor.pyw on Windows (or when .pyw already exists),
     plus ui/, core/* (except bunker.db), quickLook/, requirements
  4) Windows zip also replaces Data Doctor.exe and installs python-embed
  5) If temp/bunker.db or core/bunker.db present → merge via updateBunker.py
  6) pip install -r requirements.txt into python-embed (Windows) or .venv
  7) Remove the zip and extract tree

Does NOT:
  - Touch user config / keyring / AppData
  - Delete user-added quickLook files (only overwrites same names)
  - Overwrite live core/bunker.db wholesale (merge only)
  - Copy or replace Project Files/certs (user Aquarius certs stay)

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


def pickUpdateZip(updateDir: Path, projectFiles: Path) -> Path | None:
    """
    Prefer DataDoctor-Windows-*.zip when python-embed is missing (3.0.x hop).
    Otherwise prefer DataDoctor-Python-*.zip so a leftover Windows zip is not
    re-applied on every code update.
    """
    if not updateDir.is_dir():
        return None
    zips = [p for p in updateDir.glob("*.zip") if p.is_file()]
    if not zips:
        return None
    newest = lambda xs: max(xs, key=lambda p: p.stat().st_mtime)
    embedOk = (projectFiles / "python-embed" / "pythonw.exe").is_file()
    windowsZips = [p for p in zips if "windows" in p.name.lower()]
    pythonZips = [p for p in zips if "python" in p.name.lower()]
    if not embedOk and windowsZips:
        return newest(windowsZips)
    if pythonZips:
        return newest(pythonZips)
    return newest(zips)


def pathIsInside(dest: Path, target: Path) -> bool:
    destReal = os.path.normcase(str(dest.resolve())) + os.sep
    t = os.path.normcase(str(target.resolve()))
    return t == destReal[:-1] or t.startswith(destReal)


def zipMemberUnsafe(name: str) -> bool:
    raw = (name or "").replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("\\"):
        return True
    if len(raw) > 1 and raw[1] == ":":
        return True
    parts = [p for p in raw.split("/") if p and p != "."]
    return any(p == ".." for p in parts)


def safeExtractZip(zf: zipfile.ZipFile, dest: Path, maxUncompressed: int = 2 * 1024 ** 3) -> None:
    """Extract a zip, rejecting .. / absolute paths and oversized payloads."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for info in zf.infolist():
        if zipMemberUnsafe(info.filename):
            raise ValueError(f"unsafe zip path: {info.filename}")
        total += max(int(getattr(info, "file_size", 0) or 0), 0)
        if total > maxUncompressed:
            raise ValueError("zip uncompressed size exceeds limit")
        target = (dest / info.filename.replace("\\", "/")).resolve()
        if not pathIsInside(dest, target):
            raise ValueError(f"unsafe zip path: {info.filename}")
        if info.is_dir() or info.filename.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def writeFilteredRequirements(src: Path, dest: Path) -> bool:
    """
    Copy requirement lines that are package pins only.
    Drops pip CLI flags (-r, --index-url, --trusted-host) and direct URLs.
    """
    if not src.is_file():
        return False
    keep = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") or "://" in line:
            print(f"WARN: ignoring requirements line: {line}", file=sys.stderr)
            continue
        keep.append(raw.rstrip())
    if not keep:
        return False
    dest.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return True


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
        projectFiles / "python-embed" / "python.exe",  # Windows bundled 3.14
        projectFiles / ".venv" / "Scripts" / "python.exe",
        projectFiles / ".venv" / "bin" / "python",
        projectFiles / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return sys.executable


def enableEmbedSite(embedDir: Path) -> None:
    pthFiles = list(embedDir.glob("python*._pth"))
    if not pthFiles:
        return
    pth = pthFiles[0]
    text = pth.read_text(encoding="utf-8")
    lines = []
    sawSite = False
    sawLib = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lstrip("#").strip() == "import site":
            lines.append("import site")
            sawSite = True
            continue
        if stripped.replace("\\", "/") == "Lib/site-packages":
            lines.append("Lib\\site-packages")
            sawLib = True
            continue
        lines.append(line)
    if not sawLib:
        inserted = False
        new = []
        for line in lines:
            new.append(line)
            if line.strip() == "." and not inserted:
                new.append("Lib\\site-packages")
                inserted = True
        lines = new if inserted else lines + ["Lib\\site-packages"]
    if not sawSite:
        lines.append("import site")
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensurePip(py: str, projectFiles: Path) -> None:
    """Bootstrap pip into python-embed if `python -m pip` is missing."""
    probe = subprocess.call(
        [py, "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe == 0:
        return
    getPip = projectFiles / "python-embed" / "get-pip.py"
    if not getPip.is_file():
        url = "https://bootstrap.pypa.io/get-pip.py"
        print(f"Downloading {url}")
        try:
            import urllib.request
            getPip.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                final = resp.geturl()
                if not str(final).lower().startswith("https://bootstrap.pypa.io/"):
                    print(f"WARN: refusing get-pip redirect to {final}", file=sys.stderr)
                    return
                data = resp.read()
            if len(data) < 1000 or len(data) > 3 * 1024 * 1024:
                print("WARN: get-pip.py size looks wrong; not running it", file=sys.stderr)
                return
            getPip.write_bytes(data)
        except Exception as e:
            print(f"WARN: get-pip.py download failed: {e}", file=sys.stderr)
            return
    print("+", py, str(getPip))
    subprocess.call([py, str(getPip), "--no-warn-script-location"])
    enableEmbedSite(projectFiles / "python-embed")


def ensurePython(projectFiles: Path) -> str:
    """Prefer bundled python-embed; fall back to .venv / this interpreter."""
    embedDir = projectFiles / "python-embed"
    embedPy = embedDir / "python.exe"
    if embedPy.is_file():
        enableEmbedSite(embedDir)
        py = str(embedPy)
        ensurePip(py, projectFiles)
        return py

    existing = resolvePython(projectFiles)
    venvDir = projectFiles / ".venv"
    winPy = venvDir / "Scripts" / "python.exe"
    nixPy = venvDir / "bin" / "python"
    nixPy3 = venvDir / "bin" / "python3"
    if existing != sys.executable and Path(existing) in (winPy, nixPy, nixPy3):
        return existing

    print(f"Creating virtualenv at {venvDir} (no python-embed on this install)")
    rc = subprocess.call([sys.executable, "-m", "venv", str(venvDir)])
    if rc != 0:
        print(f"WARN: python -m venv failed with {rc}; using {sys.executable}", file=sys.stderr)
        return sys.executable
    for c in (winPy, nixPy, nixPy3):
        if c.is_file():
            print(f"Created {c}")
            return str(c)
    return sys.executable


def isWindowsFullPayload(payload: Path) -> bool:
    """True if this zip is a DataDoctor-Windows package, not a Python-only payload."""
    if (payload / "Data Doctor.exe").is_file():
        return True
    pf = payload / "Project Files"
    if (pf / "python-embed" / "pythonw.exe").is_file():
        return True
    if (pf / "DataDoctor.pyw").is_file() and (payload / "applyUpdate.cmd").is_file():
        return True
    return False


def copyFileIfPresent(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dest)
        print(f"Updated {dest.name}")
        return True
    except OSError as e:
        # Data Doctor.exe cannot overwrite itself while the launcher is waiting
        # on applyUpdate.cmd. Rename the locked file, then copy the new one.
        if dest.is_file():
            old = dest.with_name(dest.name + ".old")
            try:
                if old.is_file():
                    old.unlink()
                dest.rename(old)
                shutil.copy2(src, dest)
                print(f"Updated {dest.name} (replaced locked file via rename)")
                return True
            except Exception as e2:
                print(
                    f"WARN: could not replace {dest.name}: {e}; retry={e2}",
                    file=sys.stderr,
                )
                return False
        print(f"WARN: could not copy {dest.name}: {e}", file=sys.stderr)
        return False


def copyApplyScripts(codeRoot: Path, projectFiles: Path) -> None:
    """Copy applyUpdate.py / updateBunker.py when the zip includes them."""
    destDir = projectFiles / "scripts"
    destDir.mkdir(parents=True, exist_ok=True)
    applySrc = codeRoot / "scripts" / "applyUpdate.py"
    if not applySrc.is_file():
        # 3.0.x applyUpdate copies core/* but not scripts/; python zip ships
        # a copy at core/applyUpdate.py so this hop still gets the new updater.
        applySrc = codeRoot / "core" / "applyUpdate.py"
    if applySrc.is_file():
        shutil.copy2(applySrc, destDir / "applyUpdate.py")
        print("Updated scripts/applyUpdate.py")
    bunkerSrc = codeRoot / "scripts" / "updateBunker.py"
    if bunkerSrc.is_file():
        shutil.copy2(bunkerSrc, destDir / "updateBunker.py")
        print("Updated scripts/updateBunker.py")


def applyWindowsLauncherBits(payload: Path, installRoot: Path) -> None:
    """Replace Data Doctor.exe, applyUpdate.cmd, and python-embed from a Windows zip."""
    copyFileIfPresent(payload / "Data Doctor.exe", installRoot / "Data Doctor.exe")
    copyFileIfPresent(payload / "applyUpdate.cmd", installRoot / "applyUpdate.cmd")
    copyFileIfPresent(payload / "README.txt", installRoot / "README.txt")
    copyFileIfPresent(payload / "UPDATE.txt", installRoot / "UPDATE.txt")
    srcEmbed = payload / "Project Files" / "python-embed"
    destEmbed = installRoot / "Project Files" / "python-embed"
    if srcEmbed.is_dir() and (srcEmbed / "pythonw.exe").is_file():
        if destEmbed.exists():
            shutil.rmtree(destEmbed)
        shutil.copytree(srcEmbed, destEmbed)
        enableEmbedSite(destEmbed)
        print("Installed Project Files/python-embed/")


def writeApplyUpdateCmd(installRoot: Path) -> None:
    """Keep applyUpdate.cmd pointing at python-embed when present."""
    cmd = installRoot / "applyUpdate.cmd"
    body = "\r\n".join([
        "@echo off",
        "REM Apply newest zip in Update\\ (code + bunker merge + pip into python-embed)",
        "setlocal",
        'cd /d "%~dp0"',
        'set "PY="',
        'if exist "Project Files\\python-embed\\python.exe" set "PY=Project Files\\python-embed\\python.exe"',
        'if not defined PY if exist "Project Files\\.venv\\Scripts\\python.exe" set "PY=Project Files\\.venv\\Scripts\\python.exe"',
        'if not defined PY set "PY=python"',
        'set "SCRIPT=%~dp0Project Files\\scripts\\applyUpdate.py"',
        'if not exist "%SCRIPT%" (',
        "  echo ERROR: applyUpdate.py not found",
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
    ])
    cmd.write_text(body, encoding="utf-8", newline="\r\n")


def runPipInstall(py: str, requirements: Path) -> int:
    if not requirements.is_file():
        print("No requirements.txt in update — skipping pip install")
        return 0
    # pygame 2.6.1 has no Python 3.14 wheel. pygame-ce provides `import pygame`.
    subprocess.call(
        [py, "-m", "pip", "uninstall", "-y", "pygame"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    filtered = requirements.with_name(requirements.name + ".safe")
    try:
        if not writeFilteredRequirements(requirements, filtered):
            print("No usable package pins in requirements.txt — skipping pip install")
            return 0
        cmd = [
            py, "-m", "pip", "install", "--upgrade",
            "--disable-pip-version-check",
            "-r", str(filtered),
        ]
        print("+", " ".join(cmd))
        try:
            return subprocess.call(cmd)
        except Exception as e:
            print(f"ERROR: pip install failed: {e}", file=sys.stderr)
            return 1
    finally:
        try:
            if filtered.is_file():
                filtered.unlink()
        except Exception:
            pass


def installAppEntry(payload: Path, projectFiles: Path) -> str | None:
    """
    Copy DataDoctor.py[.pyw] from the zip payload into Project Files/.

    Windows launcher packages ship DataDoctor.pyw and the VB launcher starts
    that file. Update zips from packagePython.py only contain DataDoctor.py.
    If the live install already has DataDoctor.pyw, or the host is Windows,
    write DataDoctor.pyw and delete any leftover DataDoctor.py.
    """
    src = payload / "DataDoctor.py"
    if not src.is_file():
        src = payload / "DataDoctor.pyw"
    if not src.is_file():
        return None

    wantPyw = (projectFiles / "DataDoctor.pyw").is_file() or sys.platform.startswith("win")
    destName = "DataDoctor.pyw" if wantPyw else "DataDoctor.py"
    shutil.copy2(src, projectFiles / destName)
    if wantPyw:
        leftover = projectFiles / "DataDoctor.py"
        if leftover.is_file():
            leftover.unlink()
    return destName


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
            safeExtractZip(zf, extractDir)

        # Payload may be at extract root or nested one level
        payload = extractDir
        if not (payload / "DataDoctor.py").is_file() and not (payload / "core").is_dir():
            if not isWindowsFullPayload(payload):
                kids = [p for p in extractDir.iterdir() if p.is_dir()]
                if len(kids) == 1:
                    payload = kids[0]

        windowsFull = isWindowsFullPayload(payload)
        codeRoot = payload
        if windowsFull:
            print("Windows full package: replacing launcher + python-embed")
            applyWindowsLauncherBits(payload, installRoot)
            pf = payload / "Project Files"
            if pf.is_dir():
                codeRoot = pf

        # App entry: raw Python zip ships DataDoctor.py. Windows launcher
        # installs run DataDoctor.pyw (no console). If .pyw is already live
        # or we are on Windows, write .pyw and drop leftover .py so an old
        # .pyw is not left sitting next to a new .py.
        destName = installAppEntry(codeRoot, projectFiles)
        if destName:
            print(f"Updated {destName}")

        for name in ("requirements.txt", "README.txt", "LICENSE"):
            src = codeRoot / name
            if src.is_file():
                shutil.copy2(src, projectFiles / name)
                print(f"Updated {name}")

        copyApplyScripts(codeRoot, projectFiles)
        if (
            sys.platform.startswith("win")
            or (installRoot / "Data Doctor.exe").is_file()
            or (installRoot / "applyUpdate.cmd").is_file()
        ):
            writeApplyUpdateCmd(installRoot)

        # Trees (do not overwrite live bunker.db here — merge uses packaged core/bunker.db)
        treeNames = (
            "ui",
            "core",
            "quickLook",
            "oracle",
        )
        for tree in treeNames:
            src = codeRoot / tree
            if not src.is_dir():
                continue
            if tree == "core":
                copyTreeMerge(
                    src,
                    projectFiles / tree,
                    skipNames={"bunker.db", "applyUpdate.py"},
                )
                print("Updated core/ (bunker.db skipped — merge path)")
            else:
                copyTreeMerge(src, projectFiles / tree)
                print(f"Updated {tree}/")

        # Never copy certs/ from the zip — a user Aquarius cert must survive
        # updates. Create an empty folder only if the install has none.
        certsDir = projectFiles / "certs"
        if not certsDir.is_dir():
            certsDir.mkdir(parents=True, exist_ok=True)
            readme = certsDir / "README.txt"
            if not readme.is_file():
                readme.write_text(
                    "Optional Aquarius TLS certificates.\n"
                    "Place aquarius.pem or a .cer/.crt here. .pfx is not supported.\n",
                    encoding="utf-8",
                )
            print("Created empty Project Files/certs/ (not overwritten on later updates)")
        else:
            print("Left Project Files/certs/ unchanged")

        py = ensurePython(projectFiles)
        print(f"Using Python: {py}")

        # Bunker merge: packaged DB is core/bunker.db in the raw Python zip
        # (or Project Files/core or Project Files/temp in a Windows zip).
        packagedBunker = codeRoot / "core" / "bunker.db"
        if not packagedBunker.is_file():
            packagedBunker = codeRoot / "temp" / "bunker.db"
        if packagedBunker.is_file():
            rc = runBunkerMerge(py, projectFiles, packagedBunker)
            if rc != 0:
                print(f"WARN: bunker merge exited {rc}", file=sys.stderr)
        else:
            print("No packaged core/bunker.db in zip — skipped dictionary merge")

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
        projectFiles = installRoot / "Project Files"
        zipPath = pickUpdateZip(updateDir, projectFiles)
        if zipPath is None:
            print(
                f"ERROR: No *.zip found in {updateDir}\n"
                "  Place DataDoctor-Python-*.zip (code) or DataDoctor-Windows-*.zip "
                "(launcher + python-embed) there, or pass --zip path",
                file=sys.stderr,
            )
            return 1

    print(f"Update zip: {zipPath}")
    return apply(zipPath, installRoot, keepExtract=args.keepExtract)


if __name__ == "__main__":
    sys.exit(main())
