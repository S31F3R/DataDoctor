# Linked HDB queries share one anchor, and each database gets its own sessions.
# Run from the repo root: python tests/testLinkedAnchor.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import core.USBR as USBR


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def main():
    errors = 0
    USBR.primaryDsn = None
    anchor = USBR.prepareLinkedAnchor(["uchdb2", "yaohdb"])
    if anchor != "uchdb2" or USBR.primaryDsn != "uchdb2":
        errors += fail("first linked", (anchor, USBR.primaryDsn))
    again = USBR.prepareLinkedAnchor(["lchdb"])
    if again != "uchdb2":
        errors += fail("sticky", again)

    USBR.primaryDsn = None
    isolated = USBR.prepareLinkedAnchor(["kbohdb", "cuhdb"])
    if isolated is not None or USBR.primaryDsn is not None:
        errors += fail("isolated", (isolated, USBR.primaryDsn))

    USBR.primaryDsn = None
    mixed = USBR.prepareLinkedAnchor(["USBR-KBOHDB", "USBR-YAOHDB", "lchdb"])
    if mixed != "yaohdb":
        errors += fail("skip isolated", mixed)

    if USBR.parallelSessionCap(1) != USBR.maxThreads:
        errors += fail("one db", USBR.parallelSessionCap(1))
    if USBR.parallelSessionCap(3) != max(4, USBR.maxThreads // 3):
        errors += fail("three db", USBR.parallelSessionCap(3))

    USBR.primaryDsn = None
    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
