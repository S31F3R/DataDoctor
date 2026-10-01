# Update.py
# Check GitHub Releases, download payload into updates/, help apply (launcher or AppImage).
#
# Stable channel → latest non-prerelease on GitHub.
# Beta channel   → latest release including GitHub "pre-release" and/or -rc./-beta. tags.
#
# No newer release / no GitHub tags yet: check is silent.
# GitHub unreachable (blocked, timeout, HTTP error): show a dialog.

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
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


GITHUB_UNREACHABLE_MSG = "Unable to check GitHub for updates."


class GitHubUnreachable(Exception):
    """GitHub Releases could not be reached (blocked, timeout, HTTP error)."""


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
    AppImage: under the user config dir so Downloads stays a single .AppImage.
    3.0.x Data Doctor.exe only looks in Update\\, so until python-embed
    exists we still write there.
    """
    if detectInstallKind() == "appimage":
        try:
            d = Path(Utils.getConfigDir()) / "updates"
            d.mkdir(parents=True, exist_ok=True)
            return d
        except Exception:
            return None
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


def windowsLauncherInstall() -> bool:
    """True when Data Doctor.exe is installed, so the Windows zip can refresh it."""
    root = installRoot()
    if root is None:
        return False
    return (root / "Data Doctor.exe").is_file()


def _cmdLines(text: str) -> str:
    """Command lines, ignoring blank lines from the old doubled CR writer."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _cmdTextSame(a: str, b: str) -> bool:
    return _cmdLines(a) == _cmdLines(b)


def windowsCmdNeedsBootstrapWrite(liveText, stagedText, body: str) -> bool:
    """
    True when startup should replace applyUpdate.cmd in place.

    A staged command that already matches is left for the second restart.
    A live command that already matches is left alone.
    """
    if stagedText is not None and _cmdTextSame(stagedText, body):
        return False
    if liveText is not None and _cmdTextSame(liveText, body):
        return False
    return True


def discardMatchingStagedCmd(root: Path) -> None:
    """Drop applyUpdate.cmd.new when it is the command already installed."""
    staged = root / "applyUpdate.cmd.new"
    live = root / "applyUpdate.cmd"
    if not staged.is_file() or not live.is_file():
        return
    try:
        if _cmdTextSame(staged.read_text(encoding="utf-8"), live.read_text(encoding="utf-8")):
            staged.unlink()
    except OSError:
        pass


def windowsLauncherLeftovers(root: Path) -> list[str]:
    """
    Files a Windows update could not replace while they were in use.

    applyUpdate.cmd.new and python-embed.next need another restart.
    An unchanged staged command is removed here so that restart is not asked.
    The other names are leftovers the restart also removes.
    """
    discardMatchingStagedCmd(root)
    items = []
    if (root / "applyUpdate.cmd.new").is_file():
        items.append("applyUpdate.cmd.new")
    for folder in ("pythonFiles", "Project Files"):
        if (root / folder / "python-embed.next" / "python.exe").is_file():
            items.append("python-embed.next")
            break
    if (root / "finishEmbedSwap.cmd").is_file():
        items.append("finishEmbedSwap.cmd")
    rootApply = root / "applyUpdate.py"
    scriptsApply = root / "pythonFiles" / "scripts" / "applyUpdate.py"
    legacyApply = root / "Project Files" / "scripts" / "applyUpdate.py"
    if rootApply.is_file() and (scriptsApply.is_file() or legacyApply.is_file()):
        items.append("applyUpdate.py")
    if (root / "python-standalone").is_dir():
        items.append("python-standalone")
    if any(root.glob("python-*-embed-*.zip")):
        items.append("python embed zip")
    return items


def windowsLauncherRestartPending(root: Path | None = None) -> bool:
    """True when this Windows install still has a staged launcher command or Python."""
    if not sys.platform.startswith("win"):
        return False
    if root is None:
        root = installRoot()
    if root is None or not (root / "Data Doctor.exe").is_file():
        return False
    items = windowsLauncherLeftovers(root)
    return "applyUpdate.cmd.new" in items or "python-embed.next" in items


def windowsLauncherRestartText(items: list[str]) -> str:
    labels = {
        "applyUpdate.cmd.new": "the new launcher command (applyUpdate.cmd.new)",
        "python-embed.next": "a staged Python folder (python-embed.next)",
        "finishEmbedSwap.cmd": "an old swap script (finishEmbedSwap.cmd)",
        "applyUpdate.py": "a leftover applyUpdate.py in the install folder",
        "python-standalone": "a leftover python-standalone folder",
        "python embed zip": "a leftover Python embed zip",
    }
    lines = "\n".join(f"- {labels.get(item, item)}" for item in items)
    return (
        "The Windows launcher still has a few files from the last update.\n\n"
        f"{lines}\n\n"
        "Restart closes Data Doctor, puts the new launcher command in place, "
        "and finishes whatever is still staged. Later asks again the next time "
        "Data Doctor opens."
    )


