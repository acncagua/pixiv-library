@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error

echo.
echo Setup completed.
pause
exit /b 0

:error
echo.
echo Setup failed.
pause
exit /b 1

