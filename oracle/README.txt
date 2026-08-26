Oracle Instant Client Basic Lite (optional)

sqlnet.ora under oracle/network/admin/ ships with the app.

Instant Client is OS-specific and is not stored in git. Packages expect
Basic Lite (raw library files, no Oracle installer):

  dist/oracle/oracle-windows.zip
  dist/oracle/oracle-linux.zip
  dist/oracle/oracle-macos.dmg

Windows and Linux zips should contain the Lite files at the zip root
(oci.dll, libociicus.so, …). A wrapper folder is unwrapped. Contents
always land in oracle/client inside that OS package.

macOS Instant Client from Oracle is a .dmg. Name it oracle-macos.dmg
and leave it in dist/oracle/. The packager extracts the disk image
(7z on Linux, hdiutil on a Mac).

The Python update zip does not include Instant Client.
