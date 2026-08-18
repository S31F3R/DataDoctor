Oracle Instant Client (optional)

sqlnet.ora under oracle/network/admin/ ships with the app.

Instant Client libraries are OS-specific and are not stored in git.
When building a package, drop (or replace) a zip here:

  dist/oracle/oracle-windows.zip
  dist/oracle/oracle-linux.zip
  dist/oracle/oracle-macos.zip

Official Instant Client Basic zips work as-is. The packager unwraps a
single top-level instantclient_* folder and copies it to oracle/client
inside that OS package.

The Python update zip (DataDoctor-Python-*.zip) does not include Instant
Client. Replace a zip in place to pick up a newer Oracle version on the
next package / publishRelease run.
