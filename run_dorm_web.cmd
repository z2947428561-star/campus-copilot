@echo off
cd /d "%~dp0"
if exist ".venv\python.exe" (
  ".venv\python.exe" scripts\run_dorm_web.py %*
) else (
  ".venv\Scripts\python.exe" scripts\run_dorm_web.py %*
)
pause
