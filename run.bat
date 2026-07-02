@echo off
REM Double-click to launch the Lipreading desktop app (no terminal window).
REM Auto-finds your virtual env in the repo root or one level up. If it can't,
REM edit the SET "VENV=" line below to point at your venv folder.
setlocal
cd /d "%~dp0"
if not exist "%USERPROFILE%\.lipreading" mkdir "%USERPROFILE%\.lipreading"

set "VENV="
for %%D in ("%~dp0.venv" "%~dp0..\.venv" "%~dp0venv" "%~dp0..\venv") do (
  if not defined VENV if exist "%%~fD\Scripts\activate.bat" set "VENV=%%~fD"
)
REM --- If auto-detect fails, hard-code your venv here, e.g.:
REM set "VENV=C:\path\to\your\.venv"
if not defined VENV (
  echo Could not find a virtual env (.venv) in "%~dp0" or its parent.
  echo Edit run.bat and set VENV to your venv folder, then try again.
  pause
  exit /b 1
)

call "%VENV%\Scripts\activate.bat"
set "PYW=%VENV%\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%VENV%\Scripts\python.exe"
start "" "%PYW%" -m server.gui_app
endlocal
