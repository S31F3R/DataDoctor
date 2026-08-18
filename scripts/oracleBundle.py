#!/usr/bin/env python3
"""
Bundle a platform Instant Client from dist/oracle/*.zip into a package.

Drop (or replace) these files — same name, new contents when Oracle updates:

  dist/oracle/oracle-windows.zip
  dist/oracle/oracle-linux.zip
  dist/oracle/oracle-macos.zip

Official Instant Client zips (a single instantclient_* folder at the root)
and a flat zip of the library files both work. Contents land at oracle/client
inside the package (what core/Oracle.py looks for).

The Python update zip does not take these — Instant Client is OS-specific.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

ZIP_DIR = Path("dist") / "oracle"

ZIP_NAMES = {
    "windows": ("oracle-windows.zip", "oracle-win.zip"),
    "linux": ("oracle-linux.zip",),
    "macos": ("oracle-macos.zip", "oracle-mac.zip", "oracle-darwin.zip"),
}

# Files core/Oracle.py requires before it treats a packaged client as ready
MARKER_FILES = {
    "windows": "oci.dll",
    "linux": "libociei.so",
    "macos": "libociei.dylib",
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


def _unwrapClientRoot(extracted: Path) -> Path:
    """
    Official Instant Client zips are instantclient_23_7/* .
    Also accept oracle/client/*, client/*, or files at the zip root.
    """
    for rel in (
        Path("oracle") / "client",
        Path("client"),
    ):
        cand = extracted / rel
        if cand.is_dir() and any(cand.iterdir()):
            return cand

    entries = [p for p in extracted.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted


def extractOracleZip(zipPath: Path, destClient: Path) -> Path:
    if destClient.exists():
        shutil.rmtree(destClient)
    destClient.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dd-oracle-") as tmp:
        tmpPath = Path(tmp)
        with zipfile.ZipFile(zipPath, "r") as zf:
            zf.extractall(tmpPath)
        src = _unwrapClientRoot(tmpPath)
        for item in src.iterdir():
            dest = destClient / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
    return destClient


def installOracleClient(root: Path, destClient: Path, platformKey: str) -> bool:
    """
    Fill destClient (…/oracle/client) from dist/oracle/oracle-<platform>.zip.
    Falls back to a repo oracle/client tree if no zip is present.
    Returns True if a client was installed.
    """
    z = findOracleZip(root, platformKey)
    if z is not None:
        try:
            rel = z.relative_to(root)
        except ValueError:
            rel = z
        print(f"Bundling Instant Client from {rel}")
        extractOracleZip(z, destClient)
        marker = MARKER_FILES.get(platformKey)
        if marker and not (destClient / marker).is_file():
            print(
                f"WARN: {rel} has no {marker} — "
                f"core/Oracle.py will not treat this as a packaged client on {platformKey}",
            )
        return True

    src = root / "oracle" / "client"
    if src.is_dir() and any(src.iterdir()):
        print(f"Bundling Instant Client from oracle/client (no {platformKey} zip)")
        if destClient.exists():
            shutil.rmtree(destClient)
        shutil.copytree(src, destClient, ignore=shutil.ignore_patterns("__pycache__"))
        return True

    names = ZIP_NAMES.get(platformKey, ())
    expected = names[0] if names else f"oracle-{platformKey}.zip"
    print(f"NOTE: no {expected} in dist/oracle/ — Instant Client not bundled")
    return False


def writeDummyOracleZips(root: Path) -> list[Path]:
    """Tiny stand-in zips so packagers can be tested without a real Instant Client."""
    folder = zipDir(root)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    layouts = {
        "windows": ("instantclient_dummy", "oci.dll"),
        "linux": ("instantclient_dummy", "libociei.so"),
        "macos": ("instantclient_dummy", "libociei.dylib"),
    }
    for key, (top, marker) in layouts.items():
        name = ZIP_NAMES[key][0]
        path = folder / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{top}/{marker}",
                b"DataDoctor dummy Instant Client marker - replace this zip.\n",
            )
            zf.writestr(
                f"{top}/README.txt",
                (
                    f"Dummy {key} Instant Client for package tests.\n"
                    f"Replace {name} with a real Instant Client zip (same filename).\n"
                ),
            )
        written.append(path)
    return written


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parent.parent
    created = writeDummyOracleZips(root)
    print("Wrote dummy Instant Client zips:")
    for p in created:
        print(f"  {p}")
    sys.exit(0)
