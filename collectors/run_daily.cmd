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
rem CYGNSS: the newest complete day -> data\cygnss\daily and the cygnss-data release (home board; needs EARTHDATA_TOKEN)
.venv\Scripts\python.exe tools\cygnss_daily.py >> data\logs\cygnss_daily.log 2>&1
rem Sentinel-6A: newest complete days -> data\s6rfi\daily and the s6-data release (map layer; EARTHDATA_TOKEN + Space-Track)
.venv\Scripts\python.exe tools\s6_daily.py >> data\logs\s6_daily.log 2>&1
rem SMAP: newest complete days -> data\smap\daily (7-day windows) and the smap-data release (map layer; EARTHDATA_TOKEN)
.venv\Scripts\python.exe tools\smap_daily.py >> data\logs\smap_daily.log 2>&1
rem COSMIC-2: newest complete days -> data\cosmic2\daily and the cosmic2-data release (map layer; no account)
.venv\Scripts\python.exe tools\cosmic2_daily.py >> data\logs\cosmic2_daily.log 2>&1
rem EASA FIR tables and the Baltic warnings page: daily history in the private archive (both show only what is current)
.venv\Scripts\python.exe tools\notice_capture.py >> data\logs\notice_capture.log 2>&1
endlocal
