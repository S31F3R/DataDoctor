#!/usr/bin/env python3
"""
Build every release asset this host can produce, optionally upload to GitHub.

Version lives in core/Version.py (About reads that — not winAbout.ui).
Auto-update matches GitHub Release tags + asset names from this script.

  python scripts/publishRelease.py
  python scripts/publishRelease.py --channel published --build-only
  python scripts/publishRelease.py --channel rc --number 1 --upload
  python scripts/publishRelease.py --channel beta --number 1 --dry-run

What this Linux machine can build
---------------------------------
  YES  DataDoctor-Python-vX.Y.Z.zip     update payload (Windows applyUpdate)
  YES  DataDoctor-Windows-vX.Y.Z.zip    first-install zip (uses repo launcher exe)
                                        always --skip-venv here (Linux venv is useless)
  YES  DataDoctor-<arch>-vX.Y.Z.AppImage  this CPU/glibc only (needs PyInstaller)
  YES  DataDoctor-macOS-vX.Y.Z.zip      portable .command zip (--skip-venv)
  NO   native macOS .app                must run packageMac.py --app on a Mac
  NO   other-arch AppImage              build on that arch
  NO   rebuild Data Doctor.exe          already shipped under launcher/

Uploading a release is a GitHub API call (not git push). Token from
GITHUB_TOKEN / GH_TOKEN, `gh auth token`, or this machine's git credential.
The token needs `repo` (or Releases write) on S31F3R/DataDoctor.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Allow `from core.Version import …` when run from project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import Version  # noqa: E402

REPO = Version.GITHUB_REPO
VERSION_PATH = ROOT / "core" / "Version.py"


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if not raw and default is not None:
        return default
    return raw


def askYes(prompt: str, defaultYes: bool = True) -> bool:
    hint = "Y/n" if defaultYes else "y/N"
    raw = input(f"{prompt} [{hint}]: ").strip().lower()
    if not raw:
        return defaultYes
    return raw in ("y", "yes")


def baseTriple(version: str) -> str:
    parsed = Version.parseVersion(version)
    if parsed is None:
        die(f"unparseable version in Version.py: {version!r}")
    major, minor, patch, _pre = parsed
    return f"{major}.{minor}.{patch}"


def preKindAndNumber(version: str) -> tuple[str | None, int | None]:
    parsed = Version.parseVersion(version)
    if parsed is None or parsed[3] is None:
        return None, None
    parts = parsed[3]
    # (('rc',) style via parseVersion: letters → (1, 'rc'), digits → (0, n))
    name = None
    number = None
    for kind, val in parts:
        if kind == 1 and val in ("rc", "beta"):
            name = val
        elif kind == 0 and isinstance(val, int):
            number = val
    return name, number


def resolveVersion(channel: str, number: int | None, writeFile: bool, yes: bool) -> str:
    current = Version.displayVersion()
    base = baseTriple(current)
    kind, existingN = preKindAndNumber(current)

    if channel == "published":
        target = base
        if current != target and not yes:
            log(f"Version.py is {current!r}; published release will use {target!r}")
            if not askYes("Strip pre-release suffix and write Version.py?", True):
                die("aborted")
    elif channel in ("rc", "beta"):
        n = number
        if n is None:
            if kind == channel and existingN is not None:
                n = existingN + 1
            else:
                n = 1
            if not yes:
                raw = ask(f"{channel.upper()} number", str(n))
                try:
                    n = int(raw)
                except ValueError:
                    die(f"not a number: {raw!r}")
        if n < 1:
            die("pre-release number must be >= 1")
        target = f"{base}-{channel}.{n}"
    else:
        die(f"unknown channel {channel!r} (use published / rc / beta)")

    parsed = Version.parseVersion(target)
    if parsed is None:
        die(f"resolved version is not valid semver: {target!r}")

    if target != current:
        log(f"Version.py {current} → {target}")
        if writeFile:
            setVersionFile(target)
            # Keep in-memory copy in sync for later displayVersion calls
            Version.VERSION = target
        else:
            log("Version.py not written (--dry-run)")
    else:
        log(f"Version.py already {target}")
    return target


def setVersionFile(version: str) -> None:
    text = VERSION_PATH.read_text(encoding="utf-8")
    new, n = re.subn(
        r'^VERSION\s*=\s*"[^"]*"',
        f'VERSION = "{version}"',
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        die("could not find VERSION = \"...\" in core/Version.py")
    VERSION_PATH.write_text(new, encoding="utf-8")
    log(f"Wrote {VERSION_PATH.relative_to(ROOT)} VERSION = {version!r}")


def hostArch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine in ("armv7l", "armhf"):
        return "armhf"
    if machine in ("i386", "i686", "x86"):
        return "i686"
    return machine or "unknown"


def plannedAssets(version: str, skipAppImage: bool) -> list[dict]:
    """Describe what we will try to build on this host."""
    tag = f"v{version}"
    arch = hostArch()
    system = platform.system()
    items = [
        {
            "key": "python",
            "ok": True,
            "label": "Python zip (update payload)",
            "script": "scripts/packagePython.py",
            "args": [],
            "out": ROOT / "dist" / f"DataDoctor-Python-{tag}.zip",
            "assetName": f"DataDoctor-Python-{tag}.zip",
        },
        {
            "key": "windows",
            "ok": True,
            "label": "Windows launcher zip (--skip-venv)",
            "script": "scripts/packageWindows.py",
            "args": ["--skip-venv"],
            "out": ROOT / "dist" / f"DataDoctor-Windows-{tag}.zip",
            "assetName": f"DataDoctor-Windows-{tag}.zip",
        },
        {
            "key": "appimage",
            "ok": system == "Linux" and not skipAppImage,
            "skipReason": (
                "not Linux" if system != "Linux"
                else "--skip-appimage" if skipAppImage
                else None
            ),
            "label": f"AppImage ({arch})",
            "script": "scripts/packageAppImage.py",
            "args": [],
            "out": ROOT / "dist" / f"DataDoctor-{arch}-{tag}.AppImage",
            "assetName": f"DataDoctor-{arch}-{tag}.AppImage",
        },
        {
            "key": "macos",
            "ok": True,
            "label": "macOS portable zip (--skip-venv, no .app)",
            "script": "scripts/packageMac.py",
            "args": ["--skip-venv"],
            "out": ROOT / "dist" / f"DataDoctor-macOS-{tag}.zip",
            "assetName": f"DataDoctor-macOS-{tag}.zip",
        },
    ]
    return items


def printPlan(channel: str, version: str, items: list[dict]) -> None:
    log("")
    log(f"Host:    {platform.system()} {platform.machine()}")
    log(f"Channel: {channel}")
    log(f"Version: {version}")
    log(f"Tag:     v{version}")
    log(f"Pre:     {channel != 'published'}  (GitHub Pre-release checkbox)")
    log("")
    log("Assets:")
    for it in items:
        if it["ok"]:
            log(f"  BUILD  {it['label']}")
            log(f"         → {it['out'].name}")
        else:
            log(f"  SKIP   {it['label']}  ({it.get('skipReason') or 'unavailable'})")
    log("")
    log("Cannot build here (need another machine):")
    log("  - native macOS .app  (python scripts/packageMac.py --app on a Mac)")
    log("  - AppImage for a different CPU")
    log("  - rebuild of launcher/Data Doctor.exe  (already in the repo)")
    log("")


def runPackager(it: dict, dryRun: bool) -> Path | None:
    out = it["out"]
    cmd = [sys.executable, str(ROOT / it["script"]), *it["args"], "--out", str(out)]
    if dryRun:
        log(f"dry-run: {' '.join(cmd)}")
        return out
    log(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        die(f"{it['script']} failed with exit {r.returncode}")
    if not out.is_file():
        die(f"{it['script']} reported success but {out} is missing")
    mb = out.stat().st_size / (1024 * 1024)
    log(f"  wrote {out} ({mb:.1f} MB)")
    return out


def gitCurrentBranch() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return (r.stdout or "").strip() or "HEAD"


def gitCredentialToken() -> str | None:
    r = subprocess.run(
        ["git", "credential", "fill"],
        cwd=ROOT,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    for line in (r.stdout or "").splitlines():
        if line.startswith("password="):
            secret = line.split("=", 1)[1].strip()
            return secret or None
    return None


def githubToken() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    gh = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
    )
    if gh.returncode == 0 and (gh.stdout or "").strip():
        return gh.stdout.strip()
    return gitCredentialToken()


def apiJson(method: str, url: str, token: str, body=None, raw=False):
    data = None
    headers = {
        "User-Agent": f"DataDoctor-publish/{Version.displayVersion()}",
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None and not raw:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw:
        data = body
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = resp.read()
            if not payload:
                return {}
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        die(f"GitHub API {method} {url} → HTTP {e.code}\n{err}")


def createRelease(token: str, version: str, channel: str, target: str, notes: str) -> dict:
    tag = f"v{version}"
    url = f"https://api.github.com/repos/{REPO}/releases"
    body = {
        "tag_name": tag,
        "name": version,
        "body": notes,
        "draft": False,
        "prerelease": channel != "published",
        "target_commitish": target,
    }
    log(f"Creating GitHub release {tag} on {target} (prerelease={body['prerelease']})")
    return apiJson("POST", url, token, body)


def uploadAsset(token: str, release: dict, path: Path, assetName: str) -> None:
    uploadTmpl = release.get("upload_url") or ""
    # upload_url looks like https://uploads.github.com/.../assets{?name,label}
    base = uploadTmpl.split("{", 1)[0]
    url = base + "?" + urllib.parse.urlencode({"name": assetName})
    data = path.read_bytes()
    headers = {
        "User-Agent": f"DataDoctor-publish/{Version.displayVersion()}",
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(data)),
        "X-GitHub-Api-Version": "2022-11-28",
    }
    log(f"  uploading {assetName} ({len(data) / (1024 * 1024):.1f} MB)")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        die(f"upload {assetName} failed HTTP {e.code}\n{err}")


def defaultNotes(version: str, channel: str, files: list[Path]) -> str:
    lines = [
        f"Data Doctor {version}",
        "",
        f"Channel: {channel}",
        "",
        "Assets in this release:",
    ]
    for p in files:
        lines.append(f"- `{p.name}`")
    lines.extend([
        "",
        "Windows users: for an existing launcher install, drop the `DataDoctor-Python-*.zip` "
        "into `Update\\` and run `applyUpdate.cmd`.",
        "Linux: download the AppImage for your CPU.",
        "",
        "See the [wiki](https://github.com/S31F3R/DataDoctor/wiki/Updates-and-Releases).",
    ])
    return "\n".join(lines)


def parseArgs() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build Data Doctor release assets and optionally publish to GitHub"
    )
    p.add_argument(
        "--channel",
        choices=("published", "rc", "beta"),
        default=None,
        help="published = Version.py triple; rc/beta append -rc.N / -beta.N",
    )
    p.add_argument(
        "--number",
        type=int,
        default=None,
        help="N in -rc.N or -beta.N (default: 1, or last+1 if Version.py already matches)",
    )
    p.add_argument(
        "--upload",
        action="store_true",
        help="create the GitHub Release and attach built assets",
    )
    p.add_argument(
        "--build-only",
        dest="buildOnly",
        action="store_true",
        help="build assets, do not upload (default unless --upload)",
    )
    p.add_argument(
        "--dry-run",
        dest="dryRun",
        action="store_true",
        help="print the plan; do not write Version.py, build, or upload",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="do not prompt (use flags / defaults)",
    )
    p.add_argument(
        "--skip-appimage",
        dest="skipAppImage",
        action="store_true",
        help="skip the PyInstaller AppImage (slow)",
    )
    p.add_argument(
        "--target",
        default=None,
        help="git branch or SHA the GitHub tag should point at (default: current branch)",
    )
    p.add_argument(
        "--notes",
        default=None,
        help="release notes file path (default: generated stub)",
    )
    return p.parse_args()


def main() -> int:
    args = parseArgs()
    if not (ROOT / "DataDoctor.py").is_file():
        die("run from the DataDoctor project (DataDoctor.py missing)")

    channel = args.channel
    if channel is None:
        if args.yes:
            die("--channel is required with --yes")
        log("Release type:")
        log("  published  — tag vMAJOR.MINOR.PATCH from Version.py (stable channel)")
        log("  rc         — tag vMAJOR.MINOR.PATCH-rc.N  (GitHub Pre-release)")
        log("  beta       — tag vMAJOR.MINOR.PATCH-beta.N (GitHub Pre-release)")
        channel = ask("Channel (published / rc / beta)", "published").lower()
        if channel in ("release", "stable", "final"):
            channel = "published"
        if channel not in ("published", "rc", "beta"):
            die(f"unknown channel {channel!r}")

    writeFile = not args.dryRun
    version = resolveVersion(channel, args.number, writeFile=writeFile, yes=args.yes)
    items = plannedAssets(version, skipAppImage=args.skipAppImage)
    printPlan(channel, version, items)

    if args.dryRun:
        log("dry-run: stopping before build / upload")
        return 0

    if not args.yes and not askYes("Build the BUILD assets above?", True):
        die("aborted")

    built: list[tuple[dict, Path]] = []
    for it in items:
        if not it["ok"]:
            continue
        path = runPackager(it, dryRun=False)
        if path is not None:
            built.append((it, path))

    if not built:
        die("nothing was built")

    log("")
    log("Built:")
    for it, path in built:
        log(f"  {path}")

    doUpload = args.upload and not args.buildOnly
    if not args.upload and not args.buildOnly and not args.yes:
        doUpload = askYes("Create GitHub Release and upload these files?", False)

    if not doUpload:
        log("Skipping GitHub upload. Files are in dist/.")
        log("Upload later with: python scripts/publishRelease.py --channel "
            f"{channel} --yes --upload --skip-appimage")
        log("(re-run will rebuild; or attach dist/ files in the GitHub UI)")
        return 0

    token = githubToken()
    if not token:
        die(
            "no GitHub token. Set GITHUB_TOKEN, run `gh auth login`, "
            "or use a git credential that is a PAT with repo scope."
        )

    target = args.target or gitCurrentBranch()
    if not args.yes:
        target = ask("Tag which branch / commit?", target)

    if args.notes:
        notes = Path(args.notes).read_text(encoding="utf-8")
    else:
        notes = defaultNotes(version, channel, [p for _, p in built])

    release = createRelease(token, version, channel, target, notes)
    html = release.get("html_url") or ""
    for it, path in built:
        uploadAsset(token, release, path, it["assetName"])
    log(f"Published {html}")
    log("Stable users see this only if it is NOT a Pre-release.")
    log("Beta-channel users also see -rc / -beta / Pre-release tags.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
