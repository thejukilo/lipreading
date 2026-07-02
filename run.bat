@echo off
REM Double-click to launch the Lipreading desktop app (no terminal window).
REM Auto-finds your virtual env in the repo root or one level up. If it can't,
REM edit the SET "VENV=" line below to point at your venv folder.
setlocal
cd /d "%~dp0"
if not exist "%USERPROFILE%\.lipreading" mkdir "%USERPROFILE%\.lipreading"

set "VENV="
REM 1) A custom path in .venvpath (untracked — never conflicts on pull). Put the
REM    full path to your venv folder on the first line of that file.
if exist "%~dp0.venvpath" set /p VENV=<"%~dp0.venvpath"
REM 2) Otherwise auto-detect in the repo root or one level up.
if not defined VENV for %%D in ("%~dp0.venv" "%~dp0..\.venv" "%~dp0venv" "%~dp0..\venv") do (
  if not defined VENV if exist "%%~fD\Scripts\activate.bat" set "VENV=%%~fD"
)
if not defined VENV (
  echo Could not find a virtual env (.venv) in "%~dp0" or its parent.
  echo Create a file named .venvpath next to run.bat containing the full path
  echo to your venv folder (e.g. C:\path\to\your\.venv), then try again.
  pause
  exit /b 1
)

call "%VENV%\Scripts\activate.bat"
set "PYW=%VENV%\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%VENV%\Scripts\python.exe"
start "" "%PYW%" -m server.gui_app
endlocal
