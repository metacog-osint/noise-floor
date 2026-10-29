@echo off
rem Daily Norwegian open AIS collection (BarentsWatch live AIS API), started by Windows Task Scheduler
rem (task "noise-floor BarentsWatch AIS"). Streams for just under 24 hours into data\ais\barentswatch\ (gitignored)
rem and takes one snapshot first. Needs BARENTSWATCH_CLIENT_ID and BARENTSWATCH_CLIENT_SECRET as user environment
rem variables; without them the run logs one line and exits 0. Log: data\logs\barentswatch.log.
rem Stop early by creating data\ais\barentswatch\STOP.
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
if not exist data\logs mkdir data\logs
echo === %DATE% %TIME% >> data\logs\barentswatch.log
.venv\Scripts\python.exe collectors\barentswatch_ais.py snapshot >> data\logs\barentswatch.log 2>&1
.venv\Scripts\python.exe collectors\barentswatch_ais.py stream --hours 23.75 >> data\logs\barentswatch.log 2>&1
set RC=%ERRORLEVEL%
echo === exit %RC% >> data\logs\barentswatch.log
endlocal & exit /b %RC%
