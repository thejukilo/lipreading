@echo off
REM Double-click to launch the Lipreading desktop app (no terminal window).
REM Uses pythonw so nothing stays open. If it fails to start, run run_debug.bat
REM to see the error.
cd /d "%~dp0"
if not exist "%USERPROFILE%\.lipreading" mkdir "%USERPROFILE%\.lipreading"
call ".venv\Scripts\activate.bat"
start "" pythonw -m server.gui_app
