#!/usr/bin/env python3
"""
Build every release asset this host can produce, optionally upload to GitHub.

Version lives in core/Version.py (About reads that — not winAbout.ui).
Auto-update matches GitHub Release tags + asset names from this script.

  python scripts/publishRelease.py
  python scripts/publishRelease.py --channel rc --number 2.5 --upload --yes
  python scripts/publishRelease.py --channel published --upload --yes
  python scripts/publishRelease.py --channel published --build-only
  python scripts/publishRelease.py --channel beta --number 1 --dry-run

--yes skips every prompt and tags/pushes the branch you are on.
Without --yes, "Tag which branch / commit?" defaults to that branch (Enter).

Release notes: documentation/releases/vX.Y.Z.md (created if missing).
That file is the GitHub Release body. Version.py is committed when it changes.
A published X.Y.Z also folds documentation/test.txt Confirmed titles into
## Changes when they were missed in Working Notes / rc-beta notes, then
clears Confirmed (those tests are the bug/beta cycle, not a forever list).

Order the updater uses: published > rc > beta (same X.Y.Z).
  3.0.0 > 3.0.0-rc.2.1 > 3.0.0-rc.2 > 3.0.0-beta.4
Older GitHub Releases (e.g. rc.1) stay up until deleted on the website.

What this Linux machine can build
---------------------------------
  YES  DataDoctor-Python-vX.Y.Z.zip     code update (already on python-embed)
  YES  DataDoctor-Windows-vX.Y.Z.zip    first install + 3.0.x launcher hop
                                        (python-embed 3.14; --skip-venv is a no-op)
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
NOTES_DIR = ROOT / "documentation" / "releases"
WORKING_NOTES = ROOT / "documentation" / "Working Notes.txt"
TEST_FILE = ROOT / "documentation" / "test.txt"
WORKING_NOTES_STUB = (
    "Working Notes\n"
    "=============\n"
    "Scratch file for unreleased changes. Do not create vVERSION.md here —\n"
    "the version is unknown until publish (rc.N, beta.N, or full vX.Y.Z).\n"
    "\n"
    "Write one bullet per change (bug fix, feature, or TASK). Include a\n"
    "GitHub issue number when there is one.\n"
    "\n"
    "publishRelease.py copies these bullets under ## Changes in\n"
    "documentation/releases/vVERSION.md (no Working Notes heading), then\n"
    "resets this file to this template.\n"
    "\n"
)


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


_PRE_NUM_RE = re.compile(r"^\d+(?:\.\d+)*$")


def preKindAndNumber(version: str) -> tuple[str | None, str | None]:
    """('rc', '2.1') from 3.0.0-rc.2.1."""
    parsed = Version.parseVersion(version)
    if parsed is None or parsed[3] is None:
        return None, None
    name = None
    nums: list[str] = []
    for kind, val in parsed[3]:
        if kind == 1 and val in ("rc", "beta"):
            name = val
        elif kind == 0:
            nums.append(str(val))
    return name, ".".join(nums) if nums else None


def incrementPreNumber(num: str) -> str:
    parts = num.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def resolveVersion(channel: str, number: str | None, writeFile: bool, yes: bool) -> str:
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
        n = (number or "").strip() if number else None
        if not n:
            if kind == channel and existingN:
                n = incrementPreNumber(existingN)
            else:
                n = "1"
            if not yes:
                n = ask(f"{channel.upper()} number (e.g. 2 or 2.1)", n)
        if not _PRE_NUM_RE.match(n):
            die(f"pre-release number must look like 1 or 2.1, not {n!r}")
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


def notesPathFor(version: str) -> Path:
    return NOTES_DIR / f"v{version}.md"


def notesTemplate(version: str, channel: str) -> str:
    return (
        f"# Data Doctor {version}\n"
        f"\n"
        f"Channel: {channel}\n"
        f"\n"
        f"## Changes\n"
        f"\n"
        f"- \n"
        f"\n"
        f"## Notes\n"
        f"\n"
        f"Windows: already on python-embed → `DataDoctor-Python-*.zip` + "
        f"`applyUpdate.cmd`. Coming from 3.0.x → `DataDoctor-Windows-*.zip`, "
        f"close the app, then `applyUpdate.cmd` (replaces the launcher).\n"
    )


def extractChangesBullets(mdText: str) -> list[str]:
    """## Changes bullets from a vVERSION.md (skip empty '- ' placeholders)."""
    if not mdText:
        return []
    lines = mdText.splitlines()
    bullets: list[str] = []
    inChanges = False
    for raw in lines:
        stripped = raw.rstrip()
        s = stripped.strip()
        if s.startswith("## "):
            heading = s[3:].strip().lower()
            if heading == "changes":
                inChanges = True
                continue
            if inChanges:
                break
            continue
        if not inChanges:
            continue
        if not s:
            if bullets:
                bullets.append(stripped)
            continue
        if s == "-" or s.lstrip("-").strip() == "":
            continue
        if s.startswith("-"):
            bullets.append(stripped if stripped.startswith("-") else f"- {s}")
        elif bullets:
            bullets.append(stripped)
    while bullets and not bullets[-1].strip():
        bullets.pop()
    return bullets


