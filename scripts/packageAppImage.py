#!/usr/bin/env python3
"""
Build a Linux AppImage for DataDoctor (and optionally a portable tar.gz).

Prerequisites (on a Linux host matching the target glibc):
  - Python 3.13 + project venv with requirements.txt installed
  - PyInstaller:  pip install pyinstaller
  - appimagetool (optional but needed for a real .AppImage):
      https://github.com/AppImage/appimagetool/releases
      Place on PATH as `appimagetool`, or pass --appimagetool /path/to/appimagetool

What this does:
  1) PyInstaller --onedir into dist/linux/AppDir/usr
  2) Wires AppRun + DataDoctor.desktop + icon
  3) Runs appimagetool → dist/DataDoctor-x86_64.AppImage (or aarch64)
  4) Always also writes a portable tar.gz of the AppDir (works without appimagetool)

Run from project root:
  python scripts/packageAppImage.py
  python scripts/packageAppImage.py --skip-appimage   # tar.gz only
  python scripts/packageAppImage.py --out dist/My.AppImage
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path


def projectRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def archLabel() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    return m or "unknown"


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd, cwd=None, env=None):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, cwd=cwd, env=env)


def writeDesktop(appDir: Path, iconName: str = "DataDoctor"):
    desktop = f"""[Desktop Entry]
Type=Application
Name=Data Doctor
Comment=Time-series data query and QA tool
Exec=DataDoctor
Icon={iconName}
Categories=Science;Utility;
Terminal=false
"""
    (appDir / "DataDoctor.desktop").write_text(desktop, encoding="utf-8")
    # Also under usr/share/applications for tools that look there
    apps = appDir / "usr" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "DataDoctor.desktop").write_text(desktop, encoding="utf-8")


def writeAppRun(appDir: Path):
    # Prefer the PyInstaller binary under usr/bin when present; else usr/DataDoctor/
    script = """#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export APPDIR="$HERE"
# Bundled libs first
if [ -d "$HERE/usr/lib" ]; then
  export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# PyInstaller onedir layout used by this script: usr/bin/DataDoctor
if [ -x "$HERE/usr/bin/DataDoctor" ]; then
  exec "$HERE/usr/bin/DataDoctor" "$@"
fi
# Fallback: nested folder
if [ -x "$HERE/usr/DataDoctor/DataDoctor" ]; then
  exec "$HERE/usr/DataDoctor/DataDoctor" "$@"
