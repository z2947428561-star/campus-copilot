@echo off
rem ============================================================
rem Campus Copilot - one-click launcher for the M6 web server
rem (FastAPI + SSE streaming + multi-user sessions)
rem
rem Same conda-layout notes as run_chat.cmd:
rem   python.exe lives at .venv\python.exe (NOT .venv\Scripts\)
rem
rem NOTE: keep this file ASCII-only AND CRLF. cmd.exe misparses
rem       UTF-8 Chinese characters and LF-only line endings.
rem ============================================================

chcp 65001 >nul

setlocal
set "PROJECT_DIR=%~dp0"
set "PY=%PROJECT_DIR%.venv\python.exe"

if not exist "%PY%" (
    echo [ERROR] Project interpreter not found:
    echo         %PY%
    pause
    exit /b 1
)

echo Starting Campus Copilot web server ...
echo Open http://127.0.0.1:8000 in your browser after startup.
echo Press Ctrl+C here to stop the server.

"%PY%" -m uvicorn src.server:app --host 127.0.0.1 --port 8000

if not "%ERRORLEVEL%"=="0" (
    echo.
    echo [exit code %ERRORLEVEL%] the server ended with an error
    pause
)

endlocal & exit /b %ERRORLEVEL%
