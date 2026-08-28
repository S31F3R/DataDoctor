Data Doctor.exe — generic Windows Python launcher
=================================================

This VS project is meant to be reused. It always starts:

  pythonFiles\python-embed\pythonw.exe  pythonFiles\app.pyw

If Update\ (or update\) contains a .zip, it starts applyUpdate.cmd and
EXITS (does not wait). That unlocks Data Doctor.exe so the cmd can replace
the launcher. applyUpdate.py starts Data Doctor.exe when the zip is done.

If there is no zip, it starts pythonw + app.pyw.

Data Doctor packaging (scripts/packageWindows.py) copies DataDoctor.py →
pythonFiles\app.pyw and extracts embeddable CPython into pythonFiles\python-embed\.

Icon: DataDoctor.ico in this folder is the ApplicationIcon (taskbar / exe).
Rebuild on Windows (Visual Studio or Developer Command Prompt):

  msbuild "Data Doctor.vbproj" /p:Configuration=Release
  copy /Y bin\Release\"Data Doctor.exe" ..\

  or:

  vbc /nologo /target:winexe /win32icon:DataDoctor.ico /out:"..\Data Doctor.exe" app.vb

This Linux packager cannot produce a new .exe. After compiling on Windows,
put Data Doctor.exe in launcher\ (zip root).

python-3.14.7-embed-amd64.zip lives in launcher\ and is extracted at package
time. Pip/site-packages are installed on the user's PC by applyUpdate.cmd.
