@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py gui
) else (
  echo The virtual environment is missing. Run setup.bat first.
  pause
)
