@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Installation completed.
exit /b 0

:error
echo.
echo Installation failed. Install Python 3.10 or newer from https://www.python.org/
exit /b 1
