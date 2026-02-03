@echo off
cd /d "%~dp0"
set "PY=%CD%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [ERR] Python venv not found: %PY%
  pause
  exit /b 2
)

set SENSEI_MODE=offline
set SENSEI_DB_PATH=data\trader.db

"%PY%" -m app.service --config config\app.toml
pause
