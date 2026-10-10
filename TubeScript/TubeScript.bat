@echo off
chcp 65001 > nul

setlocal

REM TubeScript CLI launcher
REM Sets up a local virtual environment on the first run, installs the pinned
REM dependencies, then launches the CLI from this directory.

REM Get the directory of this batch file
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Prefer python in PATH, fallback to py launcher
where python > nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=python"
) else (
    set "PYTHON=py -3"
)

set "VENV_PY=%CD%\.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto :checkdeps

echo.
echo First run: creating a local virtual environment...
%PYTHON% -m venv .venv
if errorlevel 1 goto :setupfailed

:checkdeps
"%VENV_PY%" -c "import colorama, yt_dlp, pywhispercpp" > nul 2>&1
if not errorlevel 1 goto :run

echo First run: installing dependencies (this can take a few minutes)...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :setupfailed
echo.
echo Environment ready.
echo.

:run
"%VENV_PY%" main.py %*
set "EXITCODE=%errorlevel%"

REM On success the app already asked whether to close or go back to the home
REM screen, so the window can simply go away. Only on an error do we hold the
REM window open, otherwise the message would vanish unread.
if %EXITCODE% neq 0 (
    echo.
    echo TubeScript exited with code %EXITCODE%. Press any key to close this window.
    pause > nul
)

endlocal & exit /b %EXITCODE%

:setupfailed
echo.
echo Could not set up the virtual environment. Make sure Python 3.10+ is
echo installed and on your PATH, then run this file again.
pause > nul
endlocal & exit /b 1