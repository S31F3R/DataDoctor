#!/usr/bin/env python3
"""
Apply a DataDoctor zip from the install's updates/ folder.

Expected install layout (Windows launcher package):
  <install root>/
    Data Doctor.exe | Data Doctor.command | …
    applyUpdate.cmd | applyUpdate.sh | this script (or under pythonFiles/scripts/)
    updates/                ← DataDoctor-Python-*.zip (code) or
                              DataDoctor-Windows-*.zip (launcher + python-embed)
                              (3.0.x leftover: Update/)
    pythonFiles/            ← Windows (generic launcher: app.pyw)
      app.pyw               ← DataDoctor.py renamed at package/apply time
      python-embed/         ← bundled CPython 3.14; no system Python
      core/                 ← live bunker.db stays here
      ui/
      …
    Project Files/          ← 3.0.x leftover; still accepted for migrate

What this does:
  1) Pick a zip in updates/ (Windows zip when Data Doctor.exe is installed)
  2) Extract to a temp dir under updates/
  3) Copy DataDoctor.py as app.pyw on Windows (pythonFiles/),
     plus ui/, core/* (except bunker.db), quickLook/, requirements
  4) Windows zip also replaces Data Doctor.exe and the icon.
     An existing python-embed of the same Python version is left in place.
     A different Python version is staged as python-embed.next while this
     process is running from python-embed. applyUpdate.cmd is staged as
     applyUpdate.cmd.new so cmd.exe is not rewritten while it is running.
     Data Doctor asks for a second restart to finish those staged files.
  5) If packaged bunker.db present: copy when live is missing (no prompts);
     otherwise merge via updateBunker.py
  6) pip install -r requirements.txt into python-embed (Windows) or .venv
  7) Move the zip into updates/held/ so Data Doctor.exe does not start this
     script again. The app deletes it after the install is finished.
     Remove the extract tree now.

Does NOT:
  - Touch user config / keyring / AppData
  - Delete user-added quickLook files (only overwrites same names)
  - Overwrite live core/bunker.db wholesale (merge only)
  - Copy or replace pythonFiles/certs (user Aquarius certs stay)

Run from install root:
  python applyUpdate.py
  python applyUpdate.py --zip updates/DataDoctor-Python-20260808.zip
  python "pythonFiles/scripts/applyUpdate.py"
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

WIN_CODE_DIR = "pythonFiles"
LEGACY_CODE_DIR = "Project Files"
CODE_DIR_NAMES = (WIN_CODE_DIR, LEGACY_CODE_DIR)
WIN_APP_ENTRY = "app.pyw"
UPDATES_DIR = "updates"
LEGACY_UPDATES_DIRS = ("Update", "Updates", "update", "UPDATES")
APPLY_ROOT_ENV = "DD_APPLY_INSTALL_ROOT"


def userLogDir() -> Path:
    """Same AppData logs folder the app writes (no Qt)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Data Doctor" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Data Doctor" / "logs"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "Data Doctor" / "logs"


def logStamp() -> str:
    """Match Python logging asctime: YYYY-MM-DD HH:MM:SS,mmm"""
    now = time.time()
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    ms = int((now % 1) * 1000)
    return f"{ts},{ms:03d}"


