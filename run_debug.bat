@echo off
REM Same as run.bat but keeps a console open and prints errors — use this if the
REM app won't start, so you can see what went wrong.
setlocal
cd /d "%~dp0"

set "VENV="
if exist "%~dp0.venvpath" set /p VENV=<"%~dp0.venvpath"
if not defined VENV for %%D in ("%~dp0.venv" "%~dp0..\.venv" "%~dp0venv" "%~dp0..\venv") do (
  if not defined VENV if exist "%%~fD\Scripts\activate.bat" set "VENV=%%~fD"
)
if not defined VENV (
  echo Could not find a virtual env (.venv) in "%~dp0" or its parent.
  echo Edit this file and set VENV to your venv folder.
  pause
  exit /b 1
)

call "%VENV%\Scripts\activate.bat"
echo Using venv: %VENV%
python -m server.gui_app
echo.
echo (app closed — press a key)
pause >nul
endlocal
