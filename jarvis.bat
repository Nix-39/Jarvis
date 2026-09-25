@echo off
REM Starts the Jarvis chat using the project's own virtual environment.
REM No venv activation needed - double-click this file or run: jarvis
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Could not find .venv in %~dp0
    echo Create it with: py -3.13 -m venv .venv
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m core.orchestrator %*

REM Keep the window open if Jarvis crashed, so the error can be read.
if errorlevel 1 pause
