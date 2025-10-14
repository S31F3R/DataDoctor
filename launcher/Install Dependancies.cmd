@echo off
setlocal enabledelayedexpansion

REM Get the directory where the CMD is running
set "exeDirectory=%~dp0"
set "requirementsPath=%exeDirectory%\Project Files\requirements.txt"

REM Run pip install
echo Installing dependencies from requirements.txt...
pip install -r "%requirementsPath%"

if %errorlevel% neq 0 (
    echo Error: Pip install failed. Check output above.
    pause
) else (
    echo Dependencies installed successfully.
    echo Press any key to exit...
    pause
)

endlocal
