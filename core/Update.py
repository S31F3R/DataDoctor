# Update.py
# Check GitHub Releases, download payload into updates/, help apply (launcher or AppImage).
#
# Stable channel → latest non-prerelease on GitHub.
# Beta channel   → latest release including GitHub "pre-release" and/or -rc./-beta. tags.
#
# Works before any release is published: check fails quietly (no dialog spam).

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from core import Config, Logic, Utils, Version

# User-Agent required by GitHub API
_UA = f"DataDoctor/{Version.displayVersion()} (+https://github.com/{Version.GITHUB_REPO})"
_API = f"https://api.github.com/repos/{Version.GITHUB_REPO}/releases"
_TIMEOUT = 20
_GITHUB_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
})


def _httpsHostAllowed(url: str, extraHosts=()) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme != "https":
        return False
    host = (p.hostname or "").lower()
    if host in _GITHUB_HOSTS or host in extraHosts:
        return True
    return host.endswith(".githubusercontent.com")


def _safeDownloadName(name: str) -> str:
    base = Path(str(name or "download.bin")).name
    if not base or base in (".", ".."):
        return "download.bin"
    return base


def _verifyDigest(path: Path, digest: str | None) -> bool:
    """If GitHub sent sha256:…, require a match. Unknown/missing digest is allowed."""
    if not digest:
        return True
    kind, _, expect = str(digest).partition(":")
    if kind.lower() != "sha256" or not expect:
        return True
    expect = expect.strip().lower()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != expect:
        Logic.logMessage("ERROR", f"Update digest mismatch (got {got}, expected {expect})")
        try:
            path.unlink()
        except Exception:
            pass
        return False
    return True


def getUpdateChannel() -> str:
    """'stable' (default) or 'beta' from user.config."""
    try:
        config = Utils.loadConfig()
        ch = (config.get("updateChannel") or "stable").strip().lower()
        if ch in ("beta", "pre", "prerelease", "rc"):
            return "beta"
    except Exception:
        pass
    return "stable"


