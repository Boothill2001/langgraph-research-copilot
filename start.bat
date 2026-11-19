@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Follow the one-time setup in README.md.
  if not defined DEMO_NO_BROWSER pause
  exit /b 1
)
if defined DEMO_NO_BROWSER (
  ".venv\Scripts\python.exe" launch.py --no-browser
) else (
  ".venv\Scripts\python.exe" launch.py
)
if errorlevel 1 (
  if not defined DEMO_NO_BROWSER pause
  exit /b 1
)