def launcherRestartScript() -> str:
    """
    Hidden cmd: wait until Data Doctor has exited, rename the staged command,
    swap a staged Python if one is there, then finish without a zip.

    No process listing. The retry stops after 8 tries.
    """
    lines = [
        "@echo off",
        "setlocal EnableDelayedExpansion",
        'cd /d "%~dp0"',
        '>"%TEMP%\\dd-launcher-wait.vbs" echo WScript.Sleep 1500',
        "wscript //B //Nologo \"%TEMP%\\dd-launcher-wait.vbs\"",
        "wscript //B //Nologo \"%TEMP%\\dd-launcher-wait.vbs\"",
        "set TRIES=0",
        ":swaptry",
        'if not exist "pythonFiles\\python-embed.next\\python.exe" if not exist "Project Files\\python-embed.next\\python.exe" goto swapcmd',
        'if exist "pythonFiles\\python-embed.next\\python.exe" (',
        '  rmdir /s /q "pythonFiles\\python-embed" 2>nul',
        '  ren "pythonFiles\\python-embed.next" "python-embed"',
        ")",
        'if exist "Project Files\\python-embed.next\\python.exe" (',
        '  rmdir /s /q "Project Files\\python-embed" 2>nul',
        '  ren "Project Files\\python-embed.next" "python-embed"',
        ")",
        'if exist "pythonFiles\\python-embed.next\\python.exe" goto swapwait',
        'if exist "Project Files\\python-embed.next\\python.exe" goto swapwait',
        "goto swapcmd",
        ":swapwait",
        "set /a TRIES+=1",
        "if !TRIES! LSS 8 (",
        "  wscript //B //Nologo \"%TEMP%\\dd-launcher-wait.vbs\"",
        "  goto swaptry",
        ")",
        ":swapcmd",
        'if exist "applyUpdate.cmd.new" (',
        '  if exist "applyUpdate.cmd" del /f /q "applyUpdate.cmd"',
        '  ren "applyUpdate.cmd.new" "applyUpdate.cmd"',
        ")",
        'if exist "finishEmbedSwap.cmd" del /f /q "finishEmbedSwap.cmd"',
        'set "PY="',
        'if exist "pythonFiles\\python-embed\\pythonw.exe" set "PY=pythonFiles\\python-embed\\pythonw.exe"',
        'if not defined PY if exist "Project Files\\python-embed\\pythonw.exe" set "PY=Project Files\\python-embed\\pythonw.exe"',
        'if not defined PY if exist "pythonFiles\\python-embed\\python.exe" set "PY=pythonFiles\\python-embed\\python.exe"',
        'set "SCRIPT=pythonFiles\\scripts\\applyUpdate.py"',
        'if not exist "%SCRIPT%" set "SCRIPT=Project Files\\scripts\\applyUpdate.py"',
        'if defined PY if exist "%SCRIPT%" (',
        '  start "" "%PY%" "%SCRIPT%" --finish-staged',
        "  goto done",
        ")",
        'if exist "Data Doctor.exe" start "" "Data Doctor.exe"',
        ":done",
        'del /f /q "%TEMP%\\dd-launcher-wait.vbs"',
        "endlocal",
        '(goto) 2>nul & del /f /q "%~f0"',
        "",
    ]
    return "\r\n".join(lines)


_launcherRestartLater = False


def launcherRestartLater() -> bool:
    return _launcherRestartLater


def noteLauncherRestartLater() -> None:
    global _launcherRestartLater
    _launcherRestartLater = True


def spawnLauncherRestart(root: Path) -> bool:
    """Start the hidden finisher and return. The caller closes Data Doctor."""
    if not sys.platform.startswith("win"):
        return False
    cmd = root / "finishLauncherRestart.cmd"
    try:
        cmd.write_text(launcherRestartScript(), encoding="utf-8", newline="\r\n")
    except Exception as e:
        Logic.logException("could not write launcher restart script", e)
        return False
    import subprocess
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(cmd)],
            cwd=str(root),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000 | 0x00000008 | 0x00000200,  # NO_WINDOW | DETACHED | NEW_GROUP
        )
    except Exception as e:
        Logic.logException("could not start launcher restart", e)
        return False
    Logic.logMessage("INFO", "Launcher restart staged; closing Data Doctor")
    return True


def offerWindowsLauncherRestart(parent=None) -> bool:
    """
    Ask to finish a Windows update that staged applyUpdate.cmd.new.

    Restart renames that command and finishes whatever is left.
    Later waits until the next time Data Doctor opens.
    Returns True when Data Doctor is closing to restart.
    """
    root = installRoot()
    if root is None:
        return False
    items = windowsLauncherLeftovers(root)
    if "applyUpdate.cmd.new" not in items and "python-embed.next" not in items:
        return False

    def _show():
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(parent)
        box.setWindowTitle("Finish launcher update")
        box.setText(windowsLauncherRestartText(items))
        restartBtn = box.addButton("Restart", QMessageBox.ButtonRole.AcceptRole)
        laterBtn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restartBtn)
        box.exec()
        if box.clickedButton() is restartBtn:
            return "restart"
        noteLauncherRestartLater()
        return "later"

    choice = _holdUpdatePrompt(_show)
    if choice != "restart":
        return False
    if not spawnLauncherRestart(root):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(
            parent,
            "Finish launcher update",
            "Could not start the launcher update.",
        )
        return False
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if parent is not None:
        parent.close()
    if app is not None:
        app.quit()
    return True


