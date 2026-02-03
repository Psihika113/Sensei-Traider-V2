# migrate_outbox.py  — добавляет недостающие колонки в таблицу outbox
import os, sqlite3, datetime as dt

DB_PATH = os.path.join("data", "trader.db")
if not os.path.exists(DB_PATH):
    raise SystemExit(f"DB not found: {DB_PATH}. Создай базу (schema.sql) и запусти снова.")

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# есть ли таблица?
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='outbox'")
if not cur.fetchone():
    raise SystemExit("Таблица 'outbox' не найдена. Прогони schema.sql, затем повтори миграцию.")

cur.execute("PRAGMA table_info(outbox)")
cols = {r[1] for r in cur.fetchall()}
print("Колонки до миграции:", sorted(cols))

def add(col, ddl):
    if col not in cols:
        print(" + добавляю:", col)
        cur.execute(ddl)

# согласуем с текущим кодом Outbox/OutboxWorker
add("channel",    "ALTER TABLE outbox ADD COLUMN channel TEXT NOT NULL DEFAULT 'tg'")
add("payload",    "ALTER TABLE outbox ADD COLUMN payload TEXT NOT NULL DEFAULT '{}'")
add("attempts",   "ALTER TABLE outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
add("last_error", "ALTER TABLE outbox ADD COLUMN last_error TEXT")
add("next_at",    "ALTER TABLE outbox ADD COLUMN next_at TEXT")
add("created_at", "ALTER TABLE outbox ADD COLUMN created_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'")
add("updated_at", "ALTER TABLE outbox ADD COLUMN updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'")

conn.commit()

cur.execute("PRAGMA table_info(outbox)")
cols_after = {r[1] for r in cur.fetchall()}
print("Колонки после миграции:", sorted(cols_after))
conn.close()
print("Outbox migration OK")
