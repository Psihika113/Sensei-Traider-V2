# migrate_orders_add_price_columns.py
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import load_app_config


def get_db_path() -> Path:
    cfg = load_app_config(Path("config/app.toml"))
    # Поддержка обоих вариантов: cfg.db.path или cfg.db_path
    if hasattr(cfg, "db") and hasattr(cfg.db, "path"):
        return Path(cfg.db.path)
    if hasattr(cfg, "db_path"):
        return Path(cfg.db_path)  # type: ignore[attr-defined]
    raise RuntimeError("Cannot determine DB path from AppConfig")


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]  # row[1] = name
    return column in cols


def main() -> None:
    db_path = get_db_path()
    print(f"Using DB: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        changed = False

        for col in ("entry_price", "stop_price", "take_price"):
            if not column_exists(conn, "orders", col):
                print(f"Adding column '{col}' to 'orders'...")
                conn.execute(f"ALTER TABLE orders ADD COLUMN {col} REAL")
                changed = True
            else:
                print(f"Column '{col}' already exists, skipping.")

        if changed:
            conn.commit()
            print("Migration completed and committed.")
        else:
            print("No changes needed, schema already up to date.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
