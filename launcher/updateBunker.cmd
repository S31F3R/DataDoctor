@echo off
REM Merge packaged bunker.db into the user's bunker.db (Windows launcher helper).
REM Edit paths below if your install layout differs, or pass --packaged / --user.

setlocal
cd /d "%~dp0"

REM Prefer Project Files venv python, then PATH python
set "PY="
if exist "Project Files\.venv\Scripts\python.exe" set "PY=Project Files\.venv\Scripts\python.exe"
if not defined PY if exist "..\\.venv\Scripts\python.exe" set "PY=..\\.venv\Scripts\python.exe"
if not defined PY set "PY=python"

"%PY%" "%~dp0updateBunker.py" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo updateBunker failed with exit code %ERR%
  pause
)
endlocal
exit /b %ERR%