def appendAppLog(level: str, message: str) -> None:
    try:
        logDir = userLogDir()
        logDir.mkdir(parents=True, exist_ok=True)
        levelName = str(level or "INFO").upper()
        if levelName == "WARN":
            levelName = "WARNING"
        line = f"{logStamp()} [{levelName}] applyUpdate: {message}\n"
        with (logDir / "app.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def findInstallRoot(start: Path) -> Path:
    """
    Walk up from start to find pythonFiles/ or Project Files/
    (install root is its parent).
    """
    cur = start.resolve()
    for _ in range(6):
        for name in CODE_DIR_NAMES:
            if (cur / name).is_dir():
                return cur
            if cur.name == name and cur.parent.is_dir():
                return cur.parent
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def installRootConfirmed(root: Path) -> bool:
    """True when root looks like a Data Doctor install, not a temp folder."""
    try:
        root = root.resolve()
    except OSError:
        return False
    if any((root / name).is_dir() for name in CODE_DIR_NAMES):
        return True
    for name in (
        "Data Doctor.exe",
        "applyUpdate.cmd",
        "Data Doctor.command",
        "applyUpdate.sh",
        "DataDoctor.py",
    ):
        if (root / name).is_file():
            return True
    return False


def locateInstallRoot(scriptFile: Path | None = None) -> Path:
    """
    Install folder for this run.

    The zip's applyUpdate.py is started from a temp file. That path is not
    the install. The launcher's working directory is, and a parent that
    already found the folder passes DD_APPLY_INSTALL_ROOT.
    """
    hinted = os.environ.get(APPLY_ROOT_ENV)
    if hinted:
        hintedPath = Path(hinted).expanduser()
        if installRootConfirmed(hintedPath):
            return hintedPath.resolve()
    scriptFile = Path(scriptFile) if scriptFile is not None else Path(__file__)
    try:
        fromScript = findInstallRoot(scriptFile.resolve().parent)
    except OSError:
        fromScript = scriptFile.parent
    if installRootConfirmed(fromScript):
        return fromScript
    try:
        fromCwd = findInstallRoot(Path.cwd())
    except OSError:
        fromCwd = Path.cwd()
    if installRootConfirmed(fromCwd):
        return fromCwd
    return fromScript


def removeStrayTempUpdates(scriptFile: Path) -> None:
    """
    Delete an empty updates folder next to a temp reexec copy.

    An older run treated that temp folder as the install and created
    updates/ there before it noticed the zip was missing.
    """
    path = Path(scriptFile)
    if not path.name.startswith("dd-apply-") or path.suffix.lower() != ".py":
        return
    try:
        parent = path.resolve().parent
    except OSError:
        return
    if installRootConfirmed(parent):
        return
    updates = parent / UPDATES_DIR
    if not updates.is_dir():
        return
    try:
        files = [p for p in updates.rglob("*") if p.is_file()]
    except OSError:
        return
    if files:
        print(f"WARN: left {updates} in place (not empty)")
        return
    try:
        shutil.rmtree(updates)
        print(f"Removed stray {updates}")
    except OSError as e:
        print(f"WARN: could not remove stray {updates}: {e}", file=sys.stderr)


def isWindowsInstall(installRoot: Path) -> bool:
    return (installRoot / "Data Doctor.exe").is_file() or sys.platform.startswith("win")


def resolveCodeDir(installRoot: Path) -> Path:
    """Prefer pythonFiles/ (new Windows launcher); keep Project Files/ for 3.0.x / macOS."""
    win = installRoot / WIN_CODE_DIR
    legacy = installRoot / LEGACY_CODE_DIR
    if win.is_dir():
        return win
    if legacy.is_dir():
        return legacy
    if isWindowsInstall(installRoot):
        return win
    return legacy


def payloadCodeDir(payload: Path) -> Path:
    for name in CODE_DIR_NAMES:
        d = payload / name
        if d.is_dir():
            return d
    return payload


def allUpdatesDirs(installRoot: Path) -> list[Path]:
    """Canonical updates/ plus leftover Update/ from 3.0.x (Windows is case-insensitive)."""
    found: list[Path] = []
    seen: set[str] = set()
    for name in (UPDATES_DIR,) + LEGACY_UPDATES_DIRS:
        d = installRoot / name
        if not d.is_dir():
            continue
        try:
            key = os.path.normcase(str(d.resolve()))
        except Exception:
            key = os.path.normcase(str(d))
        if key in seen:
            continue
        seen.add(key)
        found.append(d)
    return found


def resolveUpdatesDir(installRoot: Path, create: bool = True) -> Path:
    for d in allUpdatesDirs(installRoot):
        if d.name == UPDATES_DIR:
            return d
    existing = allUpdatesDirs(installRoot)
    if existing:
        return existing[0]
    d = installRoot / UPDATES_DIR
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def pickNewestZip(updateDir: Path) -> Path | None:
    if not updateDir.is_dir():
        return None
    zips = sorted(
        updateDir.glob("*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return zips[0] if zips else None


def maybeDownloadWindowsZip(installRoot: Path) -> Path | None:
    """
    If python-embed is still missing after a Python-zip hop, download the
    matching DataDoctor-Windows-*.zip from GitHub (user already confirmed).
    """
    import json
    import urllib.request

    repo = "S31F3R/DataDoctor"
    api = f"https://api.github.com/repos/{repo}/releases?per_page=15"
    destDir = resolveUpdatesDir(installRoot, create=True)
    try:
        req = urllib.request.Request(
            api,
            headers={"User-Agent": "DataDoctor-applyUpdate", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"WARN: could not list GitHub releases for Windows zip ({e})", file=sys.stderr)
        appendAppLog("WARNING", f"Windows zip fetch list failed: {e}")
        return None
    if not isinstance(releases, list):
        return None
    for rel in releases:
        if rel.get("draft"):
            continue
        for asset in rel.get("assets") or []:
            name = (asset.get("name") or "").lower()
            url = asset.get("browser_download_url") or ""
            if name.endswith(".zip") and "windows" in name and url.startswith("https://"):
                dest = destDir / Path(asset.get("name") or "DataDoctor-Windows.zip").name
                print(f"Downloading {dest.name} (launcher + python-embed)…")
                appendAppLog("INFO", f"downloading {dest.name}")
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "DataDoctor-applyUpdate"}
                    )
                    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
                        while True:
                            chunk = resp.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                    if dest.is_file() and dest.stat().st_size > 0:
                        return dest
                except Exception as e:
                    print(f"WARN: Windows zip download failed ({e})", file=sys.stderr)
                    appendAppLog("WARNING", f"Windows zip download failed: {e}")
                    try:
                        dest.unlink()
                    except Exception:
                        pass
                    return None
    appendAppLog("WARNING", "no DataDoctor-Windows-*.zip on recent GitHub releases")
    return None


APPLIED_MARKER = "applied.json"
HELD_DIR = "held"


def _markerFiles(installRoot: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for d in allUpdatesDirs(installRoot):
        marker = d / APPLIED_MARKER
        if not marker.is_file():
            continue
        try:
            key = os.path.normcase(str(marker.resolve()))
        except OSError:
            key = os.path.normcase(str(marker))
        if key in seen:
            continue
        seen.add(key)
        found.append(marker)
    return found


def _loadZipList(marker: Path) -> list[str]:
    import json

    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    return [str(p) for p in data.get("zips") or [] if p]


def _saveZipList(marker: Path, zips: list[str]) -> None:
    import json

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"zips": zips}, indent=2) + "\n", encoding="utf-8")


def parkAppliedZip(zipPath: Path) -> Path:
    """Move a top-level updates zip into updates/held/. A zip already there stays."""
    zipPath = Path(zipPath)
    if not zipPath.is_file():
        return zipPath
    if zipPath.parent.name.lower() == HELD_DIR:
        try:
            return zipPath.resolve()
        except OSError:
            return zipPath
    held = zipPath.parent / HELD_DIR
    held.mkdir(parents=True, exist_ok=True)
    dest = held / zipPath.name
    if dest.exists():
        n = 2
        while dest.exists():
            dest = held / f"{zipPath.stem}-{n}{zipPath.suffix}"
            n += 1
    shutil.move(str(zipPath), str(dest))
    try:
        return dest.resolve()
    except OSError:
        return dest


def _heldTwin(zipPath: Path) -> Path | None:
    path = Path(zipPath)
    if path.parent.name.lower() == HELD_DIR and path.is_file():
        return path
    twin = path.parent / HELD_DIR / path.name
    if twin.is_file():
        return twin
    return None


def _recordParkedZip(installRoot: Path, original: Path, parked: Path) -> bool:
    """Store parked in applied.json. True when that path was not already listed."""
    try:
        text = str(parked.resolve())
    except OSError:
        text = str(parked)
    old = {str(original), text}
    try:
        old.add(str(original.resolve()))
    except OSError:
        old.add(str(original))
    updateDir = resolveUpdatesDir(installRoot, create=True)
    marker = updateDir / APPLIED_MARKER
    zips = _loadZipList(marker) if marker.is_file() else []
    already = text in zips
    new: list[str] = []
    for p in zips:
        if p == text:
            continue
        if p in old and not Path(p).is_file():
            continue
        new.append(p)
    new.append(text)
    _saveZipList(marker, new)
    return not already


def rememberAppliedZip(installRoot: Path, zipPath: Path) -> None:
    """
    Move an applied zip under updates/held/ and remember that path.

    Data Doctor.exe starts applyUpdate.cmd when a *.zip sits at the top of
    updates/. The file stays in held/ until the app confirms the install.
    """
    original = Path(zipPath)
    if original.is_file() and original.parent.name.lower() != HELD_DIR:
        parked = parkAppliedZip(original)
    else:
        parked = original if original.is_file() else _heldTwin(original)
        if parked is None:
            return
    if _recordParkedZip(installRoot, original, parked):
        print(f"Keeping {parked.name} until Data Doctor confirms the update")
        appendAppLog("INFO", f"keeping {parked.name} until the app confirms the update")


