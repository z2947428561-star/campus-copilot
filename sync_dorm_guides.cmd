@echo off
setlocal
cd /d "%~dp0"
".venv\python.exe" -X utf8 scripts\sync_dorm_guides.py %*
exit /b %errorlevel%
