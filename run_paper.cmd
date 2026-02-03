@echo off
cd /d %~dp0
setlocal

REM === Telegram (поставь реальные) ===
set TELEGRAM_BOT_TOKEN=7356...Sku1xU
set TELEGRAM_CHAT_ID=870404759

REM === Google Sheets ===
set GOOGLE_SHEETS_CREDENTIALS_FILE=secrets\sa.json
set TEST_SPREADSHEET_ID=1-Z2JyY_1FnfVSNHJNVycjA3IEy6-relOHnFNF4mWSgU

python -m scripts.test_notify
python -m scripts.test_sheets
python .\run_service.py --config .\config\app.paper.toml

endlocal
