@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" if exist "Pinboard.exe" (
    start "" "Pinboard.exe"
    exit /b 0
)

if exist ".runtime\Scripts\python.exe" (
    set "PINBOARD_PY=.runtime\Scripts\python.exe"
    goto :ready
)

if not exist ".venv\Scripts\python.exe" (
    call setup.cmd
    if errorlevel 1 goto :end
)

set "PINBOARD_PY=.venv\Scripts\python.exe"
:ready

set "BOARD_URL=%~1"
if not defined BOARD_URL set /p "BOARD_URL=Paste a public Pinterest board URL: "
if not defined BOARD_URL goto :end

"%PINBOARD_PY%" app.py "%BOARD_URL%" --zip

:end
echo.
pause