def _bulletKey(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip().lower())


def compilePreReleaseNotes(triple: str) -> str:
    """
    Merge ## Changes from v{triple}-rc.* and v{triple}-beta.* (oldest first).
    Used when publishing the final X.Y.Z and Working Notes is empty.
    """
    if not NOTES_DIR.is_dir():
        return ""
    paths = [
        p
        for p in NOTES_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".md"
    ]
    pre: list[tuple] = []
    for p in paths:
        stem = p.stem
        if not stem.startswith("v"):
            continue
        ver = stem[1:]
        parsed = Version.parseVersion(ver)
        if parsed is None or parsed[3] is None:
            continue
        maj, minor, patch, _pre = parsed
        if f"{maj}.{minor}.{patch}" != triple:
            continue
        pre.append((Version.versionKey(parsed), p))
    pre.sort(key=lambda t: t[0])
    seen: set[str] = set()
    out: list[str] = []
    for _key, p in pre:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for b in extractChangesBullets(text):
            k = _bulletKey(b)
            isCont = bool(out) and not b.lstrip().startswith("-")
            if not isCont:
                if not k or k in seen:
                    continue
                seen.add(k)
                out.append(b if b.startswith("-") else f"- {b}")
            else:
                out.append(b)
    if not out:
        return ""
    return "\n".join(out) + "\n"


def workingNotesBody() -> str:
    """
    Change bullets from documentation/Working Notes.txt.

    The file is a scratch pad (title + instructions + bullets). Only the
    bullets (and wrapped continuation lines) go under ## Changes in the
    versioned .md — never the 'Working Notes' heading.
    """
    if not WORKING_NOTES.is_file():
        return ""
    text = WORKING_NOTES.read_text(encoding="utf-8")
    bullets: list[str] = []
    started = False
    for raw in text.splitlines():
        stripped = raw.rstrip()
        s = stripped.strip()
        if not started:
            if s.startswith("-") and s.lstrip("-").strip():
                started = True
                bullets.append(stripped if stripped.startswith("-") else f"- {s}")
            continue
        if s.lower() == "working notes":
            continue
        if s and set(s) <= {"=", "-"}:
            continue
        bullets.append(stripped)
    while bullets and not bullets[-1].strip():
        bullets.pop()
    if not bullets:
        return ""
    return "\n".join(bullets) + "\n"


def clearWorkingNotes() -> None:
    WORKING_NOTES.parent.mkdir(parents=True, exist_ok=True)
    WORKING_NOTES.write_text(WORKING_NOTES_STUB, encoding="utf-8")
    log(f"Cleared {WORKING_NOTES.relative_to(ROOT)}")


_TEST_HEADING_RE = re.compile(
    r"^(Current Tests|Confirmed|Deferred / known)\s*$", re.I
)
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "vs", "no", "not", "is", "are", "be", "from", "into", "via", "per",
    "as", "at", "by", "this", "that", "then", "when", "after", "before",
}


