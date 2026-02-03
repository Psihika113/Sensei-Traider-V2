@echo off
cd /d C:\Users\Mass\Desktop\SenseiTrader
call .\.venv313\Scripts\activate
set TG_BOT_TOKEN=123:ABC
python run_service.py --config config/app.paper.toml