def setUpdateChannel(channel: str) -> None:
    ch = "beta" if str(channel).lower() in ("beta", "pre", "prerelease", "rc") else "stable"
    try:
        config = Utils.loadConfig()
        config["updateChannel"] = ch
        with open(Utils.getConfigPath(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        Logic.logException("Update.setUpdateChannel failed", e)


def detectInstallKind() -> str:
    """
    'appimage' | 'launcher' | 'dev'
    """
    appimage = os.environ.get("APPIMAGE") or ""
    if appimage and os.path.isfile(appimage):
        return "appimage"

    # Launcher layout: pythonFiles/app.pyw or Project Files/DataDoctor.py[w]
    try:
        appRoot = getattr(Config, "appRoot", "") or ""
        candidates = []
        if appRoot:
            candidates.append(Path(appRoot))
            candidates.append(Path(appRoot).parent)
        candidates.append(Path.cwd())
        for base in candidates:
            for folder, entries in (
                ("pythonFiles", ("app.pyw", "DataDoctor.py", "DataDoctor.pyw")),
                ("Project Files", ("DataDoctor.py", "DataDoctor.pyw", "app.pyw")),
            ):
                pf = base / folder
                if pf.is_dir() and any((pf / n).is_file() for n in entries):
                    return "launcher"
            if (base / "Data Doctor.exe").is_file() or (base / "Data Doctor.command").is_file():
                return "launcher"
    except Exception:
        pass
    return "dev"


def installRoot() -> Path | None:
    """Directory that should hold updates/ (and apply scripts for launcher)."""
    kind = detectInstallKind()
    if kind == "appimage":
        appimage = os.environ.get("APPIMAGE")
        if appimage:
            return Path(appimage).resolve().parent
        return None

    appRoot = getattr(Config, "appRoot", "") or ""
    if not appRoot:
        return Path.cwd()

    root = Path(appRoot)
    # If we're inside pythonFiles / Project Files, install root is parent
    if root.name in ("pythonFiles", "Project Files"):
        return root.parent
    if (root / "pythonFiles").is_dir() or (root / "Project Files").is_dir():
        return root
    # Dev: project root is fine for a local updates/ folder
    return root


def updateDir() -> Path | None:
    """
    Canonical drop folder is updates/.
    3.0.x Data Doctor.exe only looks in Update\\, so until python-embed
    exists we still write there.
    """
    root = installRoot()
    if root is None:
        return None
    embed = (
        (root / "pythonFiles" / "python-embed" / "pythonw.exe").is_file()
        or (root / "Project Files" / "python-embed" / "pythonw.exe").is_file()
    )
    if (root / "Data Doctor.exe").is_file() and not embed:
        for name in ("Update", "update", "updates"):
            d = root / name
            if d.is_dir():
                return d
        d = root / "Update"
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = root / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def windowsNeedsLauncherRefresh() -> bool:
    """
    True when this is a Windows launcher install without python-embed.
    3.0.x shipped a system-Python .venv; 3.1+ needs DataDoctor-Windows-*.zip.
    """
    root = installRoot()
    if root is None:
        return False
    if not (root / "Data Doctor.exe").is_file():
        return False
    embed = root / "pythonFiles" / "python-embed" / "pythonw.exe"
    if embed.is_file():
        return False
    legacy = root / "Project Files" / "python-embed" / "pythonw.exe"
    return not legacy.is_file()


_APPLY_UPDATE_CMD = "\r\n".join([
    "@echo off",
    "REM Apply newest zip in updates\\ (code + bunker merge + pip into python-embed)",
    "setlocal",
    'cd /d "%~dp0"',
    'set "PY="',
    'if exist "pythonFiles\\python-embed\\python.exe" set "PY=pythonFiles\\python-embed\\python.exe"',
    'if not defined PY if exist "Project Files\\python-embed\\python.exe" set "PY=Project Files\\python-embed\\python.exe"',
    'if not defined PY if exist "pythonFiles\\.venv\\Scripts\\python.exe" set "PY=pythonFiles\\.venv\\Scripts\\python.exe"',
    'if not defined PY if exist "Project Files\\.venv\\Scripts\\python.exe" set "PY=Project Files\\.venv\\Scripts\\python.exe"',
    'if not defined PY set "PY=python"',
    'set "SCRIPT=%~dp0pythonFiles\\scripts\\applyUpdate.py"',
    'if not exist "%SCRIPT%" set "SCRIPT=%~dp0Project Files\\scripts\\applyUpdate.py"',
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


def bootstrapWindowsApplyTools() -> None:
    """
    3.0.x applyUpdate copies core/* but not scripts/. The Python zip ships
    core/applyUpdate.py so the first hop can install a Windows-zip-capable
    updater, then the user runs applyUpdate.cmd for the launcher + embed.
    """
    if sys.platform != "win32":
        return
    try:
        coreDir = Path(__file__).resolve().parent
        projectFiles = coreDir.parent
        src = coreDir / "applyUpdate.py"
        destDir = projectFiles / "scripts"
        dest = destDir / "applyUpdate.py"
        if src.is_file():
            destDir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            try:
                src.unlink()
            except Exception:
                pass
        root = projectFiles.parent
        if (root / "Data Doctor.exe").is_file() or (root / "applyUpdate.cmd").is_file():
            cmd = root / "applyUpdate.cmd"
            cmd.write_text(_APPLY_UPDATE_CMD, encoding="utf-8", newline="\r\n")
        try:
            scriptsDir = projectFiles / "scripts"
            if str(scriptsDir) not in sys.path:
                sys.path.insert(0, str(scriptsDir))
            import applyUpdate as _au
            _au.migrateLegacyUpdatesFolder(root)
            _au.cleanupStaleLegacyDirs(root)
        except Exception:
            pass
    except Exception as e:
        Logic.logMessage("DEBUG", f"bootstrapWindowsApplyTools: {e}")


def _httpJson(url: str):
    if not _httpsHostAllowed(url):
        raise ValueError(f"refusing JSON fetch from {url}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        final = resp.geturl()
        if not _httpsHostAllowed(final):
            raise ValueError(f"refusing JSON redirect to {final}")
        return json.loads(resp.read().decode("utf-8"))


def _httpDownload(url: str, dest: Path, progress=None, cancelled=None) -> None:
    if not _httpsHostAllowed(url):
        raise ValueError(f"refusing download from {url}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            final = resp.geturl()
            if not _httpsHostAllowed(final):
                raise ValueError(f"refusing download redirect to {final}")
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as f:
                while True:
                    if cancelled and cancelled():
                        raise RuntimeError("download cancelled")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        tmp.replace(dest)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except Exception:
            pass
        raise


def _releaseVersion(rel: dict) -> str:
    tag = (rel.get("tag_name") or "").strip()
    if tag:
        return tag
    name = (rel.get("name") or "").strip()
    return name or "0.0.0"


def _pickAsset(assets: list, kind: str) -> dict | None:
    """
    Choose a release asset for this install kind.
    kind: appimage | launcher | python | any
    """
    if not assets:
        return None
    names = [(a, (a.get("name") or "").lower()) for a in assets]

    def find(*predicates):
        for a, n in names:
            if all(p(n) for p in predicates):
                return a
        return None

    if kind == "appimage":
        # Prefer AppImage for host arch
        import platform
        arch = platform.machine().lower()
        archHints = []
        if arch in ("x86_64", "amd64"):
            archHints = ["x86_64", "amd64", "x64"]
        elif arch in ("aarch64", "arm64"):
            archHints = ["aarch64", "arm64"]
        for hint in archHints:
            hit = find(lambda n: n.endswith(".appimage"), lambda n, h=hint: h in n)
            if hit:
                return hit
        hit = find(lambda n: n.endswith(".appimage"))
        if hit:
            return hit
        # Zip that likely contains an AppImage
        hit = find(lambda n: n.endswith(".zip"), lambda n: "appimage" in n or "linux" in n)
        if hit:
            return hit
        return None

    if kind == "windows":
        # Full launcher + python-embed. Used for 3.0.x → 3.1+ on Windows.
        hit = find(lambda n: n.endswith(".zip"), lambda n: "windows" in n)
        if hit:
            return hit
        return None

    # launcher / python payload (code-only; already on python-embed)
    hit = find(lambda n: n.endswith(".zip"), lambda n: "python" in n)
    if hit:
        return hit
    hit = find(lambda n: n.endswith(".zip"), lambda n: "update" in n)
    if hit:
        return hit
    hit = find(lambda n: n.endswith(".zip"), lambda n: "windows" not in n and "mac" not in n)
    if hit:
        return hit
    return find(lambda n: n.endswith(".zip"))


def fetchLatestRelease(
    channel: str | None = None,
    requireNewer: bool = True,
    allowCurrent: bool = False,
    assetKind: str | None = None,
) -> dict | None:
    """
    Return a dict:
      version, tag, name, prerelease, html_url, asset_name, asset_url, body
    or None if nothing suitable / network error / no releases yet.

    requireNewer: default True (startup check). False is used when reverting
    from beta/RC to the latest published tag, which may be an older triple.
    allowCurrent: when requireNewer is False, still return a same-version
      release (needed to download DataDoctor-Windows-*.zip after a Python-zip hop).
    assetKind: appimage | launcher | python | windows. Default is inferred.
    """
    channel = channel or getUpdateChannel()
    try:
        releases = _httpJson(_API + "?per_page=20")
    except urllib.error.HTTPError as e:
        Logic.logMessage("INFO", f"Update check: GitHub HTTP {e.code} (no releases yet is OK)")
        return None
    except Exception as e:
        Logic.logMessage("INFO", f"Update check skipped: {e}")
        return None

    if not isinstance(releases, list) or not releases:
        Logic.logMessage("INFO", "Update check: no GitHub releases published yet")
        return None

    candidates = []
    for rel in releases:
        if rel.get("draft"):
            continue
        isPre = bool(rel.get("prerelease"))
        ver = _releaseVersion(rel)
        # Treat -rc / -beta tags as pre even if not marked
        if Version.isPrereleaseVersion(ver):
            isPre = True
        if channel == "stable" and isPre:
            continue
        parsed = Version.parseVersion(ver)
        if parsed is None:
            continue
        candidates.append((Version.versionKey(parsed), rel, ver, isPre))

    if not candidates:
        return None

    candidates.sort(key=lambda t: t[0], reverse=True)
    _key, rel, ver, isPre = candidates[0]

    if requireNewer:
        if not Version.isNewer(ver, Version.VERSION):
            if Config.debug:
                Logic.logMessage(
                    "DEBUG",
                    f"Update check: up to date local={Version.VERSION} remote={ver}",
                )
            return None
    elif not allowCurrent and Version.compareVersions(ver, Version.VERSION) == 0:
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Update check: already on remote={ver}",
            )
        return None

    kind = detectInstallKind()
    if assetKind is None:
        if windowsNeedsLauncherRefresh():
            assetKind = "windows"
        elif kind == "appimage":
            assetKind = "appimage"
        else:
            assetKind = "launcher"
    asset = _pickAsset(rel.get("assets") or [], assetKind)
    if asset is None and assetKind == "windows":
        Logic.logMessage(
            "INFO",
            f"Update {ver} found but no DataDoctor-Windows-*.zip on the release",
        )
    elif asset is None and kind != "appimage":
        asset = _pickAsset(rel.get("assets") or [], "python")
        assetKind = "launcher" if asset else assetKind
    if asset is None:
        Logic.logMessage(
            "INFO",
            f"Update {ver} found but no matching asset for install kind={kind} assetKind={assetKind}",
        )
        return {
            "version": Version.displayVersion(ver),
            "tag": rel.get("tag_name") or ver,
            "name": rel.get("name") or ver,
            "prerelease": isPre,
            "html_url": rel.get("html_url") or "",
            "asset_name": None,
            "asset_url": None,
            "asset_digest": None,
            "body": (rel.get("body") or "")[:2000],
            "kind": kind,
            "assetKind": assetKind,
        }

    return {
        "version": Version.displayVersion(ver),
        "tag": rel.get("tag_name") or ver,
        "name": rel.get("name") or ver,
        "prerelease": isPre,
        "html_url": rel.get("html_url") or "",
        "asset_name": asset.get("name"),
        "asset_url": asset.get("browser_download_url"),
        "asset_digest": asset.get("digest"),
        "body": (rel.get("body") or "")[:2000],
        "kind": kind,
        "assetKind": assetKind,
    }


def downloadReleaseAsset(info: dict, destDir: Path | None = None, cancelled=None) -> Path | None:
    """
    Download the release asset into updates/.
    For AppImage zips, extract the .AppImage into updates/.
    Returns path to the primary file to apply, or None.
    """
    url = info.get("asset_url")
    name = _safeDownloadName(info.get("asset_name") or "download.bin")
    if not url:
        return None
    destDir = destDir or updateDir()
    if destDir is None:
        return None
    destDir = Path(destDir)
    destDir.mkdir(parents=True, exist_ok=True)

    target = destDir / name
    Logic.logMessage("INFO", f"Downloading update {info.get('version')} → {target}")
    try:
        _httpDownload(url, target, cancelled=cancelled)
    except Exception as e:
        if cancelled and cancelled():
            Logic.logMessage("INFO", "Update download cancelled")
        else:
            Logic.logException("Update download failed", e)
        return None
    if not _verifyDigest(target, info.get("asset_digest")):
        return None

    kind = info.get("kind") or detectInstallKind()
    lower = name.lower()

    if kind == "appimage":
        if lower.endswith(".appimage"):
            try:
                target.chmod(target.stat().st_mode | 0o111)
            except Exception:
                pass
            return target
        if lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(target, "r") as zf:
                    members = [m for m in zf.namelist() if m.lower().endswith(".appimage")]
                    if not members:
                        Logic.logMessage("WARN", "Update zip has no .AppImage inside")
                        return target
                    # Prefer arch match
                    member = members[0]
                    for m in members:
                        if "x86_64" in m or "aarch64" in m:
                            member = m
                            break
                    if ".." in member.replace("\\", "/").split("/"):
                        Logic.logMessage("WARN", f"Skipping unsafe AppImage zip member {member}")
                        return target
                    outName = Path(member).name
                    if not outName.lower().endswith(".appimage"):
                        return target
                    outPath = destDir / outName
                    with zf.open(member) as src, open(outPath, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    outPath.chmod(outPath.stat().st_mode | 0o111)
                try:
                    target.unlink()
                except Exception:
                    pass
                return outPath
            except Exception as e:
                Logic.logException("Extract AppImage from zip failed", e)
                return target

    return target


def writePendingMarker(info: dict, payloadPath: Path) -> Path | None:
    """Record what was downloaded so apply scripts / UI know what to run."""
    d = updateDir()
    if d is None:
        return None
    marker = d / "pending.json"
    data = {
        "version": info.get("version"),
        "tag": info.get("tag"),
        "kind": info.get("kind") or detectInstallKind(),
        "payload": str(payloadPath),
        "asset_name": info.get("asset_name"),
    }
    try:
        marker.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return marker
    except Exception as e:
        Logic.logException("writePendingMarker failed", e)
        return None


def appImagePath() -> Path | None:
    p = os.environ.get("APPIMAGE")
    if p and os.path.isfile(p):
        return Path(p).resolve()
    return None


def applyAppImageScriptPath() -> Path | None:
    """
    Prefer applyAppImageUpdate.sh next to the running AppImage,
    else resourcePath / scripts next to install root.
    """
    root = installRoot()
    names = ("applyAppImageUpdate.sh", "applyAppImageUpdate")
    candidates = []
    if root:
        for n in names:
            candidates.append(root / n)
            candidates.append(root / "scripts" / n)
    try:
        candidates.append(Path(Logic.resourcePath("scripts/applyAppImageUpdate.sh")))
    except Exception:
        pass
    for c in candidates:
        if c.is_file():
            return c
    return None


def launcherApplyScript() -> Path | None:
    root = installRoot()
    if root is None:
        return None
    for rel in (
        "applyUpdate.cmd",
        "applyUpdate.sh",
        "pythonFiles/scripts/applyUpdate.py",
        "Project Files/scripts/applyUpdate.py",
        "scripts/applyUpdate.py",
    ):
        p = root / rel
        if p.is_file():
            return p
    return None


def spawnAppImageReplaceAndExit(newAppImage: Path, mainWindow=None) -> bool:
    """
    Start a detached shell that waits for this process to exit, then replaces
    the current AppImage with newAppImage. Then quit the QApplication.
    """
    current = appImagePath()
    if current is None:
        Logic.logMessage("WARN", "Not running as AppImage — cannot auto-replace")
        return False
    if not newAppImage.is_file():
        return False

    # Always write the script we ship in this build so a planted
    # applyAppImageUpdate.sh next to the AppImage cannot run.
    d = updateDir()
    if d is None:
        return False
    script = d / "applyAppImageUpdate.sh"
    try:
        script.write_text(_APPIMAGE_APPLY_SCRIPT, encoding="utf-8")
        script.chmod(script.stat().st_mode | 0o111)
    except Exception as e:
        Logic.logException("could not write applyAppImageUpdate.sh", e)
        return False

    import subprocess
    env = os.environ.copy()
    cmd = [
        "bash",
        str(script),
        "--current",
        str(current),
        "--new",
        str(newAppImage),
        "--wait-pid",
        str(os.getpid()),
    ]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(current.parent),
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        Logic.logMessage("INFO", f"Spawned AppImage replace: {newAppImage} → {current}")
    except Exception as e:
        Logic.logException("spawnAppImageReplaceAndExit failed", e)
        return False

    # Quit app so wait-pid can finish
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()
    except Exception:
        pass
    return True


_APPIMAGE_APPLY_SCRIPT = r'''#!/bin/bash
# Replace running AppImage after it exits.
# Usage: applyAppImageUpdate.sh --current PATH --new PATH --wait-pid PID
set -e
CURRENT=""
NEW=""
WAIT_PID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --current) CURRENT="$2"; shift 2 ;;
    --new) NEW="$2"; shift 2 ;;
    --wait-pid) WAIT_PID="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [ -z "$CURRENT" ] || [ -z "$NEW" ]; then
  echo "Usage: $0 --current /path/DataDoctor.AppImage --new /path/Update/new.AppImage [--wait-pid PID]" >&2
  exit 1
fi
if [ ! -f "$NEW" ]; then
  echo "ERROR: new AppImage not found: $NEW" >&2
  exit 1
fi
if [ -n "$WAIT_PID" ]; then
  # Wait until the app process is gone (max ~10 min)
  for i in $(seq 1 600); do
    if ! kill -0 "$WAIT_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  sleep 1
  if kill -0 "$WAIT_PID" 2>/dev/null; then
    echo "ERROR: process $WAIT_PID still running; not replacing AppImage" >&2
    exit 1
  fi
fi
magic=$(od -An -N4 -tx1 "$NEW" 2>/dev/null | tr -d ' \n')
case "$magic" in
  7f454c46*|2321*) ;;
  *)
    echo "ERROR: new file is not an ELF/AppImage: $NEW" >&2
    exit 1
    ;;
esac
chmod +x "$NEW" 2>/dev/null || true
# Backup then replace
if [ -f "$CURRENT" ]; then
  BAK="${CURRENT}.bak"
  rm -f "$BAK"
  mv "$CURRENT" "$BAK" || true
fi
mv "$NEW" "$CURRENT"
chmod +x "$CURRENT" 2>/dev/null || true
# Drop pending marker if present
UPD_DIR="$(dirname "$CURRENT")/updates"
rm -f "$UPD_DIR/pending.json" 2>/dev/null || true
rm -f "$(dirname "$CURRENT")/Update/pending.json" 2>/dev/null || true
echo "AppImage updated: $CURRENT"
'''


def ensureAppImageApplyScriptOnDisk() -> Path | None:
    """Copy apply script next to AppImage / install root if missing."""
    root = installRoot()
    if root is None:
        return None
    dest = root / "applyAppImageUpdate.sh"
    if dest.is_file():
        return dest
    try:
        dest.write_text(_APPIMAGE_APPLY_SCRIPT, encoding="utf-8")
        dest.chmod(dest.stat().st_mode | 0o111)
        return dest
    except Exception as e:
        Logic.logException("ensureAppImageApplyScriptOnDisk failed", e)
        return None


# ---------------------------------------------------------------------------
# Qt UI helpers (lazy imports so non-GUI scripts can import Version-only paths)
# ---------------------------------------------------------------------------

def scheduleStartupUpdateCheck(parent=None, delayMs: int = 2500) -> None:
    """Fire a background update check after the main window is up."""
    try:
        from PyQt6.QtCore import QTimer

        def _go():
            if windowsNeedsLauncherRefresh():
                runWindowsLauncherRefreshUi(parent)
            else:
                runUpdateCheckUi(parent, silentIfNone=True)

        QTimer.singleShot(delayMs, _go)
    except Exception as e:
        Logic.logMessage("DEBUG", f"scheduleStartupUpdateCheck: {e}")


def runWindowsLauncherRefreshUi(parent=None) -> None:
    """
    3.0.x .venv install that already applied the Python zip: still needs
    DataDoctor-Windows-*.zip even when the version number matches.
    """
    from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMessageBox

    class _Signals(QObject):
        done = pyqtSignal(object)

    class _Worker(QRunnable):
        def __init__(self, signals):
            super().__init__()
            self.signals = signals

        def run(self):
            try:
                info = fetchLatestRelease(
                    requireNewer=False,
                    allowCurrent=True,
                    assetKind="windows",
                )
            except Exception as e:
                Logic.logMessage("INFO", f"Windows launcher refresh check: {e}")
                info = None
            self.signals.done.emit(info)

    def onDone(info):
        if info is None or not info.get("asset_url"):
            QMessageBox.information(
                parent,
                "Launcher update",
                "This Windows install still uses a system Python (.venv).\n\n"
                "3.1+ needs the Windows package (DataDoctor-Windows-*.zip), which\n"
                "replaces Data Doctor.exe and installs Python 3.14 under\n"
                "pythonFiles\\python-embed\\.\n\n"
                "Download that zip from GitHub Releases into updates\\, then\n"
                "restart Data Doctor. The launcher runs applyUpdate.cmd and exits\n"
                "so the .exe can be replaced; applyUpdate starts the app afterward.",
            )
            return
        ver = info.get("version") or "?"
        box = QMessageBox(parent)
        box.setWindowTitle("Launcher update")
        box.setText(
            "This Windows install still uses a system Python (.venv).\n\n"
            f"Available:  {ver}\n\n"
            "Download the Windows package, then restart Data Doctor.\n"
            "The launcher runs applyUpdate.cmd and exits so the .exe can\n"
            "be replaced; applyUpdate starts the app when it finishes."
        )
        downloadBtn = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(downloadBtn)
        box.exec()
        if box.clickedButton() is downloadBtn:
            _downloadAndOfferApply(parent, info)

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateWindowsRefreshSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals))


def runRevertToPublishedUi(parent=None) -> None:
    """
    After the user turns Beta updates off: offer the latest published
    (non alpha/beta/rc) release even if it is older than the current RC.
    """
    from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMessageBox

    class _Signals(QObject):
        done = pyqtSignal(object)

    class _Worker(QRunnable):
        def __init__(self, signals):
            super().__init__()
            self.signals = signals

        def run(self):
            try:
                info = fetchLatestRelease(channel="stable", requireNewer=False)
            except Exception as e:
                Logic.logMessage("INFO", f"Revert-to-published check: {e}")
                info = None
            self.signals.done.emit(info)

    def onDone(info):
        if info is None:
            QMessageBox.information(
                parent,
                "Updates",
                "No published (non-beta / non-RC) GitHub release was found.\n\n"
                "Stay on this build, or publish a stable tag to revert to.",
            )
            return
        local = Version.displayVersion()
        ver = info.get("version") or "?"
        box = QMessageBox(parent)
        box.setWindowTitle("Revert to published")
        box.setText(
            "Beta updates were turned off.\n\n"
            f"Installed:  {local}\n"
            f"Published:  {ver}\n\n"
            "Download the published build and restart to leave the beta/RC channel?"
        )
        downloadBtn = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(downloadBtn)
        box.exec()
        if box.clickedButton() is downloadBtn:
            _downloadAndOfferApply(parent, info)

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateRevertSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals))


def runUpdateCheckUi(parent=None, silentIfNone: bool = True) -> None:
    """
    Background-fetch latest release; if newer, prompt the user.
    silentIfNone: no popup when already current / offline / no releases.
    """
    from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMessageBox

    class _Signals(QObject):
        done = pyqtSignal(object)  # info dict or None

    class _Worker(QRunnable):
        def __init__(self, signals):
            super().__init__()
            self.signals = signals

        def run(self):
            try:
                info = fetchLatestRelease()
            except Exception as e:
                Logic.logMessage("INFO", f"Update check worker: {e}")
                info = None
            self.signals.done.emit(info)

    def onDone(info):
        if info is None:
            if not silentIfNone and parent is not None:
                QMessageBox.information(
                    parent,
                    "Updates",
                    f"You're on the latest version ({Version.displayVersion()}).\n\n"
                    "If nothing is published on GitHub Releases yet, that is expected.",
                )
            return
        _promptUpdate(parent, info)

    signals = _Signals()
    # Keep reference on parent/app so it is not GC'd mid-flight
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateCheckSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals))


