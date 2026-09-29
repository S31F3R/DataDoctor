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

        same = root / "same"
        srcEmbed = same / "src"
        destEmbed = same / "pythonFiles" / "python-embed"
        writeFile(srcEmbed / "python.exe", "src")
        writeFile(srcEmbed / "pythonw.exe", "src")
        writeFile(srcEmbed / "python314.dll", "dll")
        writeFile(destEmbed / "python.exe", "keep")
        writeFile(destEmbed / "pythonw.exe", "keep")
        writeFile(destEmbed / "python314.dll", "dll")
        if not applyUpdate.embedAlreadyCurrent(srcEmbed, destEmbed):
            errors += fail("same python", applyUpdate.embedAbiTag(destEmbed))
        kept = applyUpdate.stageEmbedIfNeeded(srcEmbed, destEmbed, inUse=True)
        if kept != destEmbed:
            errors += fail("keep target", kept)
        if (destEmbed / "python.exe").read_text(encoding="utf-8") != "keep":
            errors += fail("kept embed", "live python was replaced")
        if (destEmbed.with_name("python-embed.next")).exists():
            errors += fail("same next", "staged a copy of the same Python")

        writeFile(srcEmbed / "python315.dll", "newer")
        (srcEmbed / "python314.dll").unlink()
        if applyUpdate.embedAlreadyCurrent(srcEmbed, destEmbed):
            errors += fail("newer python", "same tag")
        staged = applyUpdate.stageEmbedIfNeeded(srcEmbed, destEmbed, inUse=True)
        if staged.name != "python-embed.next":
            errors += fail("newer stage", staged.name)
        if (destEmbed / "python.exe").read_text(encoding="utf-8") != "keep":
            errors += fail("newer live", "replaced the running Python")

        finish = root / "finish"
        writeFile(finish / "applyUpdate.cmd", "old")
        writeFile(finish / "applyUpdate.cmd.new", "new")
        writeFile(finish / "applyUpdate.py", "root")
        writeFile(finish / "pythonFiles" / "scripts" / "applyUpdate.py", "scripts")
        writeFile(finish / "pythonFiles" / "python-embed.next" / "python.exe", "staged")
        writeFile(finish / "pythonFiles" / "python-embed" / "python.exe", "live")
        writeFile(finish / "finishEmbedSwap.cmd", "old helper")
        # This process is not inside the fake embed, so the swap can finish.
        rc = applyUpdate.finishStaged(finish)
        if rc != 0:
            errors += fail("finish rc", rc)
        if (finish / "applyUpdate.cmd.new").exists():
            errors += fail("finish cmd.new", "still staged")
        if (finish / "applyUpdate.cmd").read_text(encoding="utf-8") != "new":
            errors += fail("finish cmd", "old command still in place")
        if (finish / "pythonFiles" / "python-embed.next").exists():
            errors += fail("finish next", "staged Python still waiting")
        if (finish / "pythonFiles" / "python-embed" / "python.exe").read_text(encoding="utf-8") != "staged":
            errors += fail("finish embed", "staged Python was not swapped")
        if (finish / "applyUpdate.py").exists():
            errors += fail("finish root", "root applyUpdate.py still present")
        if (finish / "finishEmbedSwap.cmd").exists():
            errors += fail("finish helper", "old helper still present")

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
