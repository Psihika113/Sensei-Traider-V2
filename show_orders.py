# -*- coding: utf-8 -*-
# show_orders.py

import os
import sys
import sqlite3
from pathlib import Path


def _resolve_db_path(default_rel: str = r"data\trader.db") -> Path:
    """
    Priority:
      1) CLI: --db <path> or --db=<path>
      2) ENV: SENSEI_DB_PATH
      3) DEFAULT: project-relative default_rel
    """
    argv = sys.argv[1:]

    # 1) CLI
    for i, a in enumerate(argv):
        if a == "--db" and i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser()
        if a.startswith("--db="):
            return Path(a.split("=", 1)[1]).expanduser()

    # 2) ENV
    env = os.environ.get("SENSEI_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser()

    # 3) DEFAULT
    return (Path(__file__).parent / default_rel)


DB_PATH = _resolve_db_path()


def main() -> None:
    db_abs = DB_PATH
    if not db_abs.is_absolute():
        db_abs = (Path(__file__).parent / DB_PATH).resolve()

    print(f"Используем БД: {db_abs}")

    conn = sqlite3.connect(str(db_abs))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='orders'
        """
    )
    row = cur.fetchone()
    if not row:
        print("\nТаблица 'orders' не найдена в БД.")
        return

    limit = 20
    cur.execute(
        """
        SELECT *
        FROM orders
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()

    if not rows:
        print("\nВ таблице 'orders' пока нет записей.")
        return

    print(f"\nПоследние {len(rows)} ордеров:\n")

    for r in rows:
        print("-" * 40)

        def get(col, default="-"):
            return r[col] if col in r.keys() else default

        print(f"id         : {get('id')}")
        print(f"order_id   : {get('order_id')}")
        print(f"symbol     : {get('symbol')}")
        print(f"side       : {get('side')}")
        print(f"qty        : {get('qty')}")
        print(f"status     : {get('status')}")
        print(f"reason     : {get('reason')}")
        print(f"created_ts : {get('created_ts')}")
        print(f"order_ref  : {get('order_ref')}")

    conn.close()


if __name__ == "__main__":
    main()
