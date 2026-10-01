# Windows apply stages python-embed and applyUpdate.cmd instead of replacing
# the copies this process is running from. Leftover packaged files are removed.
# Run from the repo root: python tests/testApplyStage.py

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
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

        current = root / "running-apply.py"
        current.write_bytes(b"print('installed')\n")
        pack = root / "DataDoctor-Windows-test.zip"
        with zipfile.ZipFile(pack, "w") as zf:
            zf.writestr("pythonFiles/scripts/applyUpdate.py", b"print('from zip')\n")
        if not applyUpdate.shouldReexecApplyScript(pack, current):
            errors += fail("reexec zip", "installed script would keep running")
        os.environ["DD_APPLY_REEXEC"] = "1"
        try:
            if applyUpdate.shouldReexecApplyScript(pack, current):
                errors += fail("reexec guard", "would run the zip script twice")
        finally:
            os.environ.pop("DD_APPLY_REEXEC", None)
        with zipfile.ZipFile(pack, "w") as zf:
            zf.writestr("pythonFiles/scripts/applyUpdate.py", current.read_bytes())
        if applyUpdate.shouldReexecApplyScript(pack, current):
            errors += fail("reexec same", "identical script would restart")

        cmdRoot = root / "cmdbody"
        cmdRoot.mkdir()
        applyUpdate.writeApplyUpdateCmd(cmdRoot)
        body = (cmdRoot / "applyUpdate.cmd").read_text(encoding="utf-8", newline="")
        if body != applyUpdate.applyCmdBody():
            errors += fail("cmd body", "writer drifted from applyCmdBody")
        if b"\r\r\n" in body.encode("utf-8"):
            errors += fail("cmd cr", "writer doubled the carriage return")
        if "find " in body or "tasklist" in body:
            errors += fail("cmd find", "command still searches for a process")
        if "finishEmbedSwap.cmd" not in body:
            errors += fail("cmd cleanup", "does not remove the old helper")
        from core.Update import _APPLY_UPDATE_CMD, _cmdTextSame, windowsCmdNeedsBootstrapWrite
        if _APPLY_UPDATE_CMD != applyUpdate.applyCmdBody():
            errors += fail("cmd drift", "bootstrap text differs from applyCmdBody")
        doubled = body.replace("\r\n", "\r\r\n")
        if not applyUpdate.cmdTextSame(doubled, body) or not _cmdTextSame(doubled, body):
            errors += fail("doubled cmd", "old writer looked like a command change")
        if windowsCmdNeedsBootstrapWrite(doubled, None, body):
            errors += fail("bootstrap same", "would rewrite a matching command")
        if not windowsCmdNeedsBootstrapWrite("old launcher command", None, body):
            errors += fail("bootstrap old", "3.0 command would be left in place")
        if windowsCmdNeedsBootstrapWrite("old launcher command", body, body):
            errors += fail("bootstrap staged", "would hide a real second restart")

        sameCmd = root / "samecmd"
        writeFile(sameCmd / "applyUpdate.cmd", body)
        writeFile(sameCmd / "applyUpdate.cmd.new", body)
        applyUpdate.writeApplyUpdateCmd(sameCmd, stageBesideLive=True)
        if (sameCmd / "applyUpdate.cmd.new").exists():
            errors += fail("same cmd", "staged a command that already matches")
        if (sameCmd / "applyUpdate.cmd").read_text(encoding="utf-8", newline="") != body:
            errors += fail("same cmd live", "rewrote the matching command")

        oldWriter = root / "oldwriter"
        (oldWriter / "applyUpdate.cmd").parent.mkdir(parents=True, exist_ok=True)
        (oldWriter / "applyUpdate.cmd").write_bytes(doubled.encode("utf-8"))
        (oldWriter / "applyUpdate.cmd.new").write_bytes(doubled.encode("utf-8"))
        applyUpdate.writeApplyUpdateCmd(oldWriter, stageBesideLive=True)
        if (oldWriter / "applyUpdate.cmd.new").exists():
            errors += fail("old writer", "staged a command the old writer already installed")
        if (oldWriter / "applyUpdate.cmd").read_bytes() != doubled.encode("utf-8"):
            errors += fail("old writer live", "rewrote the matching command")

        changed = root / "changecmd"
        writeFile(changed / "applyUpdate.cmd", "old launcher command\r\n")
        applyUpdate.writeApplyUpdateCmd(changed, stageBesideLive=True)
        if (changed / "applyUpdate.cmd").read_text(encoding="utf-8", newline="") != "old launcher command\r\n":
            errors += fail("changed live", "replaced the running command")
        if (changed / "applyUpdate.cmd.new").read_text(encoding="utf-8", newline="") != body:
            errors += fail("changed staged", "new command was not staged")

        sameExe = root / "exe"
        writeFile(sameExe / "Data Doctor.exe", "launcher-bytes")
        if not applyUpdate.copyFileIfPresent(sameExe / "Data Doctor.exe", sameExe / "Data Doctor.exe"):
            errors += fail("exe same", "identical file was not left in place")
        srcExe = root / "new-exe"
        writeFile(srcExe / "Data Doctor.exe", "newer-launcher")
        destExe = root / "dest-exe" / "Data Doctor.exe"
        writeFile(destExe, "launcher-bytes")
        applyUpdate.copyFileIfPresent(srcExe / "Data Doctor.exe", destExe)
        if destExe.read_text(encoding="utf-8") != "newer-launcher":
            errors += fail("exe new", destExe.read_text(encoding="utf-8"))

        real = root / "realinstall"
        writeFile(real / "pythonFiles" / "app.pyw", "app")
        writeFile(real / "applyUpdate.cmd", "cmd")
        # The fixture root already has pythonFiles. A reexec copy must sit
        # outside that tree or the walk finds it and never looks like Temp.
        previous = Path.cwd()
        nest = Path(tempfile.mkdtemp(prefix="dd-temp-nest-"))
        try:
            tempScript = nest / "dd-apply-abc.py"
            writeFile(tempScript, "from zip")
            stray = tempScript.parent / "updates"
            stray.mkdir()
            walked = applyUpdate.findInstallRoot(tempScript.parent)
            if walked != tempScript.parent.resolve():
                errors += fail("temp walk", walked)
            if applyUpdate.installRootConfirmed(tempScript.parent):
                errors += fail("temp confirmed", tempScript.parent)
            try:
                os.chdir(real)
                found = applyUpdate.locateInstallRoot(tempScript)
                if found != real.resolve():
                    errors += fail("reexec root", found)
            finally:
                os.chdir(previous)
            applyUpdate.removeStrayTempUpdates(tempScript)
            if stray.exists():
                errors += fail("stray updates", "empty temp updates folder still present")
            if not tempScript.is_file():
                errors += fail("temp script", "removed the reexec copy")

            occupiedScript = nest / "elsewhere" / "dd-apply-def.py"
            writeFile(occupiedScript, "from zip")
            occupiedZip = occupiedScript.parent / "updates" / "DataDoctor-Python-v1.zip"
            writeFile(occupiedZip, "zip")
            applyUpdate.removeStrayTempUpdates(occupiedScript)
            if not occupiedZip.is_file():
                errors += fail("keep zip", "removed a temp updates folder that had a zip")
        finally:
            import shutil
            shutil.rmtree(nest, ignore_errors=True)

        (real / "updates").mkdir()
        namedLikeTemp = real / "dd-apply-nope.py"
        writeFile(namedLikeTemp, "script")
        applyUpdate.removeStrayTempUpdates(namedLikeTemp)
        if not (real / "updates").is_dir():
            errors += fail("real updates", "removed the install updates folder")

        scriptIn = real / "pythonFiles" / "scripts" / "applyUpdate.py"
        writeFile(scriptIn, "installed")
        try:
            os.chdir(root)
            found = applyUpdate.locateInstallRoot(scriptIn)
            if found != real.resolve():
                errors += fail("script root", found)
        finally:
            os.chdir(previous)

        other = root / "otherinstall"
        writeFile(other / "Data Doctor.exe", "exe")
        os.environ[applyUpdate.APPLY_ROOT_ENV] = str(other)
        try:
            os.chdir(real)
            found = applyUpdate.locateInstallRoot(Path("dd-apply-unused.py"))
            if found != other.resolve():
                errors += fail("env root", found)
        finally:
            os.environ.pop(applyUpdate.APPLY_ROOT_ENV, None)
            os.chdir(previous)

        zipPath = real / "updates" / "DataDoctor-Python-v9.zip"
        argv = applyUpdate.reexecArgv(["--keep-extract"], real, zipPath)
        if argv[:1] != ["--keep-extract"] or "--install-root" not in argv or "--zip" not in argv:
            errors += fail("reexec argv", argv)
        if str(real) not in argv or str(zipPath) not in argv:
            errors += fail("reexec paths", argv)
        again = applyUpdate.reexecArgv(
            ["--install-root", str(real), "--zip", "already.zip"],
            other,
            other / "x.zip",
        )
        if again.count("--install-root") != 1 or again.count("--zip") != 1:
            errors += fail("reexec dup", again)
        if "already.zip" not in again or str(other) in again:
            errors += fail("reexec keep", again)

    if errors:
        print(f"{errors} failed")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
