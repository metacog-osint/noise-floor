@echo off
rem Daily community collectors and watch pollers, run by Windows Task Scheduler. Paths are relative to this file.
rem Output: data\community\*\digest_*.md and data\watch\digest_*.md; log: data\logs\collectors.log (all gitignored).
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
if not exist data\logs mkdir data\logs
echo === %DATE% %TIME% >> data\logs\collectors.log
rem The PC's scheduled tasks run this checkout's files, so it has to stay on main (15 Nov 2026: it sat on a docs
rem branch from 5 to 15 Nov and the tasks ran that branch's code). On main with no tracked changes, fast-forward
rem from GitHub so merged fixes reach this PC; on any other branch, log a warning and run as is.
set "NF_BRANCH="
for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "NF_BRANCH=%%b"
if /i "%NF_BRANCH%"=="main" (
  git diff --quiet HEAD -- 2>nul && git pull --ff-only --quiet origin main >> data\logs\collectors.log 2>&1
) else (
  echo WARNING: this checkout is on branch "%NF_BRANCH%", not main, so the scheduled tasks run that branch's code >> data\logs\collectors.log
)
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
rem Sentinel-1 C-band radar activity: newest complete day -> data\s1rfi\global (28-day windows) and the s1-data release
rem (map layer; Planetary Computer, no account; about 3 minutes a day)
.venv\Scripts\python.exe tools\s1_daily.py >> data\logs\s1_daily.log 2>&1
rem Sentinel-1/2/3 navigation receivers: newest days -> data\sentinel_gnss (E1 tables, E2 epochs) and private area
rem products in private\sentinel (trend, map; private config private\watch\satgnss.json). Nothing is uploaded.
.venv\Scripts\python.exe tools\sentinel_daily.py >> data\logs\sentinel_daily.log 2>&1
rem EASA FIR tables and the Baltic warnings page: daily history in the private archive (both show only what is current)
.venv\Scripts\python.exe tools\notice_capture.py >> data\logs\notice_capture.log 2>&1
rem Private archive (metacog-osint/tic-archive, release assets): today's NISAR state, which holds the detections
rem the public gate never publishes, and the D:-only collector data above. Last, so nothing waits on it; a failure
rem writes data\logs\ARCHIVE_FAILED.txt and makes this task's Last Run Result non-zero. Uses this PC's gh login.
.venv\Scripts\python.exe tools\pc_archive.py >> data\logs\pc_archive.log 2>&1
set "ARCHIVE_RC=%ERRORLEVEL%"
endlocal & exit /b %ARCHIVE_RC%
