# Change-agent lookup collision retry. No database.
# Run from the repo root: python tests/test_uploadRetry.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.Upload import isChangeAgentLookupRace, retryChangeAgentRace


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def testDetect():
    race = RuntimeError(
        "ORA-00001: unique constraint (LCHDBA.IDX_REF_CHANGE_AGENT_LOOKUP) violated"
    )
    other = RuntimeError("ORA-00001: unique constraint (LCHDBA.SOME_OTHER) violated")
    if not isChangeAgentLookupRace(race):
        return fail("detect race", race)
    if isChangeAgentLookupRace(other):
        return fail("detect other", other)
    if isChangeAgentLookupRace(RuntimeError("ORA-01403: no data found")):
        return fail("detect nodata", "matched")
    return 0


def testRetry():
    calls = {"n": 0}
    pauses = []

    def action():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(
                "ORA-00001: unique constraint (LCHDBA.IDX_REF_CHANGE_AGENT_LOOKUP) violated"
            )
        return "ok"

    result = retryChangeAgentRace(action, attempts=4, pause=lambda s: pauses.append(s))
    if result != "ok" or calls["n"] != 3 or len(pauses) != 2:
        return fail("retry", (result, calls, pauses))

    def boom():
        raise RuntimeError("ORA-01403: no data found")

    try:
        retryChangeAgentRace(boom, attempts=4, pause=lambda s: None)
    except RuntimeError as e:
        if "ORA-01403" not in str(e):
            return fail("no retry", e)
    else:
        return fail("no retry", "did not raise")
    return 0


def main():
    errors = testDetect() + testRetry()
    if errors:
        print(f"{errors} failed")
        return 1
    print("upload retry checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