def _promptUpdate(parent, info: dict) -> None:
    from PyQt6.QtWidgets import QMessageBox

    ver = info.get("version") or "?"
    local = Version.displayVersion()
    pre = " (pre-release / beta)" if info.get("prerelease") else ""
    kind = info.get("kind") or detectInstallKind()
    hasAsset = bool(info.get("asset_url"))

    lines = [
        f"A newer version is available{pre}.",
        f"",
        f"Installed:  {local}",
        f"Available:  {ver}",
    ]
    if info.get("html_url"):
        lines.append(f"")
        lines.append(f"Release page: {info['html_url']}")
    if not hasAsset:
        lines.append("")
        lines.append(
            "No downloadable package for this install type was attached to the "
            "release yet. Open the release page to download manually."
        )
        QMessageBox.information(parent, "Update available", "\n".join(lines))
        return

    needsWindowsZip = (info.get("assetKind") == "windows") or windowsNeedsLauncherRefresh()
    if kind == "appimage":
        lines.append("")
        lines.append(
            "Download will place the new AppImage in an updates/ folder next to "
            "this AppImage. You can then replace the current file (the app will "
            "offer to quit and apply, or you can run applyAppImageUpdate.sh)."
        )
    elif kind == "launcher":
        lines.append("")
        if needsWindowsZip:
            lines.append(
                "This version ships a new Windows launcher and bundled Python 3.14. "
                "Download the Windows zip into updates\\, then restart Data Doctor. "
                "The launcher starts applyUpdate.cmd and exits so the .exe can be replaced; "
                "applyUpdate.cmd starts Data Doctor again when it finishes."
            )
        else:
            lines.append(
                "Download will place a zip in updates/. Restart Data Doctor "
                "to apply the update."
            )
    else:
        lines.append("")
        lines.append(
            "Dev/source install: the package will download into updates/ under "
            "the project root. Apply manually if desired."
        )

    box = QMessageBox(parent)
    box.setWindowTitle("Update available")
    box.setText("\n".join(lines))
    downloadBtn = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(downloadBtn)
    box.exec()
    if box.clickedButton() is not downloadBtn:
        return

    _downloadAndOfferApply(parent, info)


