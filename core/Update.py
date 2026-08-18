# Update.py
# Check GitHub Releases, download payload into Update/, help apply (launcher or AppImage).
#
# Stable channel → latest non-prerelease on GitHub.
# Beta channel   → latest release including GitHub "pre-release" and/or -rc./-beta. tags.
#
# Works before any release is published: check fails quietly (no dialog spam).

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from core import Config, Logic, Utils, Version

# User-Agent required by GitHub API
_UA = f"DataDoctor/{Version.displayVersion()} (+https://github.com/{Version.GITHUB_REPO})"
_API = f"https://api.github.com/repos/{Version.GITHUB_REPO}/releases"
_TIMEOUT = 20


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

    # Launcher layout: .../Project Files/DataDoctor.py[w] with sibling Update/ or applyUpdate
    try:
        appRoot = getattr(Config, "appRoot", "") or ""
        candidates = []
        if appRoot:
            candidates.append(Path(appRoot))
            candidates.append(Path(appRoot).parent)
        candidates.append(Path.cwd())
        for base in candidates:
            pf = base / "Project Files"
            if pf.is_dir() and (
                (pf / "DataDoctor.py").is_file()
                or (pf / "DataDoctor.pyw").is_file()
            ):
                return "launcher"
            if (base / "Data Doctor.exe").is_file() or (base / "Data Doctor.command").is_file():
                return "launcher"
    except Exception:
        pass
    return "dev"


def installRoot() -> Path | None:
    """Directory that should hold Update/ (and apply scripts for launcher)."""
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
    # If we're inside Project Files, install root is parent
    if root.name == "Project Files":
        return root.parent
    if (root / "Project Files").is_dir():
        return root
    # Dev: project root is fine for a local Update/ folder
    return root


def updateDir() -> Path | None:
    root = installRoot()
    if root is None:
        return None
    d = root / "Update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _httpJson(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _httpDownload(url: str, dest: Path, progress=None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        done = 0
        with open(tmp, "wb") as f:
            while True:
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

    # launcher / python payload
    hit = find(lambda n: n.endswith(".zip"), lambda n: "python" in n)
    if hit:
        return hit
    hit = find(lambda n: n.endswith(".zip"), lambda n: "update" in n)
    if hit:
        return hit
    # Windows full package is not applied via applyUpdate the same way — skip .exe
    hit = find(lambda n: n.endswith(".zip"), lambda n: "windows" not in n and "mac" not in n)
    if hit:
        return hit
    return find(lambda n: n.endswith(".zip"))


def fetchLatestRelease(channel: str | None = None) -> dict | None:
    """
    Return a dict:
      version, tag, name, prerelease, html_url, asset_name, asset_url, body
    or None if nothing suitable / network error / no releases yet.
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

    if not Version.isNewer(ver, Version.VERSION):
        if Config.debug:
            Logic.logMessage(
                "DEBUG",
                f"Update check: up to date local={Version.VERSION} remote={ver}",
            )
        return None

    kind = detectInstallKind()
    assetKind = "appimage" if kind == "appimage" else "launcher"
    asset = _pickAsset(rel.get("assets") or [], assetKind)
    if asset is None and kind != "appimage":
        asset = _pickAsset(rel.get("assets") or [], "python")
    if asset is None:
        Logic.logMessage(
            "INFO",
            f"Update {ver} found but no matching asset for install kind={kind}",
        )
        return {
            "version": Version.displayVersion(ver),
            "tag": rel.get("tag_name") or ver,
            "name": rel.get("name") or ver,
            "prerelease": isPre,
            "html_url": rel.get("html_url") or "",
            "asset_name": None,
            "asset_url": None,
            "body": (rel.get("body") or "")[:2000],
            "kind": kind,
        }

    return {
        "version": Version.displayVersion(ver),
        "tag": rel.get("tag_name") or ver,
        "name": rel.get("name") or ver,
        "prerelease": isPre,
        "html_url": rel.get("html_url") or "",
        "asset_name": asset.get("name"),
        "asset_url": asset.get("browser_download_url"),
        "body": (rel.get("body") or "")[:2000],
        "kind": kind,
    }


def downloadReleaseAsset(info: dict, destDir: Path | None = None) -> Path | None:
    """
    Download the release asset into Update/.
    For AppImage zips, extract the .AppImage into Update/.
    Returns path to the primary file to apply, or None.
    """
    url = info.get("asset_url")
    name = info.get("asset_name") or "download.bin"
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
        _httpDownload(url, target)
    except Exception as e:
        Logic.logException("Update download failed", e)
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
                    outName = Path(member).name
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

    script = applyAppImageScriptPath()
    # Inline fallback if no shipped script
    if script is None:
        # Write a one-shot script into Update/
        d = updateDir()
        if d is None:
            return False
        script = d / "applyAppImageUpdate.sh"
        script.write_text(_APPIMAGE_APPLY_SCRIPT, encoding="utf-8")
        script.chmod(script.stat().st_mode | 0o111)

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
fi
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
UPD_DIR="$(dirname "$CURRENT")/Update"
rm -f "$UPD_DIR/pending.json" 2>/dev/null || true
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
        QTimer.singleShot(delayMs, lambda: runUpdateCheckUi(parent, silentIfNone=True))
    except Exception as e:
        Logic.logMessage("DEBUG", f"scheduleStartupUpdateCheck: {e}")


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

    if kind == "appimage":
        lines.append("")
        lines.append(
            "Download will place the new AppImage in an Update/ folder next to "
            "this AppImage. You can then replace the current file (the app will "
            "offer to quit and apply, or you can run applyAppImageUpdate.sh)."
        )
    elif kind == "launcher":
        lines.append("")
        lines.append(
            "Download will place a Python zip in Update/. Restart Data Doctor "
            "to apply the update."
        )
    else:
        lines.append("")
        lines.append(
            "Dev/source install: the package will download into Update/ under "
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
                path = downloadReleaseAsset(self.info)
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

        # Launcher / dev — Windows exe applies the zip from Update/ on next start
        QMessageBox.information(
            parent,
            "Download complete",
            f"Downloaded:\n{path}\n\n"
            "Restart Data Doctor to apply the update.",
        )

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateDownloadSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals, info))
