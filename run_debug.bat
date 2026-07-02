@echo off
REM Same as run.bat but keeps a console open and prints errors — use this if the
REM app won't start, so you can see what went wrong.
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
python -m server.gui_app
echo.
echo (app closed — press a key)
pause >nul