fi
echo "ERROR: DataDoctor binary not found under $HERE/usr" >&2
exit 1
"""
    appRun = appDir / "AppRun"
    appRun.write_text(script, encoding="utf-8")
    appRun.chmod(0o755)


def findIcon(root: Path) -> Path | None:
    for rel in (
        "ui/icons/DataDoctor.png",
        "ui/icons/DataDoctor.ico",
        "ui/DataDoctor.png",
    ):
        p = root / rel
        if p.is_file():
            return p
    return None


def stageIcon(appDir: Path, iconSrc: Path | None):
    if iconSrc is None:
        print("WARN: no DataDoctor icon found for AppDir")
        return
    # AppImage convention: icon next to desktop file, basename matches Icon=
    dest = appDir / "DataDoctor.png"
    if iconSrc.suffix.lower() == ".png":
        shutil.copy2(iconSrc, dest)
    else:
        # .ico — still copy; some desktops accept it; prefer png when available
        shutil.copy2(iconSrc, appDir / f"DataDoctor{iconSrc.suffix.lower()}")
        if iconSrc.suffix.lower() != ".png":
            # Also try as .png name so Icon=DataDoctor resolves on some loaders
            shutil.copy2(iconSrc, dest)
    iconsDir = appDir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    iconsDir.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        shutil.copy2(dest, iconsDir / "DataDoctor.png")


def pyinstallerSpecArgs(root: Path, distPath: Path, workPath: Path) -> list:
    """Build pyinstaller CLI args for a onedir app under distPath."""
    datas = [
        ("ui", "ui"),
        ("quickLook", "quickLook"),
        ("core", "core"),
        ("oracle", "oracle"),
        ("documentation", "documentation"),
    ]
    if (root / "certs").is_dir():
        # Optional: only if user has certs in tree (app also searches user config)
        pass

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--noconsole",
        "--noupx",
        "--onedir",
        "--name", "DataDoctor",
        "--distpath", str(distPath),
        "--workpath", str(workPath),
        "--specpath", str(workPath),
    ]
    iconPng = root / "ui" / "icons" / "DataDoctor.png"
    if iconPng.is_file():
        args.extend(["--icon", str(iconPng)])

    sep = os.pathsep  # ':' on Linux
    for src, dest in datas:
        srcPath = root / src
        if srcPath.exists():
            args.extend(["--add-data", f"{srcPath}{sep}{dest}"])

    # Hidden imports that PyInstaller often misses for this stack
    for mod in (
        "PyQt6",
        "keyring",
        "keyring.backends",
        "oracledb",
        "numpy",
        "secretstorage",
    ):
        args.extend(["--hidden-import", mod])

    args.append(str(root / "DataDoctor.py"))
    return args


def main() -> int:
    root = projectRoot()
    parser = argparse.ArgumentParser(description="Package DataDoctor as a Linux AppImage")
    parser.add_argument(
        "--out",
        default=None,
        help="Output AppImage path (default: dist/DataDoctor-<arch>-YYYYMMDD.AppImage)",
    )
    parser.add_argument(
        "--skip-appimage",
        dest="skipAppImage",
        action="store_true",
        help="Only build AppDir + tar.gz (do not run appimagetool)",
    )
    parser.add_argument(
        "--appimagetool",
        default=None,
        help="Path to appimagetool binary (default: search PATH)",
    )
    parser.add_argument(
        "--keep-build",
        dest="keepBuild",
        action="store_true",
        help="Keep intermediate PyInstaller work/ and AppDir after packaging",
    )
    args = parser.parse_args()

    if sys.platform.startswith("win"):
        print("ERROR: packageAppImage.py must run on Linux (or WSL).", file=sys.stderr)
        return 1

    if not (root / "DataDoctor.py").is_file():
        print("ERROR: DataDoctor.py not found — run from project root", file=sys.stderr)
        return 1

    # PyInstaller available?
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "ERROR: PyInstaller not installed in this environment.\n"
            "  pip install pyinstaller\n"
            "  (use the same venv you run DataDoctor with)",
            file=sys.stderr,
        )
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    arch = archLabel()
    distRoot = root / "dist" / "linux"
    workPath = distRoot / "build"
    pyDist = distRoot / "pyinstaller"
    appDir = distRoot / "AppDir"

    # Clean prior stage
    for p in (pyDist, appDir):
        if p.exists():
            shutil.rmtree(p)
    distRoot.mkdir(parents=True, exist_ok=True)
    workPath.mkdir(parents=True, exist_ok=True)

    print("=== PyInstaller onedir ===")
    run(pyinstallerSpecArgs(root, pyDist, workPath), cwd=root)

    # Expected: dist/linux/pyinstaller/DataDoctor/DataDoctor
    built = pyDist / "DataDoctor"
    binary = built / "DataDoctor"
    if not binary.is_file():
        print(f"ERROR: expected binary at {binary}", file=sys.stderr)
        return 1

    print("=== Assemble AppDir ===")
    appDir.mkdir(parents=True)
    # Layout: AppDir/usr/bin/DataDoctor + sibling _internal / libs from onedir
    usrBin = appDir / "usr" / "bin"
    usrBin.mkdir(parents=True)
    # Copy entire onedir next to bin... PyInstaller 6 uses DataDoctor/ + _internal/
    # Put the whole tree under usr/ and symlink/exec via AppRun
    usrTree = appDir / "usr" / "DataDoctor"
    shutil.copytree(built, usrTree, symlinks=True)
    # Convenience: usr/bin/DataDoctor → ../DataDoctor/DataDoctor
    link = usrBin / "DataDoctor"
    try:
        link.symlink_to(os.path.relpath(usrTree / "DataDoctor", usrBin))
    except OSError:
        shutil.copy2(usrTree / "DataDoctor", link)
        link.chmod(0o755)

    writeAppRun(appDir)
    writeDesktop(appDir)
    stageIcon(appDir, findIcon(root))

    # Portable tar.gz always
    tarPath = root / "dist" / f"DataDoctor-Linux-{arch}-{stamp}.tar.gz"
    tarPath.parent.mkdir(parents=True, exist_ok=True)
    print(f"=== Writing {tarPath} ===")
    with tarfile.open(tarPath, "w:gz") as tar:
        tar.add(appDir, arcname="DataDoctor.AppDir")
    print(f"Portable AppDir archive: {tarPath} ({tarPath.stat().st_size / 1024 / 1024:.1f} MB)")

    outAppImage = (
        Path(args.out)
        if args.out
        else (root / "dist" / f"DataDoctor-{arch}-{stamp}.AppImage")
    )

    if args.skipAppImage:
        print("Skipping AppImage (--skip-appimage). Use the tar.gz or run AppDir/AppRun.")
        if not args.keepBuild:
            shutil.rmtree(workPath, ignore_errors=True)
            shutil.rmtree(pyDist, ignore_errors=True)
        print("Done.")
        return 0

    tool = args.appimagetool or which("appimagetool")
    if not tool:
        # Common local drop locations
        for cand in (
            root / "scripts" / "appimagetool",
            root / "dist" / "appimagetool",
            Path.home() / "bin" / "appimagetool",
        ):
            if cand.is_file() and os.access(cand, os.X_OK):
                tool = str(cand)
                break

    if not tool:
        print(
            "\nWARN: appimagetool not found — AppImage not built.\n"
            "  Install from https://github.com/AppImage/appimagetool/releases\n"
            "  then re-run, or:\n"
            f"    appimagetool {appDir} {outAppImage}\n"
            f"Portable archive is ready: {tarPath}\n"
            f"Or run: {appDir / 'AppRun'}",
            file=sys.stderr,
        )
        if not args.keepBuild:
            shutil.rmtree(workPath, ignore_errors=True)
            shutil.rmtree(pyDist, ignore_errors=True)
        return 0  # tar.gz success; AppImage optional

    print(f"=== appimagetool → {outAppImage} ===")
    outAppImage.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # ARCH required by some appimagetool builds
    env.setdefault("ARCH", arch)
    try:
        run([tool, str(appDir), str(outAppImage)], env=env)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: appimagetool failed: {e}", file=sys.stderr)
        print(f"AppDir left at {appDir}; tar.gz at {tarPath}", file=sys.stderr)
        return 1

    if outAppImage.is_file():
        outAppImage.chmod(0o755)
        print(f"Done: {outAppImage} ({outAppImage.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        print("ERROR: appimagetool reported success but output missing", file=sys.stderr)
        return 1

    if not args.keepBuild:
        shutil.rmtree(workPath, ignore_errors=True)
        shutil.rmtree(pyDist, ignore_errors=True)
        # Keep AppDir only if user wants --keep-build; default remove after successful image
        shutil.rmtree(appDir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
