@echo off
rem Daily NISAR L-band run, started by Windows Task Scheduler. Paths are relative to this file.
rem Config: private\watch\nisar.json (gitignored). Outputs: private\nisar\ (gitignored).
rem Log: data\logs\nisar.log (gitignored). Needs EARTHDATA_TOKEN as a user environment variable;
rem publishing the private web view also needs CLOUDFLARE_API_TOKEN and a "view" block in the config.
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
rem A shell started before the token was set won't have it: read it from the user environment (never echoed).
if not defined EARTHDATA_TOKEN (
  for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('EARTHDATA_TOKEN','User')"`) do set "EARTHDATA_TOKEN=%%t"
)
if not exist data\logs mkdir data\logs
echo === %DATE% %TIME% >> data\logs\nisar.log
cd nisar
..\.venv\Scripts\python.exe -W ignore::RuntimeWarning -m nisar_rfi run >> ..\data\logs\nisar.log 2>&1
set RC=%ERRORLEVEL%
rem Extra areas: every private\watch\nisar.d\*.json is a full config with its own state and outputs.
rem They run before publishing, so extra maps in the view are fresh. A failure sets RC but doesn't stop the rest.
if exist ..\private\watch\nisar.d\*.json (
  for %%c in (..\private\watch\nisar.d\*.json) do (
    echo --- area %%~nc >> ..\data\logs\nisar.log
    ..\.venv\Scripts\python.exe -W ignore::RuntimeWarning -m nisar_rfi run --config "%%c" >> ..\data\logs\nisar.log 2>&1
    if errorlevel 1 if %RC%==0 set RC=1
  )
)
rem NGA navigational warnings (HYDROARC, HYDROLANT) into the local archive; a failure here doesn't stop the export.
..\.venv\Scripts\python.exe ..\tools\navwarnings.py fetch --areas C,A >> ..\data\logs\nisar.log 2>&1
rem Public repeat-site file for the site's map layer (public areas only), uploaded to the nisar-data release.
..\.venv\Scripts\python.exe -W ignore::RuntimeWarning -m nisar_rfi export --upload >> ..\data\logs\nisar.log 2>&1
if errorlevel 1 if %RC%==0 set RC=1
rem Refresh the private web view (skipped when no "view" block is configured).
..\.venv\Scripts\python.exe -W ignore::RuntimeWarning -m nisar_rfi publish >> ..\data\logs\nisar.log 2>&1
echo === exit %RC% >> ..\data\logs\nisar.log
endlocal & exit /b %RC%
