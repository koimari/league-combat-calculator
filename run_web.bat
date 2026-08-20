@echo off
rem Launch the LoL calculator web interface and open it in the browser.
cd /d "%~dp0"
rem Dev mode: enables the Update Data button / wiki re-scrape endpoint,
rem which deployed sites keep disabled (see src/app.py _dev_mode).  The
rem endpoint also needs a token shared by every worker; without one it stays
rem 404 (see src/app.py _dev_update_token).
set LOL_CALC_DEV=1
set LOL_CALC_DEV_UPDATE_TOKEN=local-development-update
start "" http://127.0.0.1:5000
python -m flask --app src.app run
