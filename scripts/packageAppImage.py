#!/usr/bin/env python3
"""
Build a true Linux AppImage for DataDoctor.

The AppImage is always host-native: PyInstaller freezes against the glibc and
CPU of the machine that runs this script. Ship separate builds per target
architecture (x86_64, aarch64, …).

Prerequisites:
  - Linux host (or WSL)
  - Python 3.13 + project venv with requirements.txt installed
  - PyInstaller:  pip install pyinstaller
  - appimagetool for this arch under scripts/appimagetool/ (preferred):
        scripts/appimagetool/appimagetool-x86_64.appimage
        scripts/appimagetool/appimagetool-aarch64.appimage
        scripts/appimagetool/appimagetool-armhf.appimage
        scripts/appimagetool/appimagetool-i686.appimage
    Download from: https://github.com/AppImage/appimagetool/releases
    Or pass --appimagetool /path/to/tool, put tools in dist/appimagetool/,
    or put appimagetool on PATH.

What this does:
  1) PyInstaller --onedir (host arch)
  2) Assemble AppDir (AppRun + .desktop + icon)
  3) Run the matching appimagetool → dist/DataDoctor-<arch>-YYYYMMDD.AppImage

No zip/tar.gz is produced — only the .AppImage. Intermediate build trees are
removed after a successful pack unless --keep-build is set.

Run from project root:
  python scripts/packageAppImage.py
  python scripts/packageAppImage.py --out dist/DataDoctor.AppImage
  python scripts/packageAppImage.py --appimagetool scripts/appimagetool/appimagetool-x86_64.appimage
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def projectRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def archLabel() -> str:
    """
    Canonical AppImage / appimagetool arch name for this host.

    Matches filenames: appimagetool-x86_64.appimage, appimagetool-aarch64.appimage, …
    """
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    if m in ("armv7l", "armv7", "armhf", "armv6l"):
        return "armhf"
    if m in ("i386", "i686", "x86"):
        return "i686"
    return m or "unknown"


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd, cwd=None, env=None):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, cwd=cwd, env=env)


def findAppImageTool(root: Path, arch: str, explicit: str | None = None) -> Path:
    """
    Resolve appimagetool for this host arch.

    Preference order:
      1) --appimagetool path
      2) scripts/appimagetool/appimagetool-<arch>.appimage  (project-bundled)
      3) dist/appimagetool/appimagetool-<arch>.appimage  (legacy location)
      4) unversioned names under either tool dir
      5) PATH: appimagetool, appimagetool-<arch>
    """
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"--appimagetool not found: {p}")
        return p.resolve()

    toolDirs = [
        root / "scripts" / "appimagetool",
        root / "dist" / "appimagetool",
    ]
    # Filenames as shipped from AppImage/appimagetool releases
    nameVariants = [
        f"appimagetool-{arch}.appimage",
        f"appimagetool-{arch}.AppImage",
        f"appimagetool-{arch}",
        "appimagetool.appimage",
        "appimagetool.AppImage",
        "appimagetool",
    ]
    for toolDir in toolDirs:
        for name in nameVariants:
            cand = toolDir / name
            if cand.is_file():
                return cand.resolve()

    # Any file in a tool dir that mentions this arch
    for toolDir in toolDirs:
        if not toolDir.is_dir():
            continue
        for p in sorted(toolDir.iterdir()):
            if not p.is_file():
                continue
            name = p.name.lower()
            if "appimagetool" in name and arch.lower() in name:
                return p.resolve()

    for name in (f"appimagetool-{arch}", "appimagetool"):
        hit = which(name)
        if hit:
            return Path(hit).resolve()

    foundNotes = []
    for toolDir in toolDirs:
        rel = toolDir.relative_to(root)
        if toolDir.is_dir():
            available = sorted(p.name for p in toolDir.iterdir() if p.is_file())
            foundNotes.append(
                f"  Found under {rel}/: {', '.join(available)}"
                if available
                else f"  {rel}/ is empty or missing."
            )
        else:
            foundNotes.append(f"  {rel}/ is empty or missing.")
    hint = "\n" + "\n".join(foundNotes)
    raise FileNotFoundError(
        f"No appimagetool for arch {arch!r}.{hint}\n"
        "  Expected e.g. scripts/appimagetool/appimagetool-x86_64.appimage\n"
        "  https://github.com/AppImage/appimagetool/releases\n"
        "  Or: --appimagetool /path/to/appimagetool-<arch>.appimage"
    )


def ensureExecutable(path: Path) -> None:
    mode = path.stat().st_mode
    # u+x at minimum; keep other bits
    path.chmod(mode | 0o111)


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
    apps = appDir / "usr" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "DataDoctor.desktop").write_text(desktop, encoding="utf-8")


def writeAppRun(appDir: Path):
    script = """#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export APPDIR="$HERE"
if [ -d "$HERE/usr/lib" ]; then
  export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [ -x "$HERE/usr/bin/DataDoctor" ]; then
  exec "$HERE/usr/bin/DataDoctor" "$@"
