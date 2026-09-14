@echo off
rem ============================================================
rem Campus Copilot - one-click launcher for the M1 chat CLI
rem
rem Why this file exists:
rem   The project env (.venv) is a CONDA env created with
rem   "conda create -p .venv", so:
rem     1) python.exe lives at .venv\python.exe
rem        there is NO .venv\Scripts\python.exe
rem     2) cmd's default "python" is conda base
rem        (E:\developTools), which has langchain NOT installed
rem   This script always uses the project interpreter, so it works
rem   from any directory, with or without conda activate.
rem
rem Usage: double-click it, or run  run_chat.cmd  in cmd.
rem
rem NOTE: keep this file ASCII-only AND CRLF. cmd.exe misparses
rem       UTF-8 Chinese characters and LF-only line endings.
rem ============================================================

rem cmd defaults to codepage 936 (GBK) while the app uses UTF-8;
rem force UTF-8 so Chinese input/output is not garbled.
chcp 65001 >nul

setlocal
set "PROJECT_DIR=%~dp0"
set "PY=%PROJECT_DIR%.venv\python.exe"
set "APP=%PROJECT_DIR%src\chat_cli.py"

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

rem When double-clicked the window closes instantly; keep it open on failure
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit code %EXIT_CODE%] the program ended with an error
    pause
)

endlocal & exit /b %EXIT_CODE%