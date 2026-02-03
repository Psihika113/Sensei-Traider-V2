# -*- coding: utf-8 -*-
"""
show_executions.py — сервисный скрипт для просмотра последних исполнений.

Запуск:
    python show_executions.py
    python show_executions.py 20        # показать последние 20 исполнений
"""

import sqlite3
import sys
import os
from pathlib import Path
from typing import List, Tuple, Any


def get_db_path() -> Path:
    """
    Универсальный выбор БД:
    - если есть SENSEI_DB_PATH -> берём её;
    - иначе по умолчанию data/trader.db в корне проекта.
    """
    root = Path(__file__).resolve().parent

    env = os.getenv("SENSEI_DB_PATH")
    if env:
        p = Path(env)
        # если указали относительный путь (типа data\trader_offline_sandbox.db) —
        # считаем его относительно корня проекта
        if not p.is_absolute():
            return (root / p).resolve()
        return p

    # дефолт: старая логика
    return root / "data" / "trader.db"


def fetch_last_executions(conn: sqlite3.Connection, limit: int = 10) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """
    Забираем последние executions по rowid (или любой другой естественной вставке).

    Делаем максимально универсально:
      - сначала читаем список колонок через PRAGMA table_info;
      - потом SELECT * FROM executions ORDER BY rowid DESC LIMIT ?;
      - возвращаем имена колонок и строки.
    """
    cur = conn.cursor()

    # Узнаём структуру таблицы
    cur.execute("PRAGMA table_info(executions)")
    cols_info = cur.fetchall()
    if not cols_info:
        raise RuntimeError("Таблица 'executions' не найдена или пуста PRAGMA table_info(executions)")

    col_names = [row[1] for row in cols_info]  # 2-й столбец = имя колонки

    # Забираем последние N записей
    cur.execute("SELECT * FROM executions ORDER BY rowid DESC LIMIT ?", (limit,))
    rows = cur.fetchall()

    return col_names, rows


def print_executions(col_names: List[str], rows: List[Tuple[Any, ...]]) -> None:
    """
    Читаемо печатаем результаты.
    """
    if not rows:
        print("В таблице executions пока нет записей.")
        return

    print(f"\nПоследние {len(rows)} исполнений:\n")

    for idx, row in enumerate(rows, 1):
        print(f"--- exec #{idx} ---")
        for name, value in zip(col_names, row):
            print(f"{name:12}: {value}")
        print()


def main() -> None:
    # Разбираем аргументы: можно передать лимит
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            print(f"Некорректный лимит '{sys.argv[1]}', используем 10.")
            limit = 10
    else:
        limit = 10

    db_path = get_db_path()

    if not db_path.exists():
        print(f"Файл БД не найден: {db_path}")
        return

    print(f"Используем БД: {db_path}\n")

    conn = sqlite3.connect(str(db_path))

    try:
        col_names, rows = fetch_last_executions(conn, limit=limit)
        print_executions(col_names, rows)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
