@echo off
REM Double-click to launch the Lipreading desktop app (no terminal window).
setlocal
cd /d "%~dp0"
if not exist "%USERPROFILE%\.lipreading" mkdir "%USERPROFILE%\.lipreading"

set "VENV="
if exist "%~dp0.venvpath" set /p VENV=<"%~dp0.venvpath"
if not defined VENV if exist "%~dp0.venv\Scripts\activate.bat" set "VENV=%~dp0.venv"
if not defined VENV if exist "%~dp0..\.venv\Scripts\activate.bat" set "VENV=%~dp0..\.venv"
if not defined VENV if exist "%~dp0venv\Scripts\activate.bat" set "VENV=%~dp0venv"
if not defined VENV if exist "%~dp0..\venv\Scripts\activate.bat" set "VENV=%~dp0..\venv"
if not defined VENV goto novenv

call "%VENV%\Scripts\activate.bat"
set "PYW=%VENV%\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%VENV%\Scripts\python.exe"
start "" "%PYW%" -m server.gui_app
goto end

:novenv
echo Could not find a virtual env (.venv) in this folder or its parent.
echo Create a file named .venvpath next to run.bat containing the full path to
echo your venv folder (e.g. C:\path\to\your\.venv), then try again.
pause

:end
endlocal
