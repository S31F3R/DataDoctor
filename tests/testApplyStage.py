# Windows apply stages python-embed and applyUpdate.cmd instead of replacing
# the copies this process is running from. Leftover packaged files are removed.
# Run from the repo root: python tests/testApplyStage.py

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "applyUpdate.py")
spec = importlib.util.spec_from_file_location("applyUpdate", SCRIPT)
applyUpdate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(applyUpdate)


def fail(name, detail):
    print(f"FAIL {name}: {detail}")
    return 1


def writeFile(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main():
    errors = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        live = root / "pythonFiles" / "python-embed"
        src = root / "payload" / "python-embed"
        writeFile(live / "python.exe", "live")
        writeFile(live / "pythonw.exe", "live")
        writeFile(src / "python.exe", "new")
        writeFile(src / "pythonw.exe", "new")

        staged = applyUpdate.stagePythonEmbed(src, live, inUse=True)
        if staged.name != "python-embed.next":
            errors += fail("stage name", staged.name)
        if (live / "python.exe").read_text(encoding="utf-8") != "live":
            errors += fail("live embed", "live python.exe was replaced")
        if (staged / "python.exe").read_text(encoding="utf-8") != "new":
            errors += fail("next embed", "staged copy missing")

        replaced = applyUpdate.stagePythonEmbed(src, live, inUse=False)
        if replaced != live:
            errors += fail("direct target", replaced)
        if (live / "python.exe").read_text(encoding="utf-8") != "new":
            errors += fail("direct copy", "live embed was not replaced")

        cmd = root / "applyUpdate.cmd"
        writeFile(cmd, "old")
        target = applyUpdate.cmdWriteTarget(root, stageBesideLive=True)
        if target.name != "applyUpdate.cmd.new":
            errors += fail("cmd stage", target.name)
        direct = applyUpdate.cmdWriteTarget(root, stageBesideLive=False)
        if direct != cmd:
            errors += fail("cmd direct", direct)

        install = root / "install"
        writeFile(install / "applyUpdate.py", "root")
        writeFile(install / "pythonFiles" / "scripts" / "applyUpdate.py", "scripts")
        writeFile(install / "python-standalone" / "keep.txt", "mac cache copy")
        writeFile(install / "launcher" / "python-standalone" / "keep.txt", "packaging cache")
        writeFile(install / "python-3.14-embed-amd64.zip", "zip")
        applyUpdate.cleanupPackagedLeftovers(install)
        if (install / "applyUpdate.py").exists():
            errors += fail("root script", "still present")
        if not (install / "pythonFiles" / "scripts" / "applyUpdate.py").is_file():
            errors += fail("scripts copy", "removed the scripts copy")
        if (install / "python-standalone").exists():
            errors += fail("standalone", "install copy still present")
        if not (install / "launcher" / "python-standalone" / "keep.txt").is_file():
            errors += fail("mac cache", "packaging cache was removed")
        if (install / "python-3.14-embed-amd64.zip").exists():
            errors += fail("embed zip", "still at install root")

        updates = install / "updates"
        updates.mkdir()
        windowsZip = updates / "DataDoctor-Windows-v1.zip"
        pythonZip = updates / "DataDoctor-Python-v1.zip"
        windowsZip.write_bytes(b"w")
        pythonZip.write_bytes(b"p")
        os.utime(pythonZip, (1, 200))
        os.utime(windowsZip, (1, 100))
        writeFile(install / "Data Doctor.exe", "exe")
        picked = applyUpdate.pickUpdateZip(install, install / "pythonFiles")
        if picked is None or "windows" not in picked.name.lower():
            errors += fail("pick windows", picked)
        (install / "Data Doctor.exe").unlink()
        writeFile(install / "pythonFiles" / "python-embed" / "pythonw.exe", "py")
        picked = applyUpdate.pickUpdateZip(install, install / "pythonFiles")
        if picked is None or "python" not in picked.name.lower():
            errors += fail("pick python", picked)
        exe = install / "pythonFiles" / "python-embed" / "python.exe"
        if not applyUpdate.interpreterInside(exe.parent, str(exe)):
            errors += fail("interpreter", exe)
        if applyUpdate.interpreterInside(install / "updates", str(exe)):
            errors += fail("outside", exe)

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
