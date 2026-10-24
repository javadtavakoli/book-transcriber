@echo off
rem One-time setup: create venv and install dependencies.
cd /d "%~dp0"
py -3 -m venv venv || python -m venv venv || goto :fail
venv\Scripts\python.exe -m pip install --upgrade pip || goto :fail
venv\Scripts\python.exe -m pip install -r requirements-gui.txt || goto :fail
echo.
echo Setup complete. Drag an audio file onto run.bat, or run: run.bat -h
pause
exit /b 0
:fail
echo.
echo Setup FAILED. Make sure Python 3.10+ is installed from python.org (tick "Add to PATH").
pause
exit /b 1