fi
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
    dest = appDir / "DataDoctor.png"
    if iconSrc.suffix.lower() == ".png":
        shutil.copy2(iconSrc, dest)
    else:
        shutil.copy2(iconSrc, appDir / f"DataDoctor{iconSrc.suffix.lower()}")
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

    # oracledb (Cython base_impl) imports stdlib modules that PyInstaller does not
    # always trace: getpass, secrets, ssl, … Missing getpass → AppImage crash on
    # first Oracle import. Same class of issue as oracle/python-oracledb#31.
    # --collect-all pulls package data + binaries; hidden-imports cover stdlib.
    for package in ("oracledb", "cryptography", "keyring", "matplotlib"):
        args.extend(["--collect-all", package])

    for mod in (
        # App stack
        "PyQt6",
        "keyring",
        "keyring.backends",
        "keyring.backends.SecretService",
        "keyring.backends.chainer",
        "keyring.backends.fail",
        "keyring.backends.libsecret",
        "keyring.backends.kwallet",
        "oracledb",
        "numpy",
        "matplotlib",
        "matplotlib.backends.backend_qtagg",
        "secretstorage",
        "jeepney",
        # oracledb / thin mode stdlib + crypto (not always auto-detected)
        "getpass",
        "secrets",
        "ssl",
        "socket",
        "decimal",
        "json",
        "platform",
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.backends",
        "cryptography.hazmat.backends.openssl",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.hashes",
        "cryptography.hazmat.primitives.kdf",
        "cryptography.hazmat.primitives.asymmetric",
        "cryptography.hazmat.primitives.ciphers",
        "cryptography.hazmat.primitives.serialization",
    ):
        args.extend(["--hidden-import", mod])

    args.append(str(root / "DataDoctor.py"))
    return args


def main() -> int:
    root = projectRoot()
    parser = argparse.ArgumentParser(
        description="Package DataDoctor as a true Linux AppImage (host arch only)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output AppImage path (default: dist/DataDoctor-<arch>-YYYYMMDD.AppImage)",
    )
    parser.add_argument(
        "--appimagetool",
        default=None,
        help="Path to appimagetool binary (default: scripts/appimagetool/appimagetool-<arch>.appimage)",
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

    arch = archLabel()
    print(f"Host arch: {platform.machine()} → AppImage arch: {arch}")

    try:
        tool = findAppImageTool(root, arch, args.appimagetool)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    ensureExecutable(tool)
    print(f"Using appimagetool: {tool}")

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
    distRoot = root / "dist" / "linux"
    workPath = distRoot / "build"
    pyDist = distRoot / "pyinstaller"
    appDir = distRoot / "AppDir"

    for p in (pyDist, appDir):
        if p.exists():
            shutil.rmtree(p)
    distRoot.mkdir(parents=True, exist_ok=True)
    workPath.mkdir(parents=True, exist_ok=True)

    print("=== PyInstaller onedir ===")
    run(pyinstallerSpecArgs(root, pyDist, workPath), cwd=root)

    built = pyDist / "DataDoctor"
    binary = built / "DataDoctor"
    if not binary.is_file():
        print(f"ERROR: expected binary at {binary}", file=sys.stderr)
        return 1

    print("=== Assemble AppDir ===")
    appDir.mkdir(parents=True)
    usrBin = appDir / "usr" / "bin"
    usrBin.mkdir(parents=True)
    usrTree = appDir / "usr" / "DataDoctor"
    shutil.copytree(built, usrTree, symlinks=True)
    link = usrBin / "DataDoctor"
    try:
        link.symlink_to(os.path.relpath(usrTree / "DataDoctor", usrBin))
    except OSError:
        shutil.copy2(usrTree / "DataDoctor", link)
        link.chmod(0o755)

    writeAppRun(appDir)
    writeDesktop(appDir)
    stageIcon(appDir, findIcon(root))

    outAppImage = (
        Path(args.out)
        if args.out
        else (root / "dist" / f"DataDoctor-{arch}-{stamp}.AppImage")
    )
    if outAppImage.suffix.lower() != ".appimage":
        outAppImage = outAppImage.with_suffix(outAppImage.suffix + ".AppImage") \
            if outAppImage.suffix else Path(str(outAppImage) + ".AppImage")

    outAppImage = outAppImage.resolve()
    outAppImage.parent.mkdir(parents=True, exist_ok=True)
    if outAppImage.exists():
        outAppImage.unlink()

    print(f"=== appimagetool → {outAppImage} ===")
    env = os.environ.copy()
    env["ARCH"] = arch
    # Some distros mount AppImages with FUSE; allow extract-and-run fallback
    env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")

    try:
        run([str(tool), str(appDir), str(outAppImage)], env=env)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: appimagetool failed: {e}", file=sys.stderr)
        print(f"AppDir left at {appDir} for inspection (--keep-build not required on failure)", file=sys.stderr)
        return 1

    if not outAppImage.is_file():
        # appimagetool sometimes writes relative to cwd with a different casing
        alt = outAppImage.parent / outAppImage.name
        if not alt.is_file():
            print("ERROR: appimagetool finished but .AppImage was not created", file=sys.stderr)
            print(f"AppDir left at {appDir}", file=sys.stderr)
            return 1
        outAppImage = alt

    outAppImage.chmod(0o755)
    sizeMb = outAppImage.stat().st_size / (1024 * 1024)
    print(f"Done: {outAppImage} ({sizeMb:.1f} MB)  arch={arch}")

    if not args.keepBuild:
        shutil.rmtree(workPath, ignore_errors=True)
        shutil.rmtree(pyDist, ignore_errors=True)
        shutil.rmtree(appDir, ignore_errors=True)
        # Drop empty linux/ stage if nothing left
        try:
            if distRoot.is_dir() and not any(distRoot.iterdir()):
                distRoot.rmdir()
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
