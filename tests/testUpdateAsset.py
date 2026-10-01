# A Windows launcher install asks for the Windows zip, not the Python zip.
# Run from the repo root: python tests/testUpdateAsset.py

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pathlib import Path
import tempfile

from core.Update import (
    chooseAssetKind,
    launcherRestartScript,
    resolveReleaseAsset,
    windowsLauncherLeftovers,
    windowsLauncherRestartText,
)


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

    script = launcherRestartScript()
    if "tasklist" in script or "find " in script or "ping " in script:
        errors += fail("restart script", "still searches the process list or flashes ping")
    if "applyUpdate.cmd.new" not in script or "--finish-staged" not in script:
        errors += fail("restart script body", "missing rename or finish")
    if "LSS 8" not in script:
        errors += fail("restart retries", "retry is not bounded")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "applyUpdate.cmd.new").write_text("new", encoding="utf-8")
        embedNext = root / "pythonFiles" / "python-embed.next"
        embedNext.mkdir(parents=True)
        (embedNext / "python.exe").write_text("staged", encoding="utf-8")
        (root / "finishEmbedSwap.cmd").write_text("old", encoding="utf-8")
        items = windowsLauncherLeftovers(root)
        if "applyUpdate.cmd.new" not in items or "python-embed.next" not in items:
            errors += fail("leftovers", items)
        if "finishEmbedSwap.cmd" not in items:
            errors += fail("old helper", items)
        text = windowsLauncherRestartText(items)
        if "Restart" not in text or "Later" not in text:
            errors += fail("prompt", text)
        if "applyUpdate.cmd.new" not in text or "python-embed.next" not in text:
            errors += fail("prompt items", text)

        same = root / "same"
        same.mkdir()
        (same / "applyUpdate.cmd").write_text("same\r\n", encoding="utf-8", newline="")
        (same / "applyUpdate.cmd.new").write_text("same\r\n", encoding="utf-8", newline="")
        items = windowsLauncherLeftovers(same)
        if "applyUpdate.cmd.new" in items or (same / "applyUpdate.cmd.new").exists():
            errors += fail("same leftover", items)
        changed = root / "changed"
        changed.mkdir()
        (changed / "applyUpdate.cmd").write_text("old\r\n", encoding="utf-8", newline="")
        (changed / "applyUpdate.cmd.new").write_text("new\r\n", encoding="utf-8", newline="")
        items = windowsLauncherLeftovers(changed)
        if "applyUpdate.cmd.new" not in items or not (changed / "applyUpdate.cmd.new").is_file():
            errors += fail("changed leftover", items)

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