def parkRecordedZips(installRoot: Path) -> int:
    """Move zips already listed in applied.json out of the top of updates/."""
    moved = 0
    for marker in _markerFiles(installRoot):
        zips = _loadZipList(marker)
        new: list[str] = []
        changed = False
        for raw in zips:
            path = Path(raw)
            if path.is_file() and path.parent.name.lower() != HELD_DIR:
                parked = parkAppliedZip(path)
                try:
                    new.append(str(parked.resolve()))
                except OSError:
                    new.append(str(parked))
                changed = True
                moved += 1
                continue
            if not path.is_file():
                twin = path.parent / HELD_DIR / path.name
                if twin.is_file():
                    try:
                        new.append(str(twin.resolve()))
                    except OSError:
                        new.append(str(twin))
                    changed = True
                    continue
            if path.is_file():
                try:
                    new.append(str(path.resolve()))
                except OSError:
                    new.append(str(path))
            else:
                new.append(raw)
        deduped: list[str] = []
        for p in new:
            if p not in deduped:
                deduped.append(p)
        if deduped != zips:
            changed = True
        if changed:
            _saveZipList(marker, deduped)
    return moved


def hasAppliedZipRecord(installRoot: Path) -> bool:
    for marker in _markerFiles(installRoot):
        if _loadZipList(marker):
            return True
    return False


def zipIsRecorded(installRoot: Path, zipPath: Path) -> bool:
    try:
        text = str(Path(zipPath).resolve())
    except OSError:
        text = str(zipPath)
    for marker in _markerFiles(installRoot):
        if text in _loadZipList(marker):
            return True
    return False


def pickUpdateZip(installRoot: Path, projectFiles: Path) -> Path | None:
    """
    A Windows launcher (Data Doctor.exe) applies DataDoctor-Windows-*.zip when
    one is waiting, so the exe and icon update with the code.
    A 3.0.x install that still has no python-embed does the same.
    Otherwise prefer DataDoctor-Python-*.zip.
    """
    zips: list[Path] = []
    for d in allUpdatesDirs(installRoot):
        zips.extend(p for p in d.glob("*.zip") if p.is_file())
    if not zips:
        return None
    newest = lambda xs: max(xs, key=lambda p: p.stat().st_mtime)
    embedOk = (projectFiles / "python-embed" / "pythonw.exe").is_file()
    windowsExe = (installRoot / "Data Doctor.exe").is_file()
    windowsZips = [p for p in zips if "windows" in p.name.lower()]
    pythonZips = [p for p in zips if "python" in p.name.lower()]
    if (windowsExe or not embedOk) and windowsZips:
        return newest(windowsZips)
    if pythonZips:
        return newest(pythonZips)
    return newest(zips)


def pathIsInside(dest: Path, target: Path) -> bool:
    destReal = os.path.normcase(str(dest.resolve())) + os.sep
    t = os.path.normcase(str(target.resolve()))
    return t == destReal[:-1] or t.startswith(destReal)


def interpreterInside(folder: Path, exe: str | None = None) -> bool:
    """True when this process's Python lives inside folder."""
    if exe is None:
        exe = sys.executable or ""
    if not exe or not folder.exists():
        return False
    try:
        return pathIsInside(folder, Path(exe))
    except Exception:
        return False


def embedAbiTag(embed: Path) -> str:
    """python314.dll -> '314'. Empty when the folder has no embed DLL."""
    if not embed.is_dir():
        return ""
    tags = []
    for path in embed.glob("python3*.dll"):
        stem = path.stem.lower()
        if stem.startswith("python3") and stem[6:].isdigit():
            tags.append(stem[6:])
    if not tags:
        return ""
    return sorted(tags)[-1]


def embedInterpreterReady(embed: Path) -> bool:
    return (embed / "pythonw.exe").is_file() or (embed / "python.exe").is_file()


def embedAlreadyCurrent(srcEmbed: Path, destEmbed: Path) -> bool:
    """
    True when dest already has this Python.

    A normal update keeps that interpreter. A different python3XX.dll, or a
    dest with no interpreter, still needs the copy from the package.
    """
    if not embedInterpreterReady(destEmbed):
        return False
    srcTag = embedAbiTag(srcEmbed)
    destTag = embedAbiTag(destEmbed)
    if srcTag and destTag:
        return srcTag == destTag
    if srcTag and not destTag:
        return False
    return True


def stagePythonEmbed(srcEmbed: Path, destEmbed: Path, inUse: bool | None = None) -> Path:
    """
    Copy bundled python-embed into place.

    When this updater is running from destEmbed, copy to python-embed.next
    instead of deleting the live tree. The next Data Doctor launch finishes
    the swap after the user restarts.
    """
    if inUse is None:
        inUse = interpreterInside(destEmbed)
    destEmbed.parent.mkdir(parents=True, exist_ok=True)
    target = destEmbed.with_name("python-embed.next") if inUse else destEmbed
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(srcEmbed, target)
    enableEmbedSite(target)
    if inUse:
        print(f"Staged {target.parent.name}/{target.name}/ (live python-embed is in use)")
    else:
        print(f"Installed {destEmbed.parent.name}/python-embed/")
    return target


def stageEmbedIfNeeded(srcEmbed: Path, destEmbed: Path, inUse: bool | None = None) -> Path:
    """Keep an installed python-embed when the package is the same Python."""
    if inUse is None:
        inUse = interpreterInside(destEmbed)
    if embedAlreadyCurrent(srcEmbed, destEmbed):
        tag = embedAbiTag(destEmbed) or "the installed build"
        print(f"python-embed is already Python {tag} — leaving it in place")
        nxt = destEmbed.with_name("python-embed.next")
        if nxt.is_dir() and not inUse and not (destEmbed.parent.parent / "applyUpdate.cmd.new").is_file():
            try:
                shutil.rmtree(nxt)
                print("Removed staged python-embed.next (installed Python already matches)")
            except Exception as e:
                print(f"WARN: could not remove python-embed.next/: {e}", file=sys.stderr)
        return destEmbed
    return stagePythonEmbed(srcEmbed, destEmbed, inUse=inUse)


def cmdWriteTarget(installRoot: Path, stageBesideLive: bool | None = None) -> Path:
    """Write applyUpdate.cmd.new while cmd.exe is still running the live cmd."""
    live = installRoot / "applyUpdate.cmd"
    if stageBesideLive is None:
        stageBesideLive = sys.platform.startswith("win")
    if live.is_file() and stageBesideLive:
        return live.with_name("applyUpdate.cmd.new")
    return live


