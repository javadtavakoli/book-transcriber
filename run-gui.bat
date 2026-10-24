@echo off
rem Open the desktop app (from a source checkout), without a console window.
cd /d "%~dp0"
start "" venv\Scripts\pythonw.exe -m booktranscriber %*
