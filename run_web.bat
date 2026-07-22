@echo off
rem Launch the LoL calculator web interface and open it in the browser.
cd /d "%~dp0"
rem Dev mode: enables the Update Data button / wiki re-scrape endpoint,
rem which deployed sites keep disabled (see src/app.py _dev_mode).
set LOL_CALC_DEV=1
start "" http://127.0.0.1:5000
python -m flask --app src.app run
