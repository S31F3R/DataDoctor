# Python Embed Upgrade

## Goal

Make the launcher fully portable so **Python does not need to be installed on the target machine**.

## Why the `.venv` isn't enough

A `.venv` is not a self-contained Python install. It only contains:

- Small launcher shims (`python.exe` / `pythonw.exe` in `Scripts`)
- Installed packages (`Lib\site-packages`)
- A `pyvenv.cfg` file

The `pythonw.exe` inside `.venv\Scripts` is a tiny redirector. It reads `pyvenv.cfg`, finds the `home = ...` path pointing to the **base Python install** on the machine, and delegates all the actual interpreter work (the standard library, `python3XX.dll`, etc.) to that base install. No base Python on the machine = nothing to delegate to.

The venv gives package isolation, not interpreter portability.

## The fix: embeddable Python

Ship Python's official **Windows embeddable package** alongside the app instead of relying on the venv. It's plain files on disk — no self-extraction, no packing — so Windows Defender has nothing to flag (unlike PyInstaller `--onefile`).

## Setup steps

### 1. Download and extract

Download the **Windows embeddable package (64-bit)** zip from python.org for the target version. Extract it to:

```
Project Files\python-embed\
```

### 2. Enable site packages

Edit `python-embed\python3XX._pth` (e.g. `python313._pth`) and **uncomment** this line:

```
#import site
```

so it reads:

```
import site
```

This lets the embed build see installed packages in `Lib\site-packages`.

### 3. Bootstrap pip and install packages

From a machine with regular Python:

```
curl -o get-pip.py https://bootstrap.pypa.io/get-pip.py
python-embed\python.exe get-pip.py
python-embed\python.exe -m pip install -r requirements.txt
```

Everything lands in `python-embed\Lib\site-packages` — fully portable.

### 4. Verify the folder

Confirm `python-embed\` contains at minimum:

- `pythonw.exe`
- `python.exe`
- `python3XX.dll`
- `python3XX.zip`
- `Lib\` (with `site-packages\`)

That's the whole interpreter — nothing references a machine-level install.

## Gotcha: Visual C++ Redistributable

If any packages ship compiled extensions (numpy-adjacent libraries, etc.), they may need the **Visual C++ Redistributable** runtime. It's present on most Windows machines already, but if you hit missing-DLL errors, that's the cause. Fix by dropping the needed `vcruntime140.dll` into the `python-embed` folder.

## Packaging script notes

When updating the scripts that push the project to GitHub:

- Include the entire `python-embed\` folder in the pushed/packaged output.
- Do **not** rely on `.gitignore` rules that exclude `*.exe`, `*.dll`, or `python-embed\` — these files must ship.
- Do **not** ship the `.venv` anymore; it's replaced by `python-embed`.
- Keep `requirements.txt` in the repo so the embed can be rebuilt reproducibly.
- Consider excluding `get-pip.py` from the final package (only needed during setup).
- Watch repo size — the embed folder plus `site-packages` can be large; use Git LFS if it becomes an issue.
