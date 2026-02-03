# -*- coding: utf-8 -*-
# show_orders2.py — отладочный просмотр таблицы orders

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import load_app_config


def main() -> int:
    print("=== SENSEI ORDERS DEBUG v2 ===")

    # 1) Загружаем конфиг и путь к БД
    try:
        cfg = load_app_config("config/app.toml")
        db_path = Path(cfg.db.path)
    except Exception as e:
        print("❌ Ошибка при загрузке config/app.toml или поля db.path:")
        print("   ", repr(e))
        return 1

    print(f"Using DB: {db_path}")

    if not db_path.exists():
        print("❌ Файл БД не найден по этому пути.")
        return 1

    # 2) Открываем SQLite
    try:
        conn = sqlite3.connect(db_path)
    except Exception as e:
        print("❌ Не удалось открыть БД:")
        print("   ", repr(e))
        return 1

    try:
        cur = conn.cursor()

        # 3) Проверяем структуру таблицы orders
        cur.execute("PRAGMA table_info(orders)")
        cols_info = cur.fetchall()
        if not cols_info:
            print("❌ Таблица 'orders' не найдена в БД.")
            return 1

        col_names = [c[1] for c in cols_info]
        print("\nColumns in 'orders':")
        for c in cols_info:
            # c: (cid, name, type, notnull, dflt_value, pk)
            print(f"  {c[1]} ({c[2]})")

        # 4) Читаем последние N ордеров
        limit = 20
        cur.execute(f"SELECT * FROM orders ORDER BY rowid DESC LIMIT {limit}")
        rows = cur.fetchall()

        if not rows:
            print("\nТаблица orders пуста.")
            return 0

        print(f"\nLast {len(rows)} orders:\n")

        for row in rows:
            print("-" * 40)
            for name, val in zip(col_names, row):
                print(f"{name:15}: {val}")
        print("-" * 40)

        return 0

    except Exception as e:
        print("❌ Ошибка при чтении таблицы 'orders':")
        print("   ", repr(e))
        return 1

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