def chooseAssetKind(installKind: str, windowsExe: bool) -> str:
    """Launcher installs take the Windows zip so the exe and icon update with the code."""
    if windowsExe:
        return "windows"
    if installKind == "appimage":
        return "appimage"
    return "launcher"


def resolveReleaseAsset(assets, assetKind: str, installKind: str):
    """
    Pick the release file for this install.

    A Windows launcher that has no DataDoctor-Windows zip falls back to the
    Python zip. That package does not include Data Doctor.exe or the icon.
    Returns (asset, assetKind, fellBackFromWindows).
    """
    asset = _pickAsset(assets, assetKind)
    fellBack = False
    if asset is None and assetKind == "windows":
        fellBack = True
        asset = _pickAsset(assets, "python")
        if asset is not None:
            assetKind = "launcher"
    elif asset is None and installKind != "appimage":
        asset = _pickAsset(assets, "python")
        if asset is not None:
            assetKind = "launcher"
    return asset, assetKind, fellBack


_APPLY_UPDATE_CMD = "\r\n".join([
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


def bootstrapWindowsApplyTools() -> None:
    """
    3.0.x applyUpdate copies core/* but not scripts/, and it downloads the
    Python zip (not the Windows zip). That zip ships core/applyUpdate.py.
    The next launch copies it into scripts/ and writes this command when
    the installed text differs and no staged command is already waiting.
    That command is what then applies DataDoctor-Windows-*.zip. A staged
    applyUpdate.cmd.new stays for the second-restart prompt. Later releases
    stage a new command only when its text actually changed.
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
        body = _APPLY_UPDATE_CMD
        try:
            scriptsDir = projectFiles / "scripts"
            if str(scriptsDir) not in sys.path:
                sys.path.insert(0, str(scriptsDir))
            import applyUpdate as _au
            getter = getattr(_au, "applyCmdBody", None)
            if callable(getter):
                body = getter()
            _au.migrateLegacyUpdatesFolder(root)
            _au.cleanupStaleLegacyDirs(root)
        except Exception:
            pass
        if (root / "Data Doctor.exe").is_file() or (root / "applyUpdate.cmd").is_file():
            cmd = root / "applyUpdate.cmd"
            staged = root / "applyUpdate.cmd.new"
            try:
                current = cmd.read_text(encoding="utf-8") if cmd.is_file() else None
            except OSError:
                current = None
            try:
                stagedText = staged.read_text(encoding="utf-8") if staged.is_file() else None
            except OSError:
                stagedText = None
            if windowsCmdNeedsBootstrapWrite(current, stagedText, body):
                cmd.write_text(body, encoding="utf-8", newline="")
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
    lastErr = None
    for attempt in range(1, 4):
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
            return
        except RuntimeError:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except Exception:
                pass
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            lastErr = e
            Logic.logMessage(
                "WARN",
                f"Update download attempt {attempt}/3 failed: {e}",
            )
            try:
                if tmp.is_file():
                    tmp.unlink()
            except Exception:
                pass
            if attempt < 3:
                time.sleep(2 * attempt)
            continue
        except Exception:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except Exception:
                pass
            raise
    raise lastErr


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
    or None if nothing suitable / no releases yet.
    Raises GitHubUnreachable when GitHub cannot be reached.

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
        if e.code == 404:
            Logic.logMessage("INFO", f"Update check: GitHub HTTP {e.code} (no releases yet is OK)")
            return None
        Logic.logMessage("WARN", f"Update check: GitHub HTTP {e.code}: {e}")
        raise GitHubUnreachable(GITHUB_UNREACHABLE_MSG) from e
    except Exception as e:
        Logic.logMessage("WARN", f"Update check skipped: {e}")
        raise GitHubUnreachable(GITHUB_UNREACHABLE_MSG) from e

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
        assetKind = chooseAssetKind(kind, windowsLauncherInstall())
    asset, assetKind, fellBack = resolveReleaseAsset(rel.get("assets") or [], assetKind, kind)
    if fellBack and asset is not None:
        Logic.logMessage(
            "INFO",
            f"Update {ver} has no DataDoctor-Windows zip. Using the Python package. "
            "Data Doctor.exe and Data Doctor.ico will not change.",
        )
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
    kind = info.get("kind") or detectInstallKind()
    lower = name.lower()
    already = (
        target.is_file()
        and target.stat().st_size > 0
        and _verifyDigest(target, info.get("asset_digest"))
    )
    # A Windows zip can be applied as-is. An AppImage release zip still unpacks.
    if already and not (kind == "appimage" and lower.endswith(".zip")):
        Logic.logMessage("INFO", f"Update already downloaded: {target.name}")
        if kind == "appimage" and lower.endswith(".appimage"):
            try:
                target.chmod(target.stat().st_mode | 0o111)
            except Exception:
                pass
        return target
    if already:
        Logic.logMessage("INFO", f"Update already downloaded: {target.name}")
    else:
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


def spawnApplyAndExit(mainWindow=None) -> bool:
    """
    Start applyUpdate.cmd / applyUpdate.sh and quit so launcher files can be
    replaced. applyUpdate starts Data Doctor again when it finishes.
    """
    import subprocess
    from PyQt6.QtWidgets import QApplication

    script = launcherApplyScript()
    root = installRoot()
    if script is None or root is None:
        Logic.logMessage("WARN", "spawnApplyAndExit: no apply script / install root")
        return False
    try:
        # Visible console so bunker merge can ask y/n (commonName / datatype).
        # DETACHED + DEVNULL made those prompts EOF-default to n with no window.
        kwargs = {
            "cwd": str(root),
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000010 | 0x00000200  # NEW_CONSOLE | NEW_GROUP
            subprocess.Popen(["cmd.exe", "/c", str(script)], **kwargs)
        else:
            kwargs["start_new_session"] = True
            subprocess.Popen(["bash", str(script)], **kwargs)
        Logic.logMessage("INFO", f"spawnApplyAndExit: started {script}")
    except Exception as e:
        Logic.logException("spawnApplyAndExit failed", e)
        return False

    def _quit():
        try:
            if mainWindow is not None:
                mainWindow.close()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(200, _quit)
    return True


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


def _sanitizedUpdaterEnv() -> dict:
    """
    Child env without this AppImage's mount on LD_LIBRARY_PATH / APPDIR.
    After we exit, that mount is gone; the updater's mv/chmod would fail if
    they still pointed at it.
    """
    env = os.environ.copy()
    appdir = env.get("APPDIR") or ""
    for key in list(env):
        if key.startswith("QT_") or key in (
            "PYTHONPATH", "PYTHONHOME", "PYTHONNOUSERSITE",
            "APPDIR", "APPIMAGE", "ARGV0", "OWD",
        ):
            env.pop(key, None)
    ld = env.get("LD_LIBRARY_PATH") or ""
    if ld:
        parts = [
            p for p in ld.split(":")
            if p and not (appdir and p.startswith(appdir))
            and "/.mount_" not in p
        ]
        if parts:
            env["LD_LIBRARY_PATH"] = ":".join(parts)
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def spawnAppImageReplaceAndExit(newAppImage: Path, mainWindow=None) -> bool:
    """
    Start a detached shell that waits for this process to exit, then replaces
    the current AppImage (keeping its filename, even if the user renamed it)
    and relaunches. Extra updater files are not left next to the AppImage.
    """
    current = appImagePath()
    if current is None:
        Logic.logMessage("WARN", "Not running as AppImage — cannot auto-replace")
        return False
    if not newAppImage.is_file():
        return False

    logPath = Path(Utils.getLogPath("applyUpdate.log"))
    try:
        logPath.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    try:
        fd, scriptPath = tempfile.mkstemp(prefix="datadoctor-apply-", suffix=".sh")
        os.close(fd)
        script = Path(scriptPath)
        script.write_text(_APPIMAGE_APPLY_SCRIPT, encoding="utf-8")
        script.chmod(0o700)
    except Exception as e:
        Logic.logException("could not write AppImage apply script", e)
        return False

    import subprocess
    cmd = [
        "bash",
        str(script),
        "--current",
        str(current),
        "--new",
        str(newAppImage.resolve()),
        "--wait-pid",
        str(os.getpid()),
        "--log",
        str(logPath),
    ]
    try:
        logFh = open(logPath, "a", encoding="utf-8")
        logFh.write(
            f"\n{datetime.now().isoformat(timespec='seconds')} "
            f"spawn: {' '.join(cmd)}\n"
        )
        logFh.flush()
        subprocess.Popen(
            cmd,
            cwd=str(current.parent),
            env=_sanitizedUpdaterEnv(),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=logFh,
            stderr=logFh,
        )
        logFh.close()
        Logic.logMessage(
            "INFO",
            f"Spawned AppImage replace: {newAppImage} → {current} (log {logPath})",
        )
    except Exception as e:
        Logic.logException("spawnAppImageReplaceAndExit failed", e)
        return False

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    def _quit():
        Logic.appIsQuitting = True
        app = QApplication.instance()
        try:
            if app is not None:
                app.closeAllWindows()
                app.quit()
        except Exception:
            pass

    QTimer.singleShot(400, _quit)
    return True


_APPIMAGE_APPLY_SCRIPT = r'''#!/bin/bash
# Replace the running AppImage after it exits. Keeps the user's filename.
# Usage: --current PATH --new PATH --wait-pid PID [--log PATH]
CURRENT=""
NEW=""
WAIT_PID=""
LOG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --current) CURRENT="$2"; shift 2 ;;
    --new) NEW="$2"; shift 2 ;;
    --wait-pid) WAIT_PID="$2"; shift 2 ;;
    --log) LOG="$2"; shift 2 ;;
    *) shift ;;
  esac
done
log() {
  echo "$(date -Iseconds 2>/dev/null || date) $*"
}
fail() {
  log "ERROR: $*"
  exit 1
}
if [ -n "$LOG" ]; then
  mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
  exec >>"$LOG" 2>&1
fi
if [ -z "$CURRENT" ] || [ -z "$NEW" ]; then
  fail "Usage: $0 --current /path/AppImage --new /path/new.AppImage [--wait-pid PID]"
fi
log "apply: current=$CURRENT new=$NEW wait=$WAIT_PID"
if [ ! -f "$NEW" ]; then
  fail "new AppImage not found: $NEW"
fi
if [ -n "$WAIT_PID" ]; then
  for i in $(seq 1 600); do
    if ! kill -0 "$WAIT_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  sleep 2
  if kill -0 "$WAIT_PID" 2>/dev/null; then
    fail "process $WAIT_PID still running; not replacing AppImage"
  fi
fi
magic=$(od -An -N4 -tx1 "$NEW" 2>/dev/null | tr -d ' \n')
case "$magic" in
  7f454c46*|2321*) ;;
  *)
    fail "new file is not an ELF/AppImage: $NEW"
    ;;
esac
chmod +x "$NEW" 2>/dev/null || true
HERE="$(dirname "$CURRENT")"
TMPBAK="/tmp/datadoctor-old-$$.AppImage"
rm -f "$TMPBAK" "${CURRENT}.bak"
MOVED=0
for i in $(seq 1 60); do
  if [ ! -e "$CURRENT" ]; then
    MOVED=1
    break
  fi
  if mv "$CURRENT" "$TMPBAK" 2>/dev/null; then
    MOVED=1
    break
  fi
  log "waiting to replace (file busy) $i"
  sleep 1
done
if [ "$MOVED" != 1 ]; then
  fail "could not move current AppImage aside (still in use?): $CURRENT"
fi
if ! mv "$NEW" "$CURRENT"; then
  log "restore previous AppImage"
  mv "$TMPBAK" "$CURRENT" 2>/dev/null || true
  fail "could not move new AppImage into place"
fi
chmod +x "$CURRENT" 2>/dev/null || true
rm -f "$TMPBAK"
# Leftovers from older in-app updates next to the AppImage.
rm -f "$HERE/applyAppImageUpdate.sh" "$HERE/applyAppImageUpdate" "${CURRENT}.bak"
rm -rf "$HERE/updates" "$HERE/Update"
NEW_DIR="$(dirname "$NEW")"
rm -f "$NEW_DIR/pending.json" "$NEW_DIR/README.txt"
log "AppImage updated: $CURRENT"
if [ -x "$CURRENT" ]; then
  nohup "$CURRENT" >/dev/null 2>&1 &
  log "Relaunched pid $!"
fi
rm -f "$0"
'''


def ensureAppImageApplyScriptOnDisk() -> Path | None:
    """No longer drop a .sh next to the AppImage (in-app update uses /tmp)."""
    return None


# ---------------------------------------------------------------------------
# Qt UI helpers (lazy imports so non-GUI scripts can import Version-only paths)
# ---------------------------------------------------------------------------

def pendingAppImagePath() -> Path | None:
    """Downloaded AppImage waiting for Quit and apply (config updates/)."""
    if detectInstallKind() != "appimage":
        return None
    d = updateDir()
    if d is None:
        return None
    marker = d / "pending.json"
    payload = None
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            p = data.get("payload")
            if p:
                payload = Path(p)
        except Exception:
            payload = None
    if payload is None or not payload.is_file():
        hits = sorted(
            d.glob("*.AppImage"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        payload = hits[0] if hits else None
    if payload is not None and payload.is_file():
        return payload
    return None


# A beta published while the app is open should show up well inside an hour.
BACKGROUND_UPDATE_INTERVAL_MS = 15 * 60 * 1000  # 15 minutes


def localWindowsPackage(info=None, directory: Path | None = None) -> Path | None:
    """Windows zip already in updates/, preferring the release's own file name."""
    d = Path(directory) if directory is not None else updateDir()
    if d is None or not d.is_dir():
        return None
    if isinstance(info, dict) and info.get("asset_name"):
        named = d / _safeDownloadName(info.get("asset_name"))
        if named.is_file() and named.stat().st_size > 0 and "windows" in named.name.lower():
            return named
    hits = [
        p for p in d.glob("*.zip")
        if p.is_file() and "windows" in p.name.lower() and p.stat().st_size > 0
    ]
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)


def launcherRefreshPlan(info, localZip: Path | None = None) -> str:
    """
    How a 3.0 install finishes the Windows package.

    local: a Windows zip is already on disk.
    download: GitHub has the package and it is not on disk yet.
    manual: nothing to apply.
    """
    if localZip is not None and Path(localZip).is_file():
        return "local"
    if isinstance(info, dict) and info.get("asset_url") and not info.get("_unreachable"):
        return "download"
    return "manual"


def _appliedMarker(root: Path) -> Path | None:
    for name in ("updates", "Update", "Updates", "update", "UPDATES"):
        marker = root / name / "applied.json"
        if marker.is_file():
            return marker
    return None


def cleanupAppliedZips(root: Path | None = None, ready: bool | None = None) -> list[str]:
    """
    Delete zips recorded after a finished apply.

    Not ready (still on system Python, or a launcher file is still staged)
    leaves the files for the next try. Runs off the GUI thread at startup.
    """
    if root is None:
        root = installRoot()
    if root is None:
        return []
    marker = _appliedMarker(root)
    if marker is None:
        return []
    if ready is None:
        ready = not windowsNeedsLauncherRefresh() and not windowsLauncherRestartPending(root)
    if not ready:
        Logic.logMessage("INFO", "Update zip kept until the install finishes")
        return []
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as e:
        Logic.logMessage("WARN", f"Could not read applied update list: {e}")
        return []
    removed = []
    kept = []
    for raw in (data.get("zips") if isinstance(data, dict) else None) or []:
        path = Path(str(raw))
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed.append(path.name)
            Logic.logMessage("INFO", f"Removed applied update {path.name}")
        except OSError as e:
            kept.append(str(path))
            Logic.logMessage("WARN", f"Could not remove applied update {path.name}: {e}")
    try:
        if kept:
            marker.write_text(json.dumps({"zips": kept}, indent=2), encoding="utf-8")
        else:
            marker.unlink()
    except OSError as e:
        Logic.logMessage("WARN", f"Could not update applied update list: {e}")
    return removed


def startAppliedZipCleanup() -> None:
    """Drop finished update zips without holding up the window."""
    import threading
    threading.Thread(
        target=cleanupAppliedZips,
        name="applied-zip-cleanup",
        daemon=True,
    ).start()


def scheduleStartupUpdateCheck(parent=None, delayMs: int = 2500) -> None:
    """Fire a background update check after the main window is up, then poll."""
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        def _go():
            startAppliedZipCleanup()
            if windowsLauncherRestartPending() and not launcherRestartLater():
                if offerWindowsLauncherRestart(parent):
                    return
            pending = pendingAppImagePath()
            if pending is not None:
                def _showReady():
                    from PyQt6.QtWidgets import QMessageBox
                    box = QMessageBox(parent)
                    box.setWindowTitle("Update ready")
                    box.setText(
                        "Hit Restart to update, or close this window to restart later."
                    )
                    restartBtn = box.addButton(
                        "Restart", QMessageBox.ButtonRole.AcceptRole
                    )
                    laterBtn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
                    box.setDefaultButton(restartBtn)
                    box.exec()
                    if box.clickedButton() is restartBtn:
                        spawnAppImageReplaceAndExit(pending, parent)
                    elif box.clickedButton() is laterBtn:
                        noteDeferredUpdate()

                _holdUpdatePrompt(_showReady)
                return
            if windowsNeedsLauncherRefresh():
                runWindowsLauncherRefreshUi(parent)
            else:
                runUpdateCheckUi(parent, silentIfNone=True)

        QTimer.singleShot(delayMs, _go)
        app = QApplication.instance()
        if app is not None and getattr(app, "_dataDoctorUpdateTimer", None) is None:
            t = QTimer(app)
            t.setInterval(BACKGROUND_UPDATE_INTERVAL_MS)
            t.timeout.connect(lambda: _backgroundUpdateTick(parent))
            t.start()
            app._dataDoctorUpdateTimer = t
    except Exception as e:
        Logic.logMessage("DEBUG", f"scheduleStartupUpdateCheck: {e}")


# QMessageBox.exec() still delivers the 15-minute timer. A second check
# would stack another Update available window on the one already open.
_updatePromptOpen = False


def updatePromptOpen() -> bool:
    return _updatePromptOpen


def shouldShowUpdatePrompt(info) -> bool:
    """False when an update window is already open, or Later deferred this release."""
    if _updatePromptOpen:
        return False
    return not updatePromptDeferred(info)


def _holdUpdatePrompt(show):
    """Run show() and keep other checks from opening another update window."""
    global _updatePromptOpen
    if _updatePromptOpen:
        return None
    _updatePromptOpen = True
    try:
        return show()
    finally:
        _updatePromptOpen = False


def noteDeferredUpdate(version=None) -> None:
    """Later: stay quiet for this release, but a newer beta/rc may still prompt."""
    Config.skipUpdatePromptThisSession = True
    if version:
        Config.dismissedUpdateVersion = str(version)


def updatePromptDeferred(info) -> bool:
    """
    True when this session already said Later and `info` is not a newer release.
    A beta published after Later still returns False so the passive check can show it.
    """
    if not getattr(Config, "skipUpdatePromptThisSession", False):
        return False
    if not isinstance(info, dict) or info.get("_unreachable") or not info.get("version"):
        return True
    dismissed = getattr(Config, "dismissedUpdateVersion", None)
    if not dismissed:
        return True
    return Version.compareVersions(str(info.get("version")), str(dismissed)) <= 0


def _backgroundUpdateTick(parent=None) -> None:
    if updatePromptOpen():
        return
    runUpdateCheckUi(parent, silentIfNone=True, silentIfUnreachable=True)


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
            except GitHubUnreachable as e:
                Logic.logMessage("WARN", f"Windows launcher refresh check: {e}")
                info = {"_unreachable": True, "message": str(e) or GITHUB_UNREACHABLE_MSG}
            except Exception as e:
                Logic.logMessage("INFO", f"Windows launcher refresh check: {e}")
                info = {"_unreachable": True, "message": GITHUB_UNREACHABLE_MSG}
            self.signals.done.emit(info)

    def onDone(info):
        def _show():
            localZip = localWindowsPackage(info if isinstance(info, dict) else None)
            plan = launcherRefreshPlan(info, localZip)
            if plan == "manual":
                if isinstance(info, dict) and info.get("_unreachable"):
                    _showGithubUnreachable(parent, info.get("message"))
                    return None
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
                return None
            ver = info.get("version") if isinstance(info, dict) else ""
            lines = ["This Windows install still uses a system Python (.venv).", ""]
            if ver:
                lines.extend([f"Available:  {ver}", ""])
            lines.append("The application will restart to finish the install process.")
            box = QMessageBox(parent)
            box.setWindowTitle("Launcher update")
            box.setText("\n".join(lines))
            okBtn = box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(okBtn)
            box.exec()
            clicked = box.clickedButton()
            box.hide()
            box.close()
            if clicked is not okBtn:
                return None
            if plan == "local":
                return {"localZip": str(localZip)}
            pickedInfo = dict(info)
            pickedInfo["autoApply"] = True
            return pickedInfo

        picked = _holdUpdatePrompt(_show)
        if not picked:
            return
        local = picked.get("localZip") if isinstance(picked, dict) else None
        if local:
            Logic.logMessage("INFO", f"Using Windows package already in updates: {Path(local).name}")
            if not spawnApplyAndExit(parent):
                QMessageBox.warning(
                    parent,
                    "Launcher update",
                    "Could not start applyUpdate.\n"
                    "Close Data Doctor and run applyUpdate.cmd from the install folder.",
                )
            return
        _downloadAndOfferApply(parent, picked)

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateWindowsRefreshSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals))