def removeAbandonedEmbedNext(projectFiles: Path) -> None:
    """Drop python-embed.next left by an update that did not finish swapping."""
    nxt = projectFiles / "python-embed.next"
    live = projectFiles / "python-embed"
    if not nxt.is_dir() or interpreterInside(live):
        return
    # The app still needs this folder when the new launcher command is staged.
    if (projectFiles.parent / "applyUpdate.cmd.new").is_file():
        return
    try:
        shutil.rmtree(nxt)
        print("Removed leftover python-embed.next/")
    except Exception as e:
        print(f"WARN: could not remove python-embed.next/: {e}", file=sys.stderr)


def swapEmbedNext(projectFiles: Path) -> bool:
    """Move python-embed.next onto python-embed when this process is not using it."""
    nxt = projectFiles / "python-embed.next"
    live = projectFiles / "python-embed"
    if not (nxt / "python.exe").is_file():
        return False
    if interpreterInside(live) or interpreterInside(nxt):
        print("python-embed.next stays until this Python exits")
        return False
    try:
        if live.exists():
            shutil.rmtree(live)
        nxt.rename(live)
        print("Swapped python-embed.next into python-embed")
        return True
    except Exception as e:
        print(f"WARN: could not swap python-embed.next: {e}", file=sys.stderr)
        return False


def cleanupPackagedLeftovers(installRoot: Path) -> None:
    """
    Remove files a package used to drop in the wrong place.

    python-standalone is a Mac packaging cache and does not belong in a
    Windows install. applyUpdate.py belongs in pythonFiles/scripts/.
    The Mac cache under launcher/python-standalone is a different folder
    and is not touched.
    """
    rootApply = installRoot / "applyUpdate.py"
    scriptsApply = installRoot / WIN_CODE_DIR / "scripts" / "applyUpdate.py"
    legacyApply = installRoot / LEGACY_CODE_DIR / "scripts" / "applyUpdate.py"
    if rootApply.is_file() and (scriptsApply.is_file() or legacyApply.is_file()):
        try:
            if rootApply.resolve() == Path(__file__).resolve():
                print("Root applyUpdate.py is running — it will be removed after this process exits")
            else:
                rootApply.unlink()
                print("Removed leftover applyUpdate.py from the install root")
        except Exception as e:
            print(f"WARN: could not remove root applyUpdate.py: {e}", file=sys.stderr)
    standalone = installRoot / "python-standalone"
    if standalone.is_dir():
        try:
            shutil.rmtree(standalone)
            print("Removed leftover python-standalone/")
        except Exception as e:
            print(f"WARN: could not remove python-standalone/: {e}", file=sys.stderr)
    for leftover in installRoot.glob("python-*-embed-*.zip"):
        try:
            if leftover.is_file():
                leftover.unlink()
                print(f"Removed leftover {leftover.name}")
        except Exception as e:
            print(f"WARN: could not remove {leftover.name}: {e}", file=sys.stderr)


APPLY_REEXEC_ENV = "DD_APPLY_REEXEC"


def bundledApplyScript(zipPath: Path) -> bytes | None:
    """applyUpdate.py stored in a DataDoctor zip, if the zip has one."""
    try:
        with zipfile.ZipFile(zipPath) as zf:
            scripts = []
            plain = []
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or zipMemberUnsafe(name):
                    continue
                if name.endswith("scripts/applyUpdate.py"):
                    scripts.append(name)
                elif name.endswith("applyUpdate.py"):
                    plain.append(name)
            picks = scripts or plain
            if not picks:
                return None
            pick = sorted(picks, key=lambda n: (n.count("/"), len(n)))[0]
            return zf.read(pick)
    except Exception as e:
        print(f"WARN: could not read applyUpdate.py from {zipPath.name}: {e}", file=sys.stderr)
        return None


def shouldReexecApplyScript(zipPath: Path, currentPath: Path | None = None) -> bool:
    """
    True when the zip ships a different applyUpdate.py than the one running.

    applyUpdate.cmd starts the script already installed, so a new zip would
    otherwise finish the run with the previous build.
    """
    if os.environ.get(APPLY_REEXEC_ENV) == "1":
        return False
    fresh = bundledApplyScript(zipPath)
    if not fresh:
        return False
    path = Path(currentPath) if currentPath is not None else Path(__file__)
    try:
        current = path.read_bytes()
    except Exception:
        return True
    return fresh != current


def _argPresent(argv: list[str], name: str) -> bool:
    for item in argv:
        if item == name or str(item).startswith(name + "="):
            return True
    return False


def reexecArgv(argv: list[str], installRoot: Path, zipPath: Path) -> list[str]:
    """Pass the folder and zip already chosen so the temp copy does not guess."""
    extra = []
    if not _argPresent(argv, "--install-root"):
        extra.extend(["--install-root", str(installRoot)])
    if not _argPresent(argv, "--zip"):
        extra.extend(["--zip", str(zipPath)])
    return [*argv, *extra]


def reexecZipApplyScript(zipPath: Path, installRoot: Path) -> None:
    """Replace this process with the applyUpdate.py inside the zip."""
    if not shouldReexecApplyScript(zipPath):
        return
    fresh = bundledApplyScript(zipPath)
    if not fresh:
        return
    fd, name = tempfile.mkstemp(prefix="dd-apply-", suffix=".py")
    os.close(fd)
    path = Path(name)
    path.write_bytes(fresh)
    env = os.environ.copy()
    env[APPLY_REEXEC_ENV] = "1"
    env[APPLY_ROOT_ENV] = str(installRoot)
    forwarded = reexecArgv(list(sys.argv[1:]), installRoot, zipPath)
    print(f"Running applyUpdate.py from {zipPath.name}")
    try:
        rc = subprocess.call([sys.executable, str(path), *forwarded], env=env)
    finally:
        try:
            path.unlink()
        except Exception:
            pass
    raise SystemExit(rc)


def renameStagedCmd(installRoot: Path) -> bool:
    """Replace applyUpdate.cmd with applyUpdate.cmd.new when the new file is staged."""
    staged = installRoot / "applyUpdate.cmd.new"
    live = installRoot / "applyUpdate.cmd"
    if not staged.is_file():
        return False
    try:
        if live.is_file():
            live.unlink()
        staged.rename(live)
        print("Renamed applyUpdate.cmd.new → applyUpdate.cmd")
        return True
    except Exception as e:
        print(f"WARN: could not rename applyUpdate.cmd.new: {e}", file=sys.stderr)
        return False


