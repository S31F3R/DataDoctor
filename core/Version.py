# Version.py
# Single source of truth for Data Doctor version (semver + optional pre-release).
#
# Scheme: MAJOR.MINOR.PATCH[-PRERELEASE]
#   0.0.1  bug fixes
#   0.1.0  minor / net feature
#   1.0.0  major
# Pre-release (beta / RC): 1.2.0-rc.1  or  1.2.0-beta.1
#   - Always sorts *before* the final 1.2.0
# GitHub: mark beta/RC releases as "Pre-release" so stable users skip them.

from __future__ import annotations
import re

# Bump this when cutting a release (tag should match: v3.0.0 or v3.0.0-rc.1)
VERSION = "3.0.0-rc.1"

# GitHub repo for release checks (owner/name)
GITHUB_REPO = "S31F3R/DataDoctor"

_PRE_RE = re.compile(
    r"^v?"
    r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?"
    r"$"
)


def displayVersion(version: str | None = None) -> str:
    """Human-facing version string (no leading v)."""
    v = (version or VERSION).strip()
    if v.lower().startswith("v"):
        v = v[1:]
    return v


def parseVersion(text: str):
    """
    Parse 'v1.2.3', '1.2.3-rc.1', '1.2.3-beta.2' →
    (major, minor, patch, pre_tuple_or_None)

    pre_tuple is comparable: ('rc', 1) or ('beta', 2).
    Final releases have pre=None and sort after any pre of the same triple.
    """
    if not text:
        return None
    s = str(text).strip()
    m = _PRE_RE.match(s)
    if not m:
        return None
    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    preRaw = m.group("pre")
    if not preRaw:
        return (major, minor, patch, None)
    parts = preRaw.lower().split(".")
    preParts = []
    for p in parts:
        if p.isdigit():
            preParts.append((0, int(p)))  # numbers sort before letters within segment
        else:
            # extract trailing digits: rc1 → ('rc', 1) style via split already
            preParts.append((1, p))
    return (major, minor, patch, tuple(preParts))


def versionKey(parsed):
    """
    Sort key: final release > any pre-release of same X.Y.Z.
    pre=None → (maj, min, pat, 1)  vs  pre present → (maj, min, pat, 0, preParts)
    """
    if parsed is None:
        return (0, 0, 0, 0)
    major, minor, patch, pre = parsed
    if pre is None:
        return (major, minor, patch, 1)
    return (major, minor, patch, 0, pre)


def compareVersions(a: str, b: str) -> int:
    """
    Compare version strings.
    Returns -1 if a < b, 0 if equal, 1 if a > b.
    Unparseable versions compare as equal to each other and less than valid ones.
    """
    pa, pb = parseVersion(a), parseVersion(b)
    if pa is None and pb is None:
        return 0
    if pa is None:
        return -1
    if pb is None:
        return 1
    ka, kb = versionKey(pa), versionKey(pb)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0


def isNewer(remote: str, local: str | None = None) -> bool:
    """True if remote version is strictly newer than local (default: VERSION)."""
    return compareVersions(remote, local or VERSION) > 0


def isPrereleaseVersion(text: str) -> bool:
    parsed = parseVersion(text)
    return parsed is not None and parsed[3] is not None
