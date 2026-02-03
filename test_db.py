# test_db.py
import sqlite3
from pathlib import Path

from app.config import load_app_config


def print_tables(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cur.fetchall()]
    print("Tables in trader.db:")
    if not tables:
        print("  (no tables found)")
    else:
        for name in tables:
            print("  -", name)
    print()
    return


def print_table_schema(cur: sqlite3.Cursor, table: str) -> None:
    print(f"Schema for table '{table}':")
    cur.execute(f"PRAGMA table_info({table});")
    rows = cur.fetchall()
    if not rows:
        print("  (no columns)")
        print()
        return
    for cid, name, col_type, notnull, dflt_value, pk in rows:
        pk_flag = " PK" if pk else ""
        print(f"  - {name} {col_type} (NOT NULL={bool(notnull)}){pk_flag}")
    print()


def main() -> None:
    cfg = load_app_config("config/app.toml")
    db_path = Path(cfg.db.path)

    print(f"DB path from config: {db_path}")
    print(f"Exists on disk: {db_path.exists()}\n")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1) список таблиц
    print_tables(cur)

    # 2) структура важных таблиц
    for tbl in ("orders", "executions", "outbox"):
        print_table_schema(cur, tbl)

    conn.close()


if __name__ == "__main__":
    main()