def finishStaged(installRoot: Path) -> int:
    """
    Finish files a Windows update staged because they were in use.

    No zip. Does not copy python-embed again. Swaps python-embed.next only
    when this process is not running from it, puts the new launcher command
    in place, removes packaged leftovers, and starts Data Doctor.
    """
    for name in CODE_DIR_NAMES:
        swapEmbedNext(installRoot / name)
    renameStagedCmd(installRoot)
    cleanupPackagedLeftovers(installRoot)
    leftoverSwap = installRoot / "finishEmbedSwap.cmd"
    if leftoverSwap.is_file():
        try:
            leftoverSwap.unlink()
            print("Removed leftover finishEmbedSwap.cmd")
        except Exception as e:
            print(f"WARN: could not remove finishEmbedSwap.cmd: {e}", file=sys.stderr)
    launchDataDoctorIfIdle(installRoot, assumeIdle=True)
    return 0


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


_EMBED_SITECUSTOMIZE = """\
# Data Doctor: pythonFiles (parent of this python-embed dir) must be on sys.path.
# python*._pth does not add the script directory, so `import core` would fail.
import os
import sys
_embed = os.path.dirname(os.path.abspath(__file__))
_app = os.path.dirname(_embed)
if _app and _app not in sys.path:
    sys.path.insert(0, _app)
"""


def enableEmbedSite(embedDir: Path) -> None:
    pthFiles = list(embedDir.glob("python*._pth"))
    if not pthFiles:
        return
    pth = pthFiles[0]
    text = pth.read_text(encoding="utf-8")
    lines = []
    sawSite = False
    sawLib = False
    sawParent = False
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
        if stripped in ("..", "../", "..\\"):
            if not sawParent:
                lines.append("..")
                sawParent = True
            continue
        lines.append(line)
    if not sawLib or not sawParent:
        new = []
        for line in lines:
            new.append(line)
            if line.strip() == ".":
                if not sawParent:
                    new.append("..")
                    sawParent = True
                if not sawLib:
                    new.append("Lib\\site-packages")
                    sawLib = True
        lines = new
    if not sawParent:
        lines.append("..")
    if not sawLib:
        lines.append("Lib\\site-packages")
    if not sawSite:
        lines.append("import site")
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (embedDir / "sitecustomize.py").write_text(_EMBED_SITECUSTOMIZE, encoding="utf-8")


