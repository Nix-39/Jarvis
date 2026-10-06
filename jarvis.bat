@echo off
REM Chat with Jarvis. Jarvis Core runs in the background (Task Scheduler task
REM "Jarvis Core"); this window is only a client that talks to it.
REM No venv activation needed - double-click this file or run: jarvis
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Could not find .venv in %~dp0
    echo Create it with: py -3.13 -m venv .venv
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m clients.terminal %*

REM Keep the window open on errors, so the message can be read.
if errorlevel 1 pause
