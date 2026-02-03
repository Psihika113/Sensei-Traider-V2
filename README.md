# SenseiTrader v1

Детерминированный автоторговый контур: Sensei (LLM) → RiskGate → Executor → IBKR (брекеты/OCO) → SQLite → Google Sheets → Telegram.

## Требования
- Python 3.11.x
- TWS/IB Gateway (paper для теста), открытые порты
- Google Service Account JSON в `secrets/sa.json`
- Переменные окружения в `.env`

## Быстрый старт (paper)
```bash
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# секреты
mkdir secrets
# поместите креды сервисного аккаунта
# и укажите переменную окружения для Google Sheets
set GOOGLE_APPLICATION_CREDENTIALS=secrets/sa.json   # PowerShell: $env:GOOGLE_APPLICATION_CREDENTIALS="secrets/sa.json"

# переменные окружения
copy .env.example .env
# заполните значения в .env (TG, IBKR, spreadsheet_id и т.п.)

# подготовка БД (если нужно)
python -c "import sqlite3; sqlite3.connect('data/trader.db').close()"

# запуск сервиса (paper)
python run_service.py --config config/app.paper.toml
