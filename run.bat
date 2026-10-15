@echo off
REM ===========================================================================
REM Launch the MULTI-USER Lipreading API (server.api) for the iOS app + PWA,
REM and start an ngrok tunnel so your phone can reach it.
REM
REM NOTE: this runs `server.api` (Supabase auth). The OLD `server.web_api` is a
REM different, single-user server and makes the app say "invalid access token".
REM ===========================================================================
setlocal
cd /d "%~dp0"
if not exist "%USERPROFILE%\.lipreading" mkdir "%USERPROFILE%\.lipreading"

REM --- find the virtual env --------------------------------------------------
set "VENV="
if exist "%~dp0.venvpath" set /p VENV=<"%~dp0.venvpath"
if not defined VENV if exist "%~dp0.venv\Scripts\activate.bat" set "VENV=%~dp0.venv"
if not defined VENV if exist "%~dp0..\.venv\Scripts\activate.bat" set "VENV=%~dp0..\.venv"
if not defined VENV if exist "%~dp0venv\Scripts\activate.bat" set "VENV=%~dp0venv"
if not defined VENV if exist "%~dp0..\venv\Scripts\activate.bat" set "VENV=%~dp0..\venv"
if not defined VENV goto novenv

call "%VENV%\Scripts\activate.bat"
set "PY=%VENV%\Scripts\python.exe"

REM --- config ----------------------------------------------------------------
REM Supabase project URL is a public value (safe to keep here). It MUST be set
REM or the server falls back to custom auth and rejects the app's token.
set "SUPABASE_URL=https://mbmajkrmvtlszirgtgre.supabase.co"

REM Quiet MediaPipe's harmless "clearcut" telemetry log spam.
set "GLOG_minloglevel=2"

REM Secrets (DB URL with password, optional legacy JWT secret) live in an
REM untracked file next to this script. Copy env.local.bat.example ->
REM env.local.bat and fill it in. Optional: without a DB URL the server uses a
REM local SQLite file, which is fine for testing.
if exist "%~dp0env.local.bat" call "%~dp0env.local.bat"

REM --- start the tunnel in its own window ------------------------------------
echo Starting ngrok tunnel on port 8000 (new window)...
start "ngrok" cmd /k ngrok http 8000
echo Copy the https://xxxx.ngrok-free.app URL from that window into the app:
echo     Account -^> Server -^> paste -^> Save ^& use this server
echo.

REM --- start the API (preloads the model automatically) ---------------------
echo Starting the multi-user API on http://127.0.0.1:8000 ...
"%PY%" -m server.api --host 0.0.0.0 --port 8000
goto end

:novenv
echo Could not find a virtual env (.venv) in this folder or its parent.
echo Create a file named .venvpath next to run.bat containing the full path to
echo your venv folder (e.g. C:\path\to\your\.venv), then try again.
pause

:end
endlocal