def runRevertToPublishedUi(parent=None) -> None:
    """
    After the user turns Beta updates off: if this build is an rc/beta,
    offer the latest published (non alpha/beta/rc) release so they can leave
    the pre-release channel. Already on a published build: stay silent.
    """
    from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMessageBox

    if not Version.isPrereleaseVersion(Version.VERSION):
        Logic.logMessage(
            "INFO",
            f"Revert-to-published: already on published {Version.displayVersion()}, skip",
        )
        return

    class _Signals(QObject):
        done = pyqtSignal(object)

    class _Worker(QRunnable):
        def __init__(self, signals):
            super().__init__()
            self.signals = signals

        def run(self):
            try:
                info = fetchLatestRelease(channel="stable", requireNewer=False)
            except GitHubUnreachable as e:
                Logic.logMessage("WARN", f"Revert-to-published check: {e}")
                info = {"_unreachable": True, "message": str(e) or GITHUB_UNREACHABLE_MSG}
            except Exception as e:
                Logic.logMessage("INFO", f"Revert-to-published check: {e}")
                info = {"_unreachable": True, "message": GITHUB_UNREACHABLE_MSG}
            self.signals.done.emit(info)

    def onDone(info):
        def _show():
            local = Version.displayVersion()
            if isinstance(info, dict) and info.get("_unreachable"):
                _showGithubUnreachable(parent, info.get("message"))
                return
            if info is None:
                QMessageBox.information(
                    parent,
                    "Updates",
                    "No published (non-beta / non-RC) GitHub release was found.\n\n"
                    "Stay on this build, or publish a stable tag to revert to.",
                )
                return
            ver = info.get("version") or "?"
            if Version.compareVersions(ver, Version.VERSION) == 0:
                Logic.logMessage(
                    "INFO",
                    f"Revert-to-published: already on published {ver}",
                )
                return
            box = QMessageBox(parent)
            box.setWindowTitle("Revert to published")
            box.setText(
                "Beta updates were turned off.\n\n"
                f"Installed:  {local}\n"
                f"Published:  {ver}\n\n"
                "Download the published build and restart to leave the beta/RC channel?"
            )
            downloadBtn = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
            laterBtn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(downloadBtn)
            box.exec()
            clicked = box.clickedButton()
            box.hide()
            box.close()
            if clicked is downloadBtn:
                return info
            if clicked is laterBtn:
                noteDeferredUpdate(ver)
            return None

        picked = _holdUpdatePrompt(_show)
        if picked:
            _downloadAndOfferApply(parent, picked)

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateRevertSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    QThreadPool.globalInstance().start(_Worker(signals))


