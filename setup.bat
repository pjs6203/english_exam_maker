@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py"
) else (
  set "PYTHON=python"
)
%PYTHON% -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo Setup complete. Run run_gui.bat.
pause
exit /b 0
:error
echo.
echo Setup failed. Check that Python 3.10 or newer is installed.
pause
exit /b 1
