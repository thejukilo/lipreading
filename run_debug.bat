@echo off
REM Same as run.bat but keeps a console open and prints errors.
setlocal
cd /d "%~dp0"

set "VENV="
if exist "%~dp0.venvpath" set /p VENV=<"%~dp0.venvpath"
if not defined VENV if exist "%~dp0.venv\Scripts\activate.bat" set "VENV=%~dp0.venv"
if not defined VENV if exist "%~dp0..\.venv\Scripts\activate.bat" set "VENV=%~dp0..\.venv"
if not defined VENV if exist "%~dp0venv\Scripts\activate.bat" set "VENV=%~dp0venv"
if not defined VENV if exist "%~dp0..\venv\Scripts\activate.bat" set "VENV=%~dp0..\venv"
if not defined VENV goto novenv

call "%VENV%\Scripts\activate.bat"
echo Using venv: %VENV%
python -m server.gui_app
echo.
echo (app closed - press a key)
pause >nul
goto end

:novenv
echo Could not find a virtual env (.venv). Create a .venvpath file next to this
echo script with the full path to your venv folder, then try again.
pause

:end
endlocal
