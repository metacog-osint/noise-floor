@echo off
rem Daily aisstream AIS collection, started by Windows Task Scheduler (task "noise-floor aisstream AIS").
rem Runs collectors\aisstream_ais.py for just under 24 hours over the focus areas in private\watch\maritime.json
rem (gitignored). Needs AISSTREAM_API_KEY as a user environment variable; without it the run logs one line and exits 0.
rem Output: data\ais\aisstream\ (gitignored; aisstream data stays private). Log: data\logs\aisstream.log.
rem Stop early by creating data\ais\aisstream\STOP.
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
if not exist data\logs mkdir data\logs
if not defined AISSTREAM_API_KEY (
  for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('AISSTREAM_API_KEY','User')"`) do set "AISSTREAM_API_KEY=%%t"
)
echo === %DATE% %TIME% >> data\logs\aisstream.log
if not defined AISSTREAM_API_KEY (
  echo no AISSTREAM_API_KEY yet: skipped >> data\logs\aisstream.log
  endlocal & exit /b 0
)
.venv\Scripts\python.exe collectors\aisstream_ais.py --hours 23.75 >> data\logs\aisstream.log 2>&1
set RC=%ERRORLEVEL%
echo === exit %RC% >> data\logs\aisstream.log
endlocal & exit /b %RC%
