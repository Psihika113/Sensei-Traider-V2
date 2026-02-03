# scripts/migrate_p1_exec_positions.py
# -*- coding: utf-8 -*-
import sqlite3, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # работать из корня проекта

DB = ROOT / "data" / "trader.db"
DB.parent.mkdir(parents=True, exist_ok=True)

def safe_alter(cur, sql):
    try:
        cur.execute(sql)
    except Exception as e:
        if "duplicate column" in str(e).lower():
            pass
        else:
            raise

def main():
    if not DB.exists():
        # если базы нет — создадим пустую через schema.sql (если он у тебя есть)
        schema = ROOT / "schema.sql"
        conn = sqlite3.connect(DB.as_posix())
        if schema.exists():
            conn.executescript(schema.read_text(encoding="utf-8"))
            conn.commit()
        conn.close()

    conn = sqlite3.connect(DB.as_posix())
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    safe_alter(cur, "ALTER TABLE executions ADD COLUMN symbol TEXT;")
    safe_alter(cur, "ALTER TABLE executions ADD COLUMN side TEXT;")
    safe_alter(cur, "ALTER TABLE executions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0.0;")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_exec_ts ON executions(ts_utc);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_exec_order ON executions(order_id);")
    # schema_version у тебя INTEGER, сохраним совместимо:
    cur.execute("INSERT OR IGNORE INTO schema_version(version, applied_at_utc) VALUES (?, datetime('now'))", (1001,))
    conn.commit()
    conn.close()
    print("Migration OK")

if __name__ == "__main__":
    main()
