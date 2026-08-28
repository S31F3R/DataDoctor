@echo off
REM Merge packaged temp\bunker.db into live core\bunker.db
REM Script lives at pythonFiles\scripts\updateBunker.py (or Project Files\)

setlocal
cd /d "%~dp0"

set "PY="
if exist "pythonFiles\python-embed\python.exe" set "PY=pythonFiles\python-embed\python.exe"
if not defined PY if exist "pythonFiles\.venv\Scripts\python.exe" set "PY=pythonFiles\.venv\Scripts\python.exe"
if not defined PY if exist "Project Files\.venv\Scripts\python.exe" set "PY=Project Files\.venv\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY set "PY=python"

set "SCRIPT=%~dp0pythonFiles\scripts\updateBunker.py"
if not exist "%SCRIPT%" set "SCRIPT=%~dp0Project Files\scripts\updateBunker.py"
if not exist "%SCRIPT%" (
  echo ERROR: updateBunker.py not found

  pause
  exit /b 1
)

"%PY%" "%SCRIPT%" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo updateBunker failed with exit code %ERR%
  pause
)
endlocal
exit /b %ERR%
