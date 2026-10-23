@echo off
rem Transcribe recordings locally. Drag an audio file onto this file, or run: run.bat -h
chcp 65001 >nul
set PYTHONUTF8=1
if not exist "%~dp0venv\Scripts\python.exe" (
  echo venv not found - run setup.bat first.
  pause
  exit /b 1
)
"%~dp0venv\Scripts\python.exe" "%~dp0transcribe.py" %*
set RC=%ERRORLEVEL%
rem Keep the window open when launched by double-click / drag-and-drop.
echo %CMDCMDLINE% | find /i "/c" >nul && pause
exit /b %RC%
