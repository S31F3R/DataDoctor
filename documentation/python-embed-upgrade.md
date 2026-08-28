# Python embed upgrade (Windows)

Windows 3.1+ does **not** need Python on PATH. The launcher starts:

```
pythonFiles\python-embed\pythonw.exe  pythonFiles\app.pyw
```

`Data Doctor.exe` already uses those paths (`launcher/src/App.vb`). A `.venv` is not portable — its `python.exe` is a shim to a machine-level install.

## What ships

| Piece | Where |
|-------|--------|
| Embeddable CPython 3.14.7 | `launcher/python-3.14.7-embed-amd64.zip` (extracted at package time) |
| Launcher source | `launcher/src/App.vb` (rebuild on Windows with `vbc`) |
| Packager | `scripts/packageWindows.py` → `pythonFiles\python-embed\` |
| Apply | `scripts/applyUpdate.py` (pip + site + Windows zip) |

`python-embed` includes `vcruntime140.dll`. Pip/site-packages are installed on the user's PC (first `applyUpdate.cmd`), not stored in git. Linux/mac still use a venv.

## `_pth` + pip

After extract, `python314._pth` must contain:

```
python314.zip
.
Lib\site-packages
import site
```

`get-pip.py` is downloaded into `python-embed` at package time (and again at apply time if missing). `python -m pip install -r requirements.txt` then fills `Lib\site-packages`.

`pygame` 2.6.1 has no cp314 wheel. Requirements use `pygame-ce` (`import pygame` still works). applyUpdate uninstalls leftover `pygame` first.

This Linux packager cannot pip-install Windows wheels. First run on the PC does that.

## Zip roles

| Asset | Use |
|-------|-----|
| `DataDoctor-Python-*.zip` | Code update once `python-embed` is already there |
| `DataDoctor-Windows-*.zip` | Fresh install, **and** 3.0.x → 3.1+ (replaces `Data Doctor.exe`, installs embed) |

Old 3.0.x `applyUpdate.py` only understands a Python zip (`DataDoctor.py` at the zip root). It cannot install the launcher or `python-embed`.

### 3.0.x hop

1. In-app update on 3.0.x still downloads the **Python** zip (old updater).
2. Old applyUpdate copies `core/` (including `core/applyUpdate.py` shipped in the Python zip).
3. New `DataDoctor.py` moves that file to `pythonFiles\scripts\applyUpdate.py` (or `Project Files\scripts\` on 3.0.x) and rewrites `applyUpdate.cmd`.
4. New updater sees no `python-embed\pythonw.exe` and offers **`DataDoctor-Windows-*.zip`**.
5. User restarts Data Doctor. The launcher starts applyUpdate.cmd and exits so the `.exe` can be replaced.

Do not tell them to "restart" for that hop.

## Layout after unzip (Windows)

```
Data Doctor.exe
applyUpdate.cmd
updates\                   (first-install Python zip)
pythonFiles\
  app.pyw
  python-embed\            (python.exe, pythonw.exe, python314.dll, vcruntime140.dll, …)
  core\  ui\  quickLook\  oracle\  certs\  scripts\
```

## Rebuild the exe (Windows only)

```
cd launcher\src
vbc /nologo /target:winexe /out:"..\Data Doctor.exe" /win32icon:"..\Data Doctor.ico" app.vb
```

Launcher source is `launcher/src/` (generic: `pythonFiles\app.pyw`). Compile on Windows; this Linux box has no `vbc`.
