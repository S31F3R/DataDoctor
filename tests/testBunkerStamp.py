# AppImage dictionary questions are once per packaged bunker, not every launch.
# Run from the repo root: python tests/testBunkerStamp.py

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.BunkerMerge import (
    fileSha256,
    filesIdentical,
    mergePromptDecision,
    writeMergedStamp,
)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def main():
    errors = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        packaged = tmp / "packaged.db"
        user = tmp / "user.db"
        stamp = tmp / "bunker.merged"
        packaged.write_bytes(b"packaged-v1")
        user.write_bytes(b"user-kept-names")

        if filesIdentical(packaged, user):
            errors += fail("different files", "hashed equal")
        copy = tmp / "copy.db"
        copy.write_bytes(packaged.read_bytes())
        if not filesIdentical(packaged, copy):
            errors += fail("same bytes", "hashed different")

        if mergePromptDecision(packaged, user, stamp) != "merge":
            errors += fail("first launch", mergePromptDecision(packaged, user, stamp))

        writeMergedStamp(packaged, stamp)
        if stamp.read_text(encoding="utf-8").strip() != fileSha256(packaged):
            errors += fail("stamp text", stamp.read_text(encoding="utf-8"))
        if mergePromptDecision(packaged, user, stamp) != "already":
            errors += fail("second launch", mergePromptDecision(packaged, user, stamp))

        user.write_bytes(packaged.read_bytes())
        if mergePromptDecision(packaged, user, stamp) != "identical":
            errors += fail("byte match", mergePromptDecision(packaged, user, stamp))

        packaged.write_bytes(b"packaged-v2")
        user.write_bytes(b"user-kept-names")
        if mergePromptDecision(packaged, user, stamp) != "merge":
            errors += fail("new package", mergePromptDecision(packaged, user, stamp))
        if stamp.read_text(encoding="utf-8").strip() == fileSha256(packaged):
            errors += fail("stamp rewritten", "new package updated the stamp early")

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