def confirmedTestTitles() -> list[str]:
    """One-line titles from test.txt Confirmed (`[x] Title`)."""
    if not TEST_FILE.is_file():
        return []
    titles: list[str] = []
    inConfirmed = False
    for raw in TEST_FILE.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        m = _TEST_HEADING_RE.match(s)
        if m:
            inConfirmed = m.group(1).lower() == "confirmed"
            continue
        if not inConfirmed:
            continue
        if s and set(s) <= {"-", "="}:
            continue
        hit = re.match(r"^\[x\]\s+(.+)$", s, re.I)
        if hit:
            title = hit.group(1).strip()
            if title:
                titles.append(title)
    return titles


def clearConfirmedTests() -> None:
    """Keep Current Tests and Deferred; empty the Confirmed list."""
    if not TEST_FILE.is_file():
        return
    lines = TEST_FILE.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    inConfirmed = False
    wroteRule = False
    for raw in lines:
        s = raw.strip()
        m = _TEST_HEADING_RE.match(s)
        if m:
            name = m.group(1).lower()
            if inConfirmed and not wroteRule:
                out.append("")
                wroteRule = True
            inConfirmed = name == "confirmed"
            out.append(raw)
            continue
        if inConfirmed:
            if s and set(s) <= {"-", "="}:
                out.append(raw)
                if not wroteRule:
                    out.append("")
                    wroteRule = True
            continue
        out.append(raw)
    if inConfirmed and not wroteRule:
        out.append("")
    while out and not out[-1].strip():
        out.pop()
    out.append("")
    TEST_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        rel = TEST_FILE.relative_to(ROOT)
    except ValueError:
        rel = TEST_FILE
    log(f"Cleared Confirmed tests in {rel}")


def _normBullet(line: str) -> str:
    s = (line or "").strip()
    if s.startswith("-"):
        s = s[1:].strip()
    s = re.sub(r"^\[x\]\s*", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).lower()


def _coreTitle(line: str) -> str:
    """Drop parentheticals so 'Foo 3.14 (fresh zip)' matches notes about Foo 3.14."""
    s = _normBullet(line)
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 1 and t not in _STOP_WORDS
    ]


def _tokenHit(needle: str, hay: list[str]) -> bool:
    for x in hay:
        if needle == x or needle.startswith(x) or x.startswith(needle):
            return True
    return False


def _overlapNeed(nTokens: int) -> int:
    if nTokens <= 1:
        return nTokens
    if nTokens <= 3:
        return 2
    return max(3, int(round(0.55 * nTokens)))


def titleCoveredBy(title: str, bullets: list[str]) -> bool:
    """True if an existing change bullet already describes this test title."""
    nt = _coreTitle(title)
    if not nt:
        return True
    tt = _tokens(nt)
    full = _normBullet(title)
    for b in bullets:
        nb = _normBullet(b)
        if not nb:
            continue
        cb = _coreTitle(b)
        if nt == nb or nt == cb or nt in nb or nt in cb:
            return True
        if len(nb) >= 12 and (nb in full or nb in nt):
            return True
        bt = _tokens(nb)
        if not tt or not bt:
            continue
        hits = sum(1 for t in tt if _tokenHit(t, bt))
        if hits >= _overlapNeed(len(tt)):
            return True
    return False


def otherPublishedChangeBullets(version: str) -> list[str]:
    """## Changes from earlier published (non-rc/beta) notes, not this triple."""
    if not NOTES_DIR.is_dir():
        return []
    triple = baseTriple(version)
    out: list[str] = []
    for p in NOTES_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() != ".md":
            continue
        stem = p.stem
        if not stem.startswith("v"):
            continue
        ver = stem[1:]
        parsed = Version.parseVersion(ver)
        if parsed is None or parsed[3] is not None:
            continue
        other = f"{parsed[0]}.{parsed[1]}.{parsed[2]}"
        if other == triple:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        out.extend(extractChangesBullets(text))
    return out


def mergeBulletTexts(*blocks: str) -> str:
    """Concatenate bullet blocks, de-duped by normalized key (first wins)."""
    seen: set[str] = set()
    out: list[str] = []
    for block in blocks:
        if not (block or "").strip():
            continue
        for raw in block.splitlines():
            stripped = raw.rstrip()
            s = stripped.strip()
            if not s:
                if out and out[-1].strip():
                    out.append("")
                continue
            isCont = bool(out) and not s.startswith("-")
            if isCont:
                out.append(stripped)
                continue
            k = _bulletKey(s)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(stripped if stripped.startswith("-") else f"- {s}")
    while out and not out[-1].strip():
        out.pop()
    if not out:
        return ""
    return "\n".join(out) + "\n"


