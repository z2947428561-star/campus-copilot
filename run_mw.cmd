@echo off
rem ============================================================
rem Campus Copilot - one-click launcher for the M3 middleware CLI
rem (PII redaction / summarization / model fallback / HITL / audit logs)
rem
rem Same conda-layout notes as run_chat.cmd:
rem   python.exe lives at .venv\python.exe (NOT .venv\Scripts\)
rem   cmd's default "python" is conda base without langchain
rem
rem NOTE: keep this file ASCII-only AND CRLF. cmd.exe misparses
rem       UTF-8 Chinese characters and LF-only line endings.
rem ============================================================

chcp 65001 >nul

setlocal
set "PROJECT_DIR=%~dp0"
set "PY=%PROJECT_DIR%.venv\python.exe"
set "APP=%PROJECT_DIR%src\chat_agent_mw_cli.py"

if not exist "%PY%" (
    echo [ERROR] Project interpreter not found:
    echo         %PY%
    echo.
    echo Create the environment first:
    echo         conda create -p "%PROJECT_DIR%.venv" -c conda-forge python=3.13 -y
    echo         "%PY%" -m pip install -r "%PROJECT_DIR%requirements.txt"
    echo.
    pause
    exit /b 1
)

"%PY%" "%APP%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit code %EXIT_CODE%] the program ended with an error
    pause
)

endlocal & exit /b %EXIT_CODE%
