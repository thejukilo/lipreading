@echo off
REM Launch the Lipreading mobile web server (so phones can use their camera).
REM Runs in a visible terminal so you can read the access URL/token it prints.
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
set "PY=%VENV%\Scripts\python.exe"
echo Starting the lipreading web server. Expose it with a tunnel for phone use:
echo     cloudflared tunnel --url http://localhost:8000
echo.
"%PY%" -m server.web_api --preload %*
goto end

:novenv
echo Could not find a virtual env (.venv) in this folder or its parent.
echo Create a file named .venvpath next to run.bat containing the full path to
echo your venv folder (e.g. C:\path\to\your\.venv), then try again.
pause

:end
endlocal