def _downloadAndOfferApply(parent, info: dict) -> None:
    from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QApplication, QMessageBox, QDialog, QVBoxLayout, QLabel,
        QProgressBar, QPushButton,
    )

    progress = QDialog(parent)
    progress.setWindowTitle("Update")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setModal(True)
    boxLay = QVBoxLayout(progress)
    boxLay.setContentsMargins(20, 16, 20, 16)
    boxLay.setSpacing(12)
    progLabel = QLabel("Downloading update…")
    progLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
    progBar = QProgressBar()
    progBar.setRange(0, 0)
    progBar.setTextVisible(False)
    progBar.setMinimumWidth(320)
    progCancel = QPushButton("Cancel")
    progCancel.setAutoDefault(False)
    cancelled = {"flag": False}

    def _cancelDownload():
        cancelled["flag"] = True
        progress.reject()

    progCancel.clicked.connect(_cancelDownload)
    boxLay.addWidget(progLabel)
    boxLay.addWidget(progBar)
    boxLay.addWidget(progCancel, alignment=Qt.AlignmentFlag.AlignHCenter)
    progress.resize(400, progress.sizeHint().height())
    progress.show()

    class _Signals(QObject):
        done = pyqtSignal(object)  # Path or None

    class _Worker(QRunnable):
        def __init__(self, signals, info):
            super().__init__()
            self.signals = signals
            self.info = info

        def run(self):
            path = None
            try:
                if cancelled["flag"]:
                    self.signals.done.emit(False)
                    return
                path = downloadReleaseAsset(
                    self.info, cancelled=lambda: cancelled["flag"]
                )
                if cancelled["flag"]:
                    if path is not None:
                        try:
                            Path(path).unlink()
                        except Exception:
                            pass
                    self.signals.done.emit(False)
                    return
                if path is not None:
                    writePendingMarker(self.info, path)
                    if (self.info.get("kind") or detectInstallKind()) == "appimage":
                        ensureAppImageApplyScriptOnDisk()
            except Exception as e:
                Logic.logException("download worker failed", e)
                path = None
            self.signals.done.emit(path)

    def onDone(path):
        progress.close()
        if path is False:
            return
        if path is None:
            QMessageBox.warning(
                parent,
                "Update",
                "Download failed. Check the log viewer / app.log and try again later.",
            )
            return
        kind = info.get("kind") or detectInstallKind()
        if kind == "appimage":
            box = QMessageBox(parent)
            box.setWindowTitle("Download complete")
            box.setText(
                f"Downloaded:\n{path}\n\n"
                "Replace the current AppImage now?\n"
                "Data Doctor will quit; the updater waits for exit, then swaps the file.\n\n"
                "Or choose Later and run applyAppImageUpdate.sh after closing."
            )
            applyBtn = box.addButton("Quit and apply", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is applyBtn:
                if not spawnAppImageReplaceAndExit(Path(path), parent):
                    QMessageBox.warning(
                        parent,
                        "Update",
                        "Could not start the AppImage replace script.\n"
                        f"Close Data Doctor, then run applyAppImageUpdate.sh with:\n"
                        f"  --new {path}",
                    )
            return

        assetName = (info.get("asset_name") or str(path) or "").lower()
        needsWindowsZip = (
            info.get("assetKind") == "windows"
            or "windows" in assetName
            or windowsNeedsLauncherRefresh()
        )
        QMessageBox.information(
            parent,
            "Download complete",
            f"Downloaded:\n{path}\n\n"
            "Restart Data Doctor to apply the update.\n"
            "The launcher runs applyUpdate.cmd and exits so launcher files "
            "can be replaced; applyUpdate starts the app when it is done.",
        )

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateDownloadSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals, info))