def confirmedMissedBullets(existing: list[str], version: str) -> list[str]:
    """Confirmed titles that are in neither this release's notes nor older published notes."""
    titles = confirmedTestTitles()
    if not titles:
        return []
    covered = list(existing) + otherPublishedChangeBullets(version)
    extras: list[str] = []
    seen: set[str] = set()
    for title in titles:
        k = _bulletKey(title)
        if not k or k in seen:
            continue
        if titleCoveredBy(title, covered):
            continue
        seen.add(k)
        extras.append(f"- {title}")
    return extras


def appendChangesBullets(md: str, extras: list[str]) -> str:
    """Insert extra `- ` lines at the end of ## Changes (before the next ##)."""
    if not extras:
        return md if (md or "").endswith("\n") else (md or "") + "\n"
    lines = (md or "").splitlines()
    changesStart: int | None = None
    changesEnd = len(lines)
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("## "):
            heading = s[3:].strip().lower()
            if heading == "changes":
                changesStart = i + 1
                continue
            if changesStart is not None:
                changesEnd = i
                break
    if changesStart is None:
        body = (md or "").rstrip() + "\n\n## Changes\n\n" + "\n".join(extras) + "\n"
        return body
    mid: list[str] = []
    for raw in lines[changesStart:changesEnd]:
        s = raw.strip()
        if not s:
            continue
        if s.startswith("-") and s.lstrip("-").strip() == "":
            continue
        mid.append(raw.rstrip())
    newLines = lines[:changesStart]
    if mid:
        newLines.append("")
        newLines.extend(mid)
    newLines.append("")
    newLines.extend(extras)
    newLines.append("")
    newLines.extend(lines[changesEnd:])
    while newLines and not newLines[-1].strip():
        newLines.pop()
    return "\n".join(newLines) + "\n"


def collectNotes(version: str, channel: str, files: list[Path], notesArg: str | None, yes: bool) -> str:
    """
    GitHub Release body comes from documentation/releases/vVERSION.md.
    --notes PATH overrides. Interactive run can type a few bullets first.

    If the versioned file is missing/empty, seed ## Changes from Working
    Notes bullets. For channel=published, also compile vX.Y.Z-rc.* /
    vX.Y.Z-beta.* for that triple (merged, de-duped) and fold in
    documentation/test.txt Confirmed titles that were missed in the notes
    (and not already shipped in an older published X.Y.Z).
    """
    dest = notesPathFor(version)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if notesArg:
        src = Path(notesArg)
        if not src.is_file():
            die(f"notes file not found: {src}")
        text = src.read_text(encoding="utf-8").strip() + "\n"
        dest.write_text(text, encoding="utf-8")
        log(f"Release notes copied to {dest.relative_to(ROOT)}")
        return text

    existing = ""
    if dest.is_file() and dest.stat().st_size > 0:
        existing = dest.read_text(encoding="utf-8")
    existingBullets = extractChangesBullets(existing)

    if existingBullets and channel != "published":
        log(f"Release notes: {dest.relative_to(ROOT)}")
        return existing

    if existingBullets:
        body = existing
        log(f"Release notes: {dest.relative_to(ROOT)}")
    else:
        working = workingNotesBody()
        compiled = ""
        if channel == "published":
            compiled = compilePreReleaseNotes(baseTriple(version))
        seed = mergeBulletTexts(working, compiled)
        if seed:
            sources = []
            if working:
                sources.append("Working Notes")
            if compiled:
                sources.append(f"rc/beta notes for {baseTriple(version)}")
            source = " + ".join(sources)
            body = (
                f"# Data Doctor {version}\n\n"
                f"Channel: {channel}\n\n"
                f"## Changes\n\n"
                f"{seed.rstrip()}\n\n"
                f"## Notes\n\n"
                f"Windows: already on python-embed → `DataDoctor-Python-*.zip` + "
                f"`applyUpdate.cmd`. Coming from 3.0.x → `DataDoctor-Windows-*.zip`, "
                f"close the app, then `applyUpdate.cmd` (replaces the launcher).\n"
            )
            dest.write_text(body, encoding="utf-8")
            log(f"Seeded {dest.relative_to(ROOT)} from {source}")
        else:
            extra = ""
            if not yes:
                log(f"No {dest.relative_to(ROOT)} yet. Type changes (empty line to finish).")
                lines = []
                while True:
                    try:
                        line = input("  - " if not lines else "    ")
                    except EOFError:
                        break
                    if not line.strip():
                        break
                    bullet = line.strip()
                    if not bullet.startswith("-"):
                        bullet = f"- {bullet}"
                    lines.append(bullet)
                extra = "\n".join(lines)
            body = notesTemplate(version, channel)
            if extra:
                body = body.replace("## Changes\n\n- \n", "## Changes\n\n" + extra + "\n")
            dest.write_text(body, encoding="utf-8")
            log(
                f"Wrote {dest.relative_to(ROOT)} — "
                f"edit that file next time to change GitHub notes"
            )

    if channel == "published":
        extras = confirmedMissedBullets(extractChangesBullets(body), version)
        nConfirmed = len(confirmedTestTitles())
        # First published after Confirmed was a forever-list can have dozens of
        # historical tests that were never in any vVERSION.md. Do not dump
        # those into this X.Y.Z. A normal bug/beta cycle is a short list.
        backlogLimit = 20
        if len(extras) > backlogLimit:
            log(
                f"Confirmed has {nConfirmed} titles; {len(extras)} are not in "
                f"this release or older published notes. Treating that as a "
                f"historical backlog (not folding into {version}). Confirmed "
                f"will still be cleared."
            )
            extras = []
        if extras:
            body = appendChangesBullets(body, extras)
            dest.write_text(body, encoding="utf-8")
            log(
                f"Added {len(extras)} Confirmed test(s) that were missing from "
                f"{dest.relative_to(ROOT)}"
            )
        elif nConfirmed:
            log(f"Confirmed tests: all {nConfirmed} already covered in notes")
        else:
            log("Confirmed tests: none listed")
    return body


