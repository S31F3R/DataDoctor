# A Windows launcher install asks for the Windows zip, not the Python zip.
# Run from the repo root: python tests/testUpdateAsset.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.Update import chooseAssetKind, resolveReleaseAsset


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def asset(name):
    return {"name": name, "browser_download_url": f"https://example.test/{name}"}


def main():
    errors = 0
    if chooseAssetKind("launcher", True) != "windows":
        errors += fail("exe", chooseAssetKind("launcher", True))
    if chooseAssetKind("launcher", False) != "launcher":
        errors += fail("dev", chooseAssetKind("launcher", False))
    if chooseAssetKind("appimage", False) != "appimage":
        errors += fail("appimage", chooseAssetKind("appimage", False))
    if chooseAssetKind("dev", False) != "launcher":
        errors += fail("source", chooseAssetKind("dev", False))

    both = [
        asset("DataDoctor-Python-v3.zip"),
        asset("DataDoctor-Windows-v3.zip"),
    ]
    got, kind, fellBack = resolveReleaseAsset(both, "windows", "launcher")
    if got["name"] != "DataDoctor-Windows-v3.zip" or kind != "windows" or fellBack:
        errors += fail("windows asset", (got, kind, fellBack))

    pythonOnly = [asset("DataDoctor-Python-v3.zip")]
    got, kind, fellBack = resolveReleaseAsset(pythonOnly, "windows", "launcher")
    if got["name"] != "DataDoctor-Python-v3.zip" or kind != "launcher" or not fellBack:
        errors += fail("fallback", (got, kind, fellBack))

    got, kind, fellBack = resolveReleaseAsset(pythonOnly, "launcher", "dev")
    if got["name"] != "DataDoctor-Python-v3.zip" or fellBack:
        errors += fail("python", (got, kind, fellBack))

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
