# Later on an update stays quiet for that release. A newer beta still prompts.
# Run from the repo root: python tests/test_updateDefer.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import Config
import core.Update as Update
from core.Update import noteDeferredUpdate, shouldShowUpdatePrompt, updatePromptDeferred
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

    newer = {"version": "3.4.0-rc.1.1", "prerelease": True}
    if not shouldShowUpdatePrompt(newer):
        errors += fail("show newer", "newer than Later should still show")
    Update._updatePromptOpen = True
    try:
        if shouldShowUpdatePrompt(newer):
            errors += fail("open window", "an open update window should block another prompt")
        calls = {"n": 0}

        def _count(*_a, **_k):
            calls["n"] += 1

        original = Update.runUpdateCheckUi
        Update.runUpdateCheckUi = _count
        try:
            Update._backgroundUpdateTick()
            if calls["n"]:
                errors += fail("tick while open", "background check should wait")
        finally:
            Update.runUpdateCheckUi = original
    finally:
        Update._updatePromptOpen = False
    if Update.updatePromptOpen():
        errors += fail("flag clear", "window flag should be clear after the prompt closes")
    if not shouldShowUpdatePrompt(newer):
        errors += fail("after close", "closing the window should allow a newer release")

    nested = {"ran": 0, "inner": 0}

    def _outer():
        nested["ran"] += 1
        if Update._holdUpdatePrompt(lambda: nested.__setitem__("inner", 1)) is not None:
            nested["inner"] = -1

    Update._holdUpdatePrompt(_outer)
    if nested["ran"] != 1 or nested["inner"]:
        errors += fail("second window", "a prompt already open should not open another")
    if Update.updatePromptOpen():
        errors += fail("flag leak", "the window flag should clear when the prompt closes")

    if errors:
        print(f"{errors} failed")
        return 1
    print("update defer checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
