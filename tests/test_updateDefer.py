# Later on an update stays quiet for that release. A newer beta still prompts.
# Run from the repo root: python tests/test_updateDefer.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import Config
from core.Update import noteDeferredUpdate, updatePromptDeferred
from core.Version import compareVersions


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def main():
    errors = 0
    if compareVersions("3.4.0-rc.1.1", "3.4.0-rc.1") <= 0:
        errors += fail("rc order", "rc.1.1 should be newer than rc.1")

    Config.skipUpdatePromptThisSession = False
    Config.dismissedUpdateVersion = None
    if updatePromptDeferred({"version": "3.4.0-rc.1.1", "prerelease": True}):
        errors += fail("fresh", "should prompt before Later")

    noteDeferredUpdate("3.4.0-rc.1")
    if not updatePromptDeferred({"version": "3.4.0-rc.1", "prerelease": True}):
        errors += fail("same", "Later should hide the same release")
    if updatePromptDeferred({"version": "3.4.0-rc.1.1", "prerelease": True}):
        errors += fail("newer beta", "a newer rc should still prompt")
    if not updatePromptDeferred(None):
        errors += fail("none", "no release should stay quiet after Later")

    if errors:
        print(f"{errors} failed")
        return 1
    print("update defer checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
