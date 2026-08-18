#!/usr/bin/env python3
"""
Publish documentation/wiki/ to the GitHub wiki repo.

The live wiki is a separate git repo (DataDoctor.wiki.git), not a branch
of DataDoctor. This copies the working-tree wiki pages into a local clone
under .git/wiki-publish and pushes when they differ.

  python scripts/publishWiki.py
  python scripts/publishWiki.py --dry-run

Wired as the repo pre-push hook (scripts/hooks/pre-push) so Code-OSS Push
on this machine also updates https://github.com/S31F3R/DataDoctor/wiki
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

WIKI_REMOTE = "https://github.com/S31F3R/DataDoctor.wiki.git"
WIKI_BRANCH = "master"
SRC_REL = Path("documentation") / "wiki"


def repoRoot() -> Path:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"wiki: not inside a git repo: {r.stderr.strip()}")
    return Path(r.stdout.strip())


def git(args, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip() or f"git {' '.join(args)} failed"
        raise SystemExit(f"wiki: {msg}")
    return r


def log(msg: str) -> None:
    print(f"wiki: {msg}", flush=True)


def srcFiles(src: Path) -> list[Path]:
    files = []
    for p in src.iterdir():
        if p.is_file() and not p.name.startswith("."):
            files.append(p)
    return sorted(files, key=lambda p: p.name.lower())


def ensureClone(cache: Path, dryRun: bool) -> None:
    if (cache / ".git").is_dir():
        git(["remote", "set-url", "origin", WIKI_REMOTE], cwd=cache)
        fetch = git(["fetch", "origin", WIKI_BRANCH], cwd=cache, check=False)
        if fetch.returncode != 0:
            log("fetch failed; recloning wiki cache")
            if not dryRun:
                shutil.rmtree(cache)
            else:
                raise SystemExit(f"wiki: fetch failed: {(fetch.stderr or '').strip()}")
        else:
            git(["checkout", "-B", WIKI_BRANCH, f"origin/{WIKI_BRANCH}"], cwd=cache)
            git(["reset", "--hard", f"origin/{WIKI_BRANCH}"], cwd=cache)
            return

    if dryRun:
        log(f"would clone {WIKI_REMOTE} → {cache}")
        return
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        shutil.rmtree(cache)
    log(f"cloning {WIKI_REMOTE}")
    r = subprocess.run(
        ["git", "clone", "--branch", WIKI_BRANCH, WIKI_REMOTE, str(cache)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise SystemExit(f"wiki: clone failed: {(r.stderr or r.stdout or '').strip()}")


def syncTree(src: Path, cache: Path) -> None:
    incoming = {p.name: p for p in srcFiles(src)}
    for existing in list(cache.iterdir()):
        if existing.name == ".git" or existing.name.startswith("."):
            continue
        if existing.is_file() and existing.name not in incoming:
            existing.unlink()
        elif existing.is_dir():
            shutil.rmtree(existing)
    for name, srcPath in incoming.items():
        shutil.copy2(srcPath, cache / name)


def parentIdentity(root: Path) -> tuple[str, str]:
    name = git(["config", "user.name"], cwd=root, check=False).stdout.strip()
    email = git(["config", "user.email"], cwd=root, check=False).stdout.strip()
    if not name:
        name = "DataDoctor"
    if not email:
        email = "wiki@local"
    return name, email


def sourceLabel(root: Path) -> str:
    sha = git(["rev-parse", "--short", "HEAD"], cwd=root, check=False).stdout.strip()
    branch = git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd=root, check=False
    ).stdout.strip()
    parts = []
    if branch:
        parts.append(branch)
    if sha:
        parts.append(sha)
    return " ".join(parts) or "working tree"


def publish(dryRun: bool) -> int:
    root = repoRoot()
    src = root / SRC_REL
    if not src.is_dir():
        log(f"no {SRC_REL}/ — skip")
        return 0
    files = srcFiles(src)
    if not files:
        log(f"{SRC_REL}/ is empty — skip (will not wipe live wiki)")
        return 0

    cache = root / ".git" / "wiki-publish"
    ensureClone(cache, dryRun=dryRun)
    if dryRun and not (cache / ".git").is_dir():
        log(f"would copy {len(files)} page(s) and push if changed")
        return 0

    syncTree(src, cache)
    status = git(["status", "--porcelain"], cwd=cache)
    if not status.stdout.strip():
        log("already up to date")
        return 0

    log("pages differ from live wiki:")
    for line in status.stdout.rstrip().splitlines():
        print(f"  {line}", flush=True)

    if dryRun:
        log("dry-run: not committing or pushing")
        return 0

    name, email = parentIdentity(root)
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = name
    env["GIT_AUTHOR_EMAIL"] = email
    env["GIT_COMMITTER_NAME"] = name
    env["GIT_COMMITTER_EMAIL"] = email

    git(["add", "-A"], cwd=cache)
    msg = f"Sync wiki from DataDoctor ({sourceLabel(root)})"
    commit = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=cache,
        capture_output=True,
        text=True,
        env=env,
    )
    if commit.returncode != 0:
        raise SystemExit(f"wiki: commit failed: {(commit.stderr or commit.stdout or '').strip()}")

    log(f"pushing {WIKI_BRANCH} → origin")
    push = subprocess.run(
        ["git", "push", "origin", f"HEAD:{WIKI_BRANCH}"],
        cwd=cache,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        raise SystemExit(
            "wiki: push failed — DataDoctor push aborted so this is visible.\n"
            f"{(push.stderr or push.stdout or '').strip()}"
        )
    log("published https://github.com/S31F3R/DataDoctor/wiki")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change; do not commit or push",
    )
    parser.add_argument(
        "--from-hook",
        action="store_true",
        help="invoked by scripts/hooks/pre-push (no extra behavior)",
    )
    args = parser.parse_args()
    return publish(dryRun=args.dry_run)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
