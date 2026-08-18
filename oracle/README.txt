Oracle Instant Client (optional)

sqlnet.ora under oracle/network/admin/ ships with the app.

Instant Client libraries are OS-specific and are not stored in git.
When building a package, drop (or replace) archives here:

  dist/oracle/oracle-windows.zip
  dist/oracle/oracle-linux.zip
  dist/oracle/oracle-macos.zip   (client files, or a single oracle.dmg inside)
  dist/oracle/oracle.dmg         (macOS Instant Client .dmg, optional)

Windows and Linux zips should contain the Instant Client files at the zip
root (oci.dll, libclntsh.so, …). A wrapper folder is unwrapped. Contents
always land in oracle/client inside that OS package.

macOS Instant Client from Oracle is a .dmg. Rename it to oracle.dmg and
either leave it in dist/oracle/ or zip it as oracle-macos.zip. The packager
extracts the disk image (7z on Linux, hdiutil on a Mac).

Basic and Basic Lite both work. The Python update zip does not include
Instant Client.
