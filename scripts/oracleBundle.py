#!/usr/bin/env python3
"""
Bundle a platform Instant Client into oracle/client inside a package.

Drop (or replace) these under dist/oracle/ — same name, new contents
when Oracle updates:

  oracle-windows.zip   (files at zip root, or one wrapper folder)
  oracle-linux.zip
  oracle-macos.zip     (files, or a single oracle.dmg inside)
  oracle.dmg           (macOS Instant Client disk image, optional)

Whatever folder the archive uses (oracle-windows, instantclient_23_7, …)
is unwrapped. The package always gets:

  …/oracle/client/oci.dll          (Windows)
  …/oracle/client/libociicus.so    (Linux Basic Lite)
  …/oracle/client/libociicus.dylib (macOS Basic Lite)

The Python update zip does not take these — Instant Client is OS-specific.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ZIP_DIR = Path("dist") / "oracle"

ZIP_NAMES = {
    "windows": ("oracle-windows.zip", "oracle-win.zip"),
    "linux": ("oracle-linux.zip",),
    "macos": ("oracle-macos.zip", "oracle-mac.zip", "oracle-darwin.zip"),
}

# Any one of these means core/Oracle.py will use the packaged client
MARKER_FILES = {
    "windows": ("oci.dll",),
    "linux": ("libociei.so", "libociicus.so"),
    "macos": ("libociei.dylib", "libociicus.dylib"),
}

_WRAPPER_NAMES = {
    "oracle-windows",
    "oracle-linux",
    "oracle-macos",
    "oracle-win",
    "oracle-mac",
    "oracle-darwin",
    "client",
}


def zipDir(root: Path) -> Path:
    return root / ZIP_DIR


def findOracleZip(root: Path, platformKey: str) -> Path | None:
    names = ZIP_NAMES.get(platformKey)
    if not names:
        return None
    folder = zipDir(root)
    for name in names:
        p = folder / name
        if p.is_file():
            return p
    return None


def findMacosDmg(root: Path) -> Path | None:
    folder = zipDir(root)
    if not folder.is_dir():
        return None
    exact = folder / "oracle.dmg"
    if exact.is_file():
        return exact
    hits = sorted(folder.glob("instantclient*.dmg")) + sorted(folder.glob("*.dmg"))
    return hits[0] if hits else None


def _unwrapClientRoot(extracted: Path) -> Path:
    """
    Never keep the archive's wrapper folder name.
    Prefer oracle/client or client; else unwrap a single top-level directory
    (oracle-windows, instantclient_23_7, …).
    """
    for rel in (Path("oracle") / "client", Path("client")):
        cand = extracted / rel
        if cand.is_dir() and any(cand.iterdir()):
            return cand

    entries = [
        p for p in extracted.iterdir()
        if p.name not in ("__MACOSX", ".DS_Store") and not p.name.startswith(".")
    ]
    if len(entries) == 1 and entries[0].is_dir():
        name = entries[0].name.lower()
        if name in _WRAPPER_NAMES or name.startswith("instantclient"):
            return _unwrapClientRoot(entries[0])
        return entries[0]
    return extracted


def _run7zExtract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("7z") or shutil.which("7zz")
    if exe:
        r = subprocess.run(
            [exe, "x", str(archive), f"-o{dest}", "-y"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"7z failed on {archive.name}: {(r.stderr or r.stdout or '').strip()[-400:]}"
            )
        # Some 7z builds drop a nested 4.apfs / *.apfs that needs a second pass
        nested = [
            p for p in dest.rglob("*")
            if p.is_file() and p.suffix.lower() in (".apfs", ".dmg", ".hfs")
        ]
        libs = list(dest.rglob("*.dylib")) + list(dest.rglob("*.so")) + list(dest.rglob("*.dll"))
        if nested and not libs:
            inner = dest / "_inner"
            inner.mkdir(exist_ok=True)
            _run7zExtract(nested[0], inner)
            for item in inner.iterdir():
                shutil.move(str(item), dest / item.name)
            shutil.rmtree(inner, ignore_errors=True)
        return

    if sys.platform == "darwin" and shutil.which("hdiutil"):
        mount = dest / "_mnt"
        mount.mkdir(exist_ok=True)
        r = subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(archive)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"hdiutil attach failed: {(r.stderr or r.stdout or '').strip()}")
        try:
            for item in mount.iterdir():
                target = dest / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], capture_output=True)
        return

    raise RuntimeError(
        f"cannot extract {archive.name}: install 7z (Linux) or use hdiutil (macOS)"
    )


def _dmgInTree(folder: Path) -> Path | None:
    preferred = folder / "oracle.dmg"
    if preferred.is_file():
        return preferred
    hits = sorted(folder.rglob("*.dmg"))
    return hits[0] if hits else None


def _ensureVersionLinks(clientDir: Path) -> None:
    """7z skips DMG symlinks (libclntsh.dylib -> libclntsh.dylib.23.1). Recreate them."""
    stems = ("libclntsh.dylib", "libclntshcore.dylib", "libocci.dylib")
    for stem in stems:
        link = clientDir / stem
        if link.exists():
            continue
        versions = [
            p for p in clientDir.iterdir()
            if p.is_file() and p.name.startswith(stem + ".")
        ]
        if not versions:
            continue
        versions.sort(key=lambda p: p.name)
        try:
            os.symlink(versions[-1].name, link)
        except OSError:
            shutil.copy2(versions[-1], link)


def _copyIntoClient(src: Path, destClient: Path) -> None:
    if destClient.exists():
        shutil.rmtree(destClient)
    destClient.mkdir(parents=True, exist_ok=True)
    src = _unwrapClientRoot(src)
    # If unwrap still left a single wrapper named like the zip, peel once more
    entries = [p for p in src.iterdir() if p.name not in ("__MACOSX", ".DS_Store")]
    if len(entries) == 1 and entries[0].is_dir() and entries[0].name.lower() in _WRAPPER_NAMES:
        src = entries[0]
    for item in src.iterdir():
        if item.name in ("__MACOSX", ".DS_Store"):
            continue
        dest = destClient / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
    _ensureVersionLinks(destClient)


def extractOracleZip(zipPath: Path, destClient: Path) -> Path:
    """Extract a platform zip (or a zip that only wraps oracle.dmg) into destClient."""
    with tempfile.TemporaryDirectory(prefix="dd-oracle-") as tmp:
        tmpPath = Path(tmp)
        with zipfile.ZipFile(zipPath, "r") as zf:
            zf.extractall(tmpPath)
        dmg = _dmgInTree(tmpPath)
        if dmg is not None:
            dmgOut = tmpPath / "_dmg"
            print(f"  extracting {dmg.name} from zip")
            _run7zExtract(dmg, dmgOut)
            _copyIntoClient(dmgOut, destClient)
        else:
            _copyIntoClient(tmpPath, destClient)
    return destClient


def extractOracleDmg(dmgPath: Path, destClient: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="dd-oracle-dmg-") as tmp:
        tmpPath = Path(tmp)
        _run7zExtract(dmgPath, tmpPath)
        _copyIntoClient(tmpPath, destClient)
    return destClient


def installOracleClient(root: Path, destClient: Path, platformKey: str) -> bool:
    """
    Fill destClient (must be …/oracle/client) from dist/oracle archives.
    Falls back to a repo oracle/client tree if no archive is present.
    """
    destClient = Path(destClient)
    if destClient.name != "client":
        destClient = destClient / "client"

    z = findOracleZip(root, platformKey)
    dmg = findMacosDmg(root) if platformKey == "macos" else None

    source = None
    kind = None
    if z is not None:
        source, kind = z, "zip"
    elif dmg is not None:
        source, kind = dmg, "dmg"

    if source is not None:
        try:
            rel = source.relative_to(root)
        except ValueError:
            rel = source
        print(f"Bundling Instant Client from {rel}")
        if kind == "dmg":
            extractOracleDmg(source, destClient)
        else:
            extractOracleZip(source, destClient)
        markers = MARKER_FILES.get(platformKey, ())
        if markers and not any((destClient / m).is_file() for m in markers):
            print(
                f"WARN: no { ' / '.join(markers) } in {destClient} — "
                f"core/Oracle.py will not treat this as a packaged client on {platformKey}",
            )
        else:
            print(f"  Instant Client files → {destClient}")
        return True

    src = root / "oracle" / "client"
    if src.is_dir() and any(src.iterdir()):
        print(f"Bundling Instant Client from oracle/client (no {platformKey} archive)")
        if destClient.exists():
            shutil.rmtree(destClient)
        shutil.copytree(src, destClient, ignore=shutil.ignore_patterns("__pycache__"))
        return True

    names = ZIP_NAMES.get(platformKey, ())
    expected = names[0] if names else f"oracle-{platformKey}.zip"
    extra = " (or oracle.dmg)" if platformKey == "macos" else ""
    print(f"NOTE: no {expected}{extra} in dist/oracle/ — Instant Client not bundled")
    return False


def writeDummyOracleZips(root: Path) -> list[Path]:
    """Tiny stand-in zips. Will not overwrite a real archive (>10 KB)."""
    folder = zipDir(root)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    # Files at zip root — same layout as the real Windows / Linux Instant Client zips
    layouts = {
        "windows": "oci.dll",
        "linux": "libociicus.so",
        "macos": "libociicus.dylib",
    }
    for key, marker in layouts.items():
        name = ZIP_NAMES[key][0]
        path = folder / name
        if path.is_file() and path.stat().st_size > 10_000:
            print(f"keep existing {path.name}")
            written.append(path)
            continue
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(marker, b"DataDoctor dummy Instant Client marker.\n")
            zf.writestr(
                "README.txt",
                f"Dummy {key} Instant Client. Replace {name} with the real archive.\n",
            )
        written.append(path)
    return written


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    created = writeDummyOracleZips(root)
    print("Instant Client archives in dist/oracle/:")
    for p in created:
        print(f"  {p}")
    sys.exit(0)
