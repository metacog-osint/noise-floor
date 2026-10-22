@echo off
rem Daily community collectors and watch pollers, run by Windows Task Scheduler. Paths are relative to this file.
rem Output: data\community\*\digest_*.md and data\watch\digest_*.md; log: data\logs\collectors.log (all gitignored).
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
if not exist data\logs mkdir data\logs
echo === %DATE% %TIME% >> data\logs\collectors.log
.venv\Scripts\python.exe collectors\bluesky.py >> data\logs\collectors.log 2>&1
.venv\Scripts\python.exe collectors\feeds.py >> data\logs\collectors.log 2>&1
.venv\Scripts\python.exe collectors\watch.py >> data\logs\collectors.log 2>&1
endlocal
