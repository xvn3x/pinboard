@echo off
setlocal
cd /d "%~dp0"
if exist "Pinboard.exe" (
    start "" "Pinboard.exe"
    exit /b 0
)
if exist ".runtime\Scripts\pythonw.exe" (
    start "" ".runtime\Scripts\pythonw.exe" desktop.py
    exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" call setup.cmd
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" desktop.py
) else (
    echo Please run setup.cmd or download the portable Pinboard.exe release.
    pause
)