def runUpdateCheckUi(parent=None, silentIfNone: bool = True, silentIfUnreachable: bool = False) -> None:
    """
    Background-fetch latest release; if newer, prompt the user.
    silentIfNone: no popup when already current / no releases.
    silentIfUnreachable: no popup when GitHub cannot be reached (periodic checks).
    An update window that is already open stays the only one.
    """
    if updatePromptOpen():
        return
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
            except GitHubUnreachable as e:
                Logic.logMessage("WARN", f"Update check worker: {e}")
                info = {"_unreachable": True, "message": str(e) or GITHUB_UNREACHABLE_MSG}
            except Exception as e:
                Logic.logMessage("INFO", f"Update check worker: {e}")
                info = {"_unreachable": True, "message": GITHUB_UNREACHABLE_MSG}
            self.signals.done.emit(info)

    def onDone(info):
        if not shouldShowUpdatePrompt(info):
            return
        if isinstance(info, dict) and info.get("_unreachable"):
            if not silentIfUnreachable:
                _holdUpdatePrompt(
                    lambda: _showGithubUnreachable(parent, info.get("message"))
                )
            return
        if info is None:
            if not silentIfNone and parent is not None:
                def _showLatest():
                    QMessageBox.information(
                        parent,
                        "Updates",
                        f"You're on the latest version ({Version.displayVersion()}).\n\n"
                        "If nothing is published on GitHub Releases yet, that is expected.",
                    )
                _holdUpdatePrompt(_showLatest)
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


