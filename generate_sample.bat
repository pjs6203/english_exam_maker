@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)
if not exist "output" mkdir "output"
"%PYTHON%" app.py render examples\sample_exam.json -o output\sample_exam.pdf --manifest output\sample_exam.layout.json
if errorlevel 1 pause