def ensurePip(py: str, projectFiles: Path, embedDir: Path | None = None) -> None:
    """Bootstrap pip into python-embed if `python -m pip` is missing."""
    embedDir = embedDir or (projectFiles / "python-embed")
    probe = subprocess.call(
        [py, "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe == 0:
        return
    getPip = embedDir / "get-pip.py"
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
    enableEmbedSite(embedDir)


def ensurePython(projectFiles: Path) -> str:
    """Prefer bundled python-embed; fall back to .venv / this interpreter."""
    nextDir = projectFiles / "python-embed.next"
    liveDir = projectFiles / "python-embed"
    if (nextDir / "python.exe").is_file() and interpreterInside(liveDir):
        enableEmbedSite(nextDir)
        py = str(nextDir / "python.exe")
        ensurePip(py, projectFiles, nextDir)
        return py
    embedDir = liveDir
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
    for name in CODE_DIR_NAMES:
        pf = payload / name
        if (pf / "python-embed" / "pythonw.exe").is_file():
            return True
        if (
            ((pf / WIN_APP_ENTRY).is_file() or (pf / "DataDoctor.pyw").is_file())
            and (payload / "applyUpdate.cmd").is_file()
        ):
            return True
    return False


def sameFileBytes(src: Path, dest: Path) -> bool:
    try:
        if not src.is_file() or not dest.is_file():
            return False
        if src.stat().st_size != dest.stat().st_size:
            return False
        return src.read_bytes() == dest.read_bytes()
    except OSError:
        return False


def copyFileIfPresent(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    if dest.is_file() and sameFileBytes(src, dest):
        print(f"{dest.name} already matches — leaving it")
        return True
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


def removeLeftoverDataDoctorIco(installRoot: Path, projectFiles: Path) -> None:
    """Drop the old DataDoctor.ico name; the icon is Data Doctor.ico now."""
    places = [
        installRoot / "DataDoctor.ico",
        projectFiles / "DataDoctor.ico",
        projectFiles / "ui" / "DataDoctor.ico",
        projectFiles / "ui" / "icons" / "DataDoctor.ico",
    ]
    for p in places:
        try:
            if p.is_file():
                p.unlink()
                print(f"Removed leftover {p.relative_to(installRoot)}")
        except Exception as e:
            print(f"WARN: could not remove {p}: {e}", file=sys.stderr)


def pythonCanImport(py: str, module: str) -> bool:
    try:
        rc = subprocess.call(
            [py, "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return rc == 0
    except Exception:
        return False


def applyWindowsLauncherBits(payload: Path, installRoot: Path) -> Path | None:
    """Replace Data Doctor.exe and the icon from a Windows zip.

    applyUpdate.cmd is written later (staged beside the live cmd). The live
    python-embed is not deleted while this process is running from it.
    """
    copyFileIfPresent(payload / "Data Doctor.exe", installRoot / "Data Doctor.exe")
    copyFileIfPresent(payload / "README.txt", installRoot / "README.txt")
    copyFileIfPresent(payload / "UPDATE.txt", installRoot / "UPDATE.txt")
    copyFileIfPresent(payload / "Data Doctor.ico", installRoot / "Data Doctor.ico")
    srcEmbed = None
    for name in CODE_DIR_NAMES:
        cand = payload / name / "python-embed"
        if cand.is_dir() and (cand / "pythonw.exe").is_file():
            srcEmbed = cand
            break
    if srcEmbed is None:
        return None
    destEmbed = installRoot / WIN_CODE_DIR / "python-embed"
    return stageEmbedIfNeeded(srcEmbed, destEmbed)


def migrateLegacyProjectFiles(installRoot: Path, dest: Path) -> None:
    """Copy live bunker.db / certs / extra quickLooks from 3.0.x Project Files/."""
    legacy = installRoot / LEGACY_CODE_DIR
    if not legacy.is_dir():
        return
    try:
        if legacy.resolve() == dest.resolve():
            return
    except Exception:
        pass
    liveBunker = legacy / "core" / "bunker.db"
    destBunker = dest / "core" / "bunker.db"
    if liveBunker.is_file():
        destBunker.parent.mkdir(parents=True, exist_ok=True)
        if destBunker.is_file():
            # Keep the live dictionary: it wins over the packaged copy in dest.
            bak = destBunker.with_suffix(".db.fromzip")
            try:
                destBunker.replace(bak)
            except Exception:
                pass
        shutil.copy2(liveBunker, destBunker)
        print(f"Migrated live bunker.db → {WIN_CODE_DIR}/core/")
    liveCerts = legacy / "certs"
    if liveCerts.is_dir():
        copyTreeMerge(liveCerts, dest / "certs")
        print(f"Migrated certs/ → {WIN_CODE_DIR}/certs/")
    liveQl = legacy / "quickLook"
    if liveQl.is_dir():
        copyTreeMerge(liveQl, dest / "quickLook")
        print(f"Merged quickLook/ from {LEGACY_CODE_DIR}/")
    removeLegacyProjectFiles(installRoot, dest)


def runningFromLegacyProjectFiles(installRoot: Path) -> bool:
    exe = (sys.executable or "").replace("\\", "/").lower()
    root = str(installRoot).replace("\\", "/").lower()
    return "project files" in exe and root in exe


def removeLegacyProjectFiles(installRoot: Path, dest: Path) -> None:
    """Delete leftover Project Files/ once pythonFiles/ is the live tree."""
    legacy = installRoot / LEGACY_CODE_DIR
    if not legacy.is_dir() or not dest.is_dir():
        return
    try:
        if legacy.resolve() == dest.resolve():
            return
    except Exception:
        pass
    if runningFromLegacyProjectFiles(installRoot):
        leftover = installRoot / "Project Files.old"
        try:
            if leftover.exists():
                shutil.rmtree(leftover, ignore_errors=True)
            legacy.rename(leftover)
            print("Renamed Project Files/ → Project Files.old (in use; remove on next start)")
        except Exception as e:
            print(f"WARN: could not remove Project Files/ while in use: {e}", file=sys.stderr)
        return
    try:
        shutil.rmtree(legacy)
        print("Removed leftover Project Files/")
    except Exception as e:
        print(f"WARN: could not remove Project Files/: {e}", file=sys.stderr)


def cleanupStaleLegacyDirs(installRoot: Path) -> None:
    """Next start from python-embed: delete Project Files leftover if still present."""
    if runningFromLegacyProjectFiles(installRoot):
        return
    live = installRoot / WIN_CODE_DIR
    if not live.is_dir():
        return
    for name in (LEGACY_CODE_DIR, "Project Files.old"):
        p = installRoot / name
        if p.is_dir():
            try:
                shutil.rmtree(p)
                print(f"Removed leftover {name}/")
            except Exception as e:
                print(f"WARN: could not remove {name}/: {e}", file=sys.stderr)


def migrateLegacyUpdatesFolder(installRoot: Path) -> None:
    """Merge Update/ / Updates/ into updates/, then remove the old folder."""
    dest = installRoot / UPDATES_DIR
    dest.mkdir(parents=True, exist_ok=True)
    destKey = os.path.normcase(str(dest.resolve())) if dest.exists() else ""
    for name in ("Update", "Updates", "update", "UPDATES"):
        src = installRoot / name
        if not src.is_dir():
            continue
        try:
            srcKey = os.path.normcase(str(src.resolve()))
        except Exception:
            srcKey = os.path.normcase(str(src))
        if destKey and srcKey == destKey:
            # Same folder on a case-insensitive volume (Update vs updates).
            if src.name != UPDATES_DIR:
                tmp = installRoot / "_updates_rename_tmp"
                try:
                    if tmp.exists():
                        shutil.rmtree(tmp, ignore_errors=True)
                    src.rename(tmp)
                    tmp.rename(dest)
                except Exception as e:
                    print(f"WARN: could not rename {name}/ to {UPDATES_DIR}/: {e}", file=sys.stderr)
            continue
        for item in list(src.iterdir()):
            target = dest / item.name
            try:
                if target.exists():
                    if item.is_file():
                        item.unlink()
                    continue
                shutil.move(str(item), str(target))
            except Exception:
                pass
        try:
            shutil.rmtree(src)
        except Exception as e:
            print(f"WARN: could not remove {name}/: {e}", file=sys.stderr)


def dataDoctorExeRunning() -> bool:
    """True if a Data Doctor.exe process is already alive (launcher waiting on us)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Data Doctor.exe", "/NH"],
            text=True,
            errors="replace",
            timeout=10,
        )
        return "Data Doctor.exe" in out
    except Exception:
        return False


def launchDataDoctorIfIdle(installRoot: Path, assumeIdle: bool = False) -> None:
    """
    The Windows launcher starts applyUpdate.cmd and exits so the .exe can be
    replaced. This process starts Data Doctor.exe (or the macOS .command)
    when the zip is done. Skip if the old WaitForExit launcher is still alive.
    """
    exe = installRoot / "Data Doctor.exe"
    mac = installRoot / "Data Doctor.command"
    target = None
    args = None
    if exe.is_file() and (sys.platform.startswith("win") or not mac.is_file()):
        if not assumeIdle and dataDoctorExeRunning():
            print("Data Doctor.exe is already running — not starting another copy")
            appendAppLog("INFO", "exe already running — not starting another copy")
            return
        target = exe
        args = [str(exe)]
    elif mac.is_file():
        target = mac
        args = ["open", str(mac)] if sys.platform == "darwin" else ["bash", str(mac)]
    if target is None:
        return
    try:
        kwargs = {
            "cwd": str(installRoot),
            "close_fds": True,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(args, **kwargs)
        print(f"Starting {target.name}")
        appendAppLog("INFO", f"starting {target.name}")
    except Exception as e:
        print(f"WARN: could not start {target.name}: {e}", file=sys.stderr)
        appendAppLog("ERROR", f"could not start {target.name}: {e}")


def applyCmdBody() -> str:
    """The launcher command every Windows install should end up with."""
    return "\r\n".join([
        "@echo off",
        "REM Apply newest zip in updates\\ (code + bunker merge + pip into python-embed)",
        "setlocal",
        'cd /d "%~dp0"',
        'if exist "finishEmbedSwap.cmd" del /f /q "finishEmbedSwap.cmd"',
        'set "PY="',
        'if exist "pythonFiles\\python-embed\\python.exe" set "PY=pythonFiles\\python-embed\\python.exe"',
        'if not defined PY if exist "Project Files\\python-embed\\python.exe" set "PY=Project Files\\python-embed\\python.exe"',
        'if not defined PY if exist "pythonFiles\\.venv\\Scripts\\python.exe" set "PY=pythonFiles\\.venv\\Scripts\\python.exe"',
        'if not defined PY if exist "Project Files\\.venv\\Scripts\\python.exe" set "PY=Project Files\\.venv\\Scripts\\python.exe"',
        'if not defined PY set "PY=python"',
        'set "SCRIPT=%~dp0pythonFiles\\scripts\\applyUpdate.py"',
        'if not exist "%SCRIPT%" set "SCRIPT=%~dp0Project Files\\scripts\\applyUpdate.py"',
        'if not exist "%SCRIPT%" set "SCRIPT=%~dp0applyUpdate.py"',
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


def cmdTextSame(a: str, b: str) -> bool:
    """
    True when two command files are the same lines.

    Older writers passed a CRLF string to write_text(newline='\\r\\n'),
    which stored CR CR LF. Those blank lines are not a command change.
    """
    def lines(text):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        kept = [line.strip() for line in text.split("\n")]
        return [line for line in kept if line]
    return lines(a) == lines(b)


def writeApplyUpdateCmd(installRoot: Path, stageBesideLive: bool | None = None) -> None:
    """
    Point applyUpdate.cmd at python-embed when present.

    A running cmd.exe cannot be rewritten, so a real change is staged as
    applyUpdate.cmd.new and finished on the next restart. The same text is
    left alone, including a staged copy of that same text.
    """
    body = applyCmdBody()
    live = installRoot / "applyUpdate.cmd"
    staged = installRoot / "applyUpdate.cmd.new"
    if live.is_file():
        try:
            current = live.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current is not None and cmdTextSame(current, body):
            if staged.is_file():
                try:
                    if cmdTextSame(staged.read_text(encoding="utf-8"), body):
                        staged.unlink()
                        print("Removed applyUpdate.cmd.new (launcher command already matches)")
                except OSError as e:
                    print(f"WARN: could not remove applyUpdate.cmd.new: {e}", file=sys.stderr)
            print("applyUpdate.cmd already matches — leaving it")
            return
    cmd = cmdWriteTarget(installRoot, stageBesideLive=stageBesideLive)
    # body already uses CRLF. newline="" keeps those bytes (newline="\\r\\n"
    # would turn each CR LF into CR CR LF).
    cmd.write_text(body, encoding="utf-8", newline="")
    if cmd.name.endswith(".new"):
        print("Staged applyUpdate.cmd.new (live applyUpdate.cmd is still running)")
    else:
        print("Updated applyUpdate.cmd")


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
    Copy DataDoctor.py[.pyw] / app.pyw from the zip into the live code dir.

    Windows generic launcher starts pythonFiles\\app.pyw. Python zips still
    ship DataDoctor.py; we rename on Windows. macOS/source keep DataDoctor.py.
    """
    src = payload / "DataDoctor.py"
    if not src.is_file():
        src = payload / WIN_APP_ENTRY
    if not src.is_file():
        src = payload / "DataDoctor.pyw"
    if not src.is_file():
        return None

    windows = (
        sys.platform.startswith("win")
        or (projectFiles.parent / "Data Doctor.exe").is_file()
        or (projectFiles / WIN_APP_ENTRY).is_file()
    )
    if windows:
        destName = WIN_APP_ENTRY
    elif (projectFiles / "DataDoctor.pyw").is_file():
        destName = "DataDoctor.pyw"
    else:
        destName = "DataDoctor.py"
    shutil.copy2(src, projectFiles / destName)
    if destName == WIN_APP_ENTRY:
        for leftover in ("DataDoctor.py", "DataDoctor.pyw"):
            p = projectFiles / leftover
            if p.is_file():
                p.unlink()
    elif destName == "DataDoctor.pyw":
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
    if not live.is_file():
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packagedBunker, live)
        print(f"No existing bunker.db — installed packaged dictionary → {live}")
        return 0

    if not script.is_file():
        print("WARN: updateBunker.py not found — live bunker.db left unchanged")
        return 0

    cmd = [
        py, str(script),
        "--packaged", str(packagedBunker),
        "--user", str(live),
    ]
    # Linux apply has no console, so the two y/n prompts cannot be answered.
    # Leave existing common names and data types alone (same as answering N).
    # New rows still take the packaged names and types.
    if sys.platform.startswith("linux"):
        cmd.extend(["--no-update-common-names", "--no-update-datatypes"])
        print(
            "Linux update has no console for the dictionary questions — "
            "answering N to Common Names and Data Types on existing rows."
        )
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def apply(zipPath: Path, installRoot: Path, keepExtract: bool = False) -> int:
    if not zipPath.is_file():
        print(f"ERROR: zip not found: {zipPath}", file=sys.stderr)
        appendAppLog("ERROR", f"zip not found: {zipPath}")
        return 1

    migrateLegacyUpdatesFolder(installRoot)
    cleanupStaleLegacyDirs(installRoot)
    removeAbandonedEmbedNext(installRoot / WIN_CODE_DIR)
    leftoverSwap = installRoot / "finishEmbedSwap.cmd"
    if leftoverSwap.is_file():
        try:
            leftoverSwap.unlink()
            print("Removed leftover finishEmbedSwap.cmd")
        except Exception as e:
            print(f"WARN: could not remove finishEmbedSwap.cmd: {e}", file=sys.stderr)

    updateDir = resolveUpdatesDir(installRoot, create=True)
    extractDir = Path(tempfile.mkdtemp(prefix="dd-update-", dir=str(updateDir)))
    print(f"Extracting {zipPath.name} → {extractDir}")

    try:
        with zipfile.ZipFile(zipPath, "r") as zf:
            safeExtractZip(zf, extractDir)

        # Payload may be at extract root or nested one level
        payload = extractDir
        if (
            not (payload / "DataDoctor.py").is_file()
            and not (payload / "core").is_dir()
            and not (payload / WIN_CODE_DIR).is_dir()
            and not (payload / LEGACY_CODE_DIR).is_dir()
        ):
            if not isWindowsFullPayload(payload):
                kids = [p for p in extractDir.iterdir() if p.is_dir()]
                if len(kids) == 1:
                    payload = kids[0]

        windowsFull = isWindowsFullPayload(payload)
        codeRoot = payload
        if windowsFull:
            print("Windows full package: updating the launcher")
            applyWindowsLauncherBits(payload, installRoot)
            projectFiles = installRoot / WIN_CODE_DIR
            projectFiles.mkdir(parents=True, exist_ok=True)
            migrateLegacyProjectFiles(installRoot, projectFiles)
            nested = payloadCodeDir(payload)
            if nested != payload:
                codeRoot = nested
        else:
            projectFiles = resolveCodeDir(installRoot)
            if not projectFiles.is_dir():
                print(
                    f"ERROR: {WIN_CODE_DIR}/ or {LEGACY_CODE_DIR}/ not found under {installRoot}",
                    file=sys.stderr,
                )
                return 1

        # App entry: Python zip ships DataDoctor.py. Windows launcher starts
        # pythonFiles/app.pyw. Write that name on Windows and drop leftovers.
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
            print(f"Created empty {projectFiles.name}/certs/ (not overwritten on later updates)")
        else:
            print(f"Left {projectFiles.name}/certs/ unchanged")

        py = ensurePython(projectFiles)
        print(f"Using Python: {py}")
        appendAppLog("INFO", f"using Python {py} for {zipPath.name}")

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
            appendAppLog("WARN", f"pip install exited {rc}")
        else:
            appendAppLog("INFO", "pip install finished")

        removeLeftoverDataDoctorIco(installRoot, projectFiles)

        if (projectFiles / "python-embed" / "pythonw.exe").is_file() and not pythonCanImport(py, "PyQt6"):
            print(
                "ERROR: PyQt6 is not importable. First-run pip needs internet. "
                "Not starting Data Doctor.",
                file=sys.stderr,
            )
            appendAppLog("ERROR", "PyQt6 is not importable after pip; not starting")
            return 1

        # Move the zip out of the top of updates/ so Data Doctor.exe does not
        # start applyUpdate.cmd again. The app deletes it when the install
        # is finished.
        try:
            rememberAppliedZip(installRoot, zipPath)
        except Exception as e:
            print(f"WARN: could not record applied zip: {e}", file=sys.stderr)

        print("Update complete.")
        appendAppLog("INFO", f"update complete ({zipPath.name})")

        # User already confirmed the download. If this was a Python-zip hop
        # and python-embed is still missing, apply (or fetch) the Windows
        # package in the same run so they are not asked to do a second hop.
        if not getattr(apply, "_windowsHop", False):
            embedOk = (projectFiles / "python-embed" / "pythonw.exe").is_file()
            if (
                isWindowsInstall(installRoot)
                and not embedOk
                and not windowsFull
            ):
                apply._windowsHop = True
                nxt = pickUpdateZip(installRoot, projectFiles)
                if nxt is None or "windows" not in nxt.name.lower():
                    nxt = maybeDownloadWindowsZip(installRoot)
                if nxt is not None and nxt.is_file() and "windows" in nxt.name.lower():
                    print(f"Launcher still needs python-embed — applying {nxt.name}")
                    appendAppLog("INFO", f"chaining Windows zip {nxt.name}")
                    return apply(nxt, installRoot, keepExtract=keepExtract)

        cleanupPackagedLeftovers(installRoot)
        launchDataDoctorIfIdle(installRoot)
        return 0
    finally:
        if not keepExtract and extractDir.exists():
            shutil.rmtree(extractDir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply DataDoctor Python zip from updates/")
    parser.add_argument(
        "--zip",
        default=None,
        help="Path to Python zip (default: newest *.zip in updates/)",
    )
    parser.add_argument(
        "--install-root",
        dest="installRoot",
        default=None,
        help="Install root (folder that contains pythonFiles/ or Project Files/). Default: auto-detect",
    )
    parser.add_argument(
        "--keep-extract",
        dest="keepExtract",
        action="store_true",
        help="Keep extracted files under updates/ for debugging",
    )
    parser.add_argument(
        "--finish-staged",
        dest="finishStaged",
        action="store_true",
        help="Finish staged launcher files. Does not apply a zip or copy python-embed",
    )
    args = parser.parse_args()

    if args.installRoot:
        installRoot = Path(args.installRoot).expanduser().resolve()
    else:
        # Script may live at install root, pythonFiles/scripts/, or a temp reexec copy.
        installRoot = locateInstallRoot(Path(__file__))

    removeStrayTempUpdates(Path(__file__))
    print(f"Install root: {installRoot}")
    appendAppLog("INFO", f"install root {installRoot}")
    if not args.installRoot and not installRootConfirmed(installRoot):
        print(
            f"ERROR: Data Doctor install was not found (got {installRoot}).\n"
            "  Run applyUpdate.cmd from the install folder, or pass --install-root.",
            file=sys.stderr,
        )
        appendAppLog("ERROR", f"install not found ({installRoot})")
        return 1
    if args.finishStaged:
        return finishStaged(installRoot)

    moved = parkRecordedZips(installRoot)
    if moved:
        print(f"Set aside {moved} applied update zip(s)")
        appendAppLog("INFO", f"parked {moved} applied update zip(s)")

    if args.zip:
        zipPath = Path(args.zip).expanduser()
        try:
            zipPath = zipPath.resolve()
        except OSError:
            pass
        if not zipPath.is_file():
            if hasAppliedZipRecord(installRoot):
                print("Update zip already applied; starting Data Doctor.")
                appendAppLog("INFO", "applied zip already parked; starting Data Doctor")
                launchDataDoctorIfIdle(installRoot)
                return 0
            print(f"ERROR: Zip not found: {zipPath}", file=sys.stderr)
            appendAppLog("ERROR", f"zip not found ({zipPath})")
            return 1
    else:
        projectFiles = resolveCodeDir(installRoot)
        zipPath = pickUpdateZip(installRoot, projectFiles)
        if zipPath is None:
            if hasAppliedZipRecord(installRoot):
                print("Applied update is set aside; starting Data Doctor.")
                appendAppLog("INFO", "no top-level zip; starting Data Doctor")
                launchDataDoctorIfIdle(installRoot)
                return 0
            updateDir = resolveUpdatesDir(installRoot, create=True)
            print(
                f"ERROR: No *.zip found in {updateDir}\n"
                "  Place DataDoctor-Python-*.zip (code) or DataDoctor-Windows-*.zip "
                "(launcher + python-embed) there, or pass --zip path",
                file=sys.stderr,
            )
            return 1

    if zipIsRecorded(installRoot, zipPath):
        rememberAppliedZip(installRoot, zipPath)
        print("Update zip already applied; starting Data Doctor.")
        appendAppLog("INFO", f"skipping already applied {zipPath.name}")
        launchDataDoctorIfIdle(installRoot)
        return 0

    print(f"Update zip: {zipPath}")
    reexecZipApplyScript(zipPath, installRoot)
    return apply(zipPath, installRoot, keepExtract=args.keepExtract)


if __name__ == "__main__":
    sys.exit(main())
