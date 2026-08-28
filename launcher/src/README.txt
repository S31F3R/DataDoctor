Data Doctor.exe — Windows launcher
==================================

The checked-in Data Doctor.exe already launches:

  Project Files\python-embed\pythonw.exe  Project Files\DataDoctor.pyw

and runs applyUpdate.cmd first if Update\ contains a .zip.

Rebuild on Windows only (this Linux packager cannot produce a new .exe):

  cd launcher\src
  vbc /nologo /target:winexe /out:"..\Data Doctor.exe" /win32icon:..\DataDoctor.ico App.vb

python-3.14.7-embed-amd64.zip sits in launcher/ and is extracted into the
Windows zip at package time (Project Files\python-embed\). Pip/site-packages
are installed on the user's PC by applyUpdate.cmd, not stored in git.

python-3.13.14-amd64.exe in launcher/ is leftover (system installer). It is
not packaged. 3.1+ Windows zips do not need a system Python.