def gitCommitVersion(version: str, extraPaths: list[Path] | None = None) -> None:
    """Commit Version.py (and notes) so the bump is not left unstaged."""
    paths = [VERSION_PATH]
    for p in extraPaths or []:
        if p is not None and p.is_file():
            paths.append(p)
    rels = []
    for p in paths:
        try:
            rels.append(str(p.relative_to(ROOT)))
        except ValueError:
            rels.append(str(p))
    add = subprocess.run(
        ["git", "add", "--"] + rels,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        log(f"WARN: git add failed: {(add.stderr or add.stdout or '').strip()}")
        return
    st = subprocess.run(
        ["git", "status", "--porcelain", "--"] + rels,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if not (st.stdout or "").strip():
        log("Version commit: nothing new to commit")
        return
    msg = f"Bump version to {version}"
    commit = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        log(f"WARN: git commit failed: {(commit.stderr or commit.stdout or '').strip()}")
        return
    log(f"Committed: {msg}")


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
            "label": "Windows launcher zip (python-embed 3.14)",
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
    # gh is optional — missing binary must not abort the upload
    try:
        gh = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
        )
        if gh.returncode == 0 and (gh.stdout or "").strip():
            return gh.stdout.strip()
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return gitCredentialToken()


def apiJson(method: str, url: str, token: str, body=None, raw=False, allowCodes=()):
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
        if e.code in allowCodes:
            try:
                e.read()
            except Exception:
                pass
            return None
        err = e.read().decode("utf-8", errors="replace")
        die(f"GitHub API {method} {url} → HTTP {e.code}\n{err}")


def getReleaseByTag(token: str, tag: str) -> dict | None:
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{urllib.parse.quote(tag)}"
    return apiJson("GET", url, token, allowCodes=(404,))


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


def ensureRelease(token: str, version: str, channel: str, target: str, notes: str) -> dict:
    """Create the release, or reuse it if this tag was already published."""
    tag = f"v{version}"
    existing = getReleaseByTag(token, tag)
    if existing:
        html = existing.get("html_url") or ""
        log(f"Release {tag} already exists — updating assets / notes")
        if html:
            log(f"  {html}")
        relId = existing.get("id")
        if relId and notes:
            apiJson(
                "PATCH",
                f"https://api.github.com/repos/{REPO}/releases/{int(relId)}",
                token,
                {
                    "body": notes,
                    "prerelease": channel != "published",
                    "name": version,
                },
            )
        return existing
    created = createRelease(token, version, channel, target, notes)
    if created:
        return created
    # Race or odd 422: fetch again
    again = getReleaseByTag(token, tag)
    if again:
        return again
    die(f"could not create or load release {tag}")


def deleteReleaseAsset(token: str, assetId: int) -> None:
    url = f"https://api.github.com/repos/{REPO}/releases/assets/{int(assetId)}"
    apiJson("DELETE", url, token)


def uploadAsset(token: str, release: dict, path: Path, assetName: str) -> None:
    assets = list(release.get("assets") or [])
    for asset in assets:
        if asset.get("name") == assetName and asset.get("id") is not None:
            log(f"  replacing existing {assetName}")
            deleteReleaseAsset(token, int(asset["id"]))
            release["assets"] = [a for a in assets if a.get("id") != asset.get("id")]
            break
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
        "Windows: already on python-embed, drop `DataDoctor-Python-*.zip` into `updates\\` "
        "and run `applyUpdate.cmd`. Coming from 3.0.x, use `DataDoctor-Windows-*.zip`, "
        "close Data Doctor, then run `applyUpdate.cmd` (replaces the launcher + Python 3.14).",
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
        help="published = Version.py triple; rc/beta append -rc.N / -beta.N (N can be 2.1)",
    )
    p.add_argument(
        "--number",
        default=None,
        help="N in -rc.N or -beta.N (1, 2, 2.1, …). Default: last+1 or 1",
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
        help="do not prompt (current branch, flags / defaults)",
    )
    p.add_argument(
        "--skip-appimage",
        dest="skipAppImage",
        action="store_true",
        help="skip the PyInstaller AppImage (slow)",
    )
    p.add_argument(
        "--skip-build",
        dest="skipBuild",
        action="store_true",
        help="do not run packagers; upload/reuse files already in dist/",
    )
    p.add_argument(
        "--target",
        default=None,
        help="git branch or SHA the GitHub tag should point at (default: current branch)",
    )
    p.add_argument(
        "--notes",
        default=None,
        help="release notes markdown file (default: documentation/releases/vVERSION.md)",
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

    notesEarly = collectNotes(version, channel, [], notesArg=args.notes, yes=args.yes)
    # Packaged release: clear Working Notes (seeded into vVERSION.md if needed).
    extraNotes = [notesPathFor(version)]
    if WORKING_NOTES.is_file() or workingNotesBody():
        clearWorkingNotes()
        extraNotes.append(WORKING_NOTES)
    if channel == "published" and TEST_FILE.is_file():
        clearConfirmedTests()
        extraNotes.append(TEST_FILE)
    gitCommitVersion(version, extraPaths=extraNotes)

    built: list[tuple[dict, Path]] = []
    if args.skipBuild:
        log("Skipping packagers (--skip-build); using existing dist/ files")
        for it in items:
            if not it["ok"]:
                continue
            if it["out"].is_file():
                mb = it["out"].stat().st_size / (1024 * 1024)
                log(f"  reuse {it['out']} ({mb:.1f} MB)")
                built.append((it, it["out"]))
            else:
                die(f"--skip-build but missing {it['out']}")
    else:
        if not args.yes and not askYes("Build the BUILD assets above?", True):
            die("aborted")
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
            f"{channel} --yes --upload --skip-build")
        log("(reuses dist/ files; or attach them in the GitHub UI)")
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

    # GitHub tags the remote branch. Push the version bump first so the
    # release points at Version.py that matches the assets.
    push = subprocess.run(
        ["git", "push", "origin", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        log(
            "WARN: git push failed (tag may point at the previous remote tip): "
            f"{(push.stderr or push.stdout or '').strip()}"
        )
    else:
        log(f"Pushed {target} to origin")

    notes = notesEarly
    release = ensureRelease(token, version, channel, target, notes)
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