def _showGithubUnreachable(parent, message=None) -> None:
    from PyQt6.QtWidgets import QMessageBox

    QMessageBox.information(
        parent,
        "Updates",
        (message or GITHUB_UNREACHABLE_MSG).strip() or GITHUB_UNREACHABLE_MSG,
    )


def _promptUpdate(parent, info: dict) -> None:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    if updatePromptOpen():
        return

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
    else:
        if kind == "appimage":
            lines.append("")
            lines.append("Download, then hit Restart to apply.")
        elif kind == "launcher":
            lines.append("")
            lines.append("Download, then hit Restart to apply.")
        else:
            lines.append("")
            lines.append("The package will download into updates/ under the project root.")

    def _show():
        if not hasAsset:
            QMessageBox.information(parent, "Update available", "\n".join(lines))
            return None

        box = QMessageBox(parent)
        box.setWindowTitle("Update available")
        box.setText("\n".join(lines))
        downloadBtn = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        laterBtn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(downloadBtn)
        box.exec()
        clicked = box.clickedButton()
        box.hide()
        box.close()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        if clicked is laterBtn:
            noteDeferredUpdate(ver)
            return None
        if clicked is downloadBtn:
            return info
        return None

    picked = _holdUpdatePrompt(_show)
    if picked:
        _downloadAndOfferApply(parent, picked)


def _downloadAndOfferApply(parent, info: dict) -> None:
    from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QApplication, QMessageBox, QDialog, QVBoxLayout, QLabel,
        QProgressBar, QPushButton,
    )

    global _updatePromptOpen
    _updatePromptOpen = True
    released = {"done": False}

    def _releasePrompt():
        global _updatePromptOpen
        if released["done"]:
            return
        released["done"] = True
        _updatePromptOpen = False

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
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateDownloadProgress = progress  # type: ignore[attr-defined]

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
            except Exception as e:
                Logic.logException("download worker failed", e)
                path = None
            self.signals.done.emit(path)

    def onDone(path):
        try:
            _finishDownload(path)
        finally:
            _releasePrompt()

    def _finishDownload(path):
        progress.hide()
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
                "Hit Restart to update, or close this window to restart later."
            )
            restartBtn = box.addButton("Restart", QMessageBox.ButtonRole.AcceptRole)
            laterBtn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(restartBtn)
            box.exec()
            clicked = box.clickedButton()
            box.hide()
            box.close()
            if clicked is restartBtn:
                if not spawnAppImageReplaceAndExit(Path(path), parent):
                    QMessageBox.warning(
                        parent,
                        "Update",
                        "Could not start applyUpdate.\n"
                        "Try again from Help / the update prompt.",
                    )
            elif clicked is laterBtn:
                noteDeferredUpdate(info.get("version"))
            return

        if info.get("autoApply"):
            if not spawnApplyAndExit(parent):
                QMessageBox.warning(
                    parent,
                    "Update",
                    "Could not start applyUpdate.\n"
                    "Close Data Doctor and run applyUpdate.cmd from the install folder.",
                )
            return
        box = QMessageBox(parent)
        box.setWindowTitle("Download complete")
        box.setText(
            "Hit Restart to update, or close this window to restart later."
        )
        restartBtn = box.addButton("Restart", QMessageBox.ButtonRole.AcceptRole)
        laterBtn = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restartBtn)
        box.exec()
        clicked = box.clickedButton()
        box.hide()
        box.close()
        if clicked is restartBtn:
            if not spawnApplyAndExit(parent):
                QMessageBox.warning(
                    parent,
                    "Update",
                    "Could not start applyUpdate.\n"
                    "Close Data Doctor and run applyUpdate.cmd from the install folder.",
                )
        elif clicked is laterBtn:
            noteDeferredUpdate(info.get("version"))

    signals = _Signals()
    app = QApplication.instance()
    holder = parent or app
    if holder is not None:
        holder._updateDownloadSignals = signals  # type: ignore[attr-defined]
    signals.done.connect(onDone)
    try:
        progress.show()
        QThreadPool.globalInstance().start(_Worker(signals, info))
    except Exception:
        progress.hide()
        progress.close()
        _releasePrompt()
        raise
