# -*- coding: utf-8 -*-
"""
show_trades.py — сервисный скрипт для просмотра последних «сделок»:
исполнения (executions) + связанный ордер (orders).

Запуск:
    python show_trades.py
    python show_trades.py 20       # показать последние 20 исполнений
"""

import sqlite3
import sys
import os
from pathlib import Path
from typing import List, Tuple, Any, Optional


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


def get_table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """
    Возвращает список имён колонок для таблицы `table` через PRAGMA.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    info = cur.fetchall()
    if not info:
        raise RuntimeError(f"Таблица '{table}' не найдена или пуста PRAGMA table_info({table})")
    return [row[1] for row in info]


def fetch_last_executions(
    conn: sqlite3.Connection,
    limit: int = 10,
) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """
    Забираем последние executions по rowid.

    Возвращаем:
      - список имён колонок executions
      - список строк
    """
    exec_cols = get_table_columns(conn, "executions")
    cur = conn.cursor()
    cur.execute("SELECT * FROM executions ORDER BY rowid DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    return exec_cols, rows


def fetch_order_by_id(
    conn: sqlite3.Connection,
    order_id: str,
) -> Tuple[Optional[List[str]], Optional[Tuple[Any, ...]]]:
    """
    По order_id достаём строку из таблицы orders.

    Если ордер не найден — возвращаем (None, None).
    """
    cur = conn.cursor()

    # Проверяем, что таблица вообще есть и узнаём её колонки
    try:
        order_cols = get_table_columns(conn, "orders")
    except RuntimeError:
        # Если таблицы orders нет — считаем, что ордеров нет
        return None, None

    cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = cur.fetchone()
    if row is None:
        return None, None

    return order_cols, row


def print_trades(
    exec_cols: List[str],
    exec_rows: List[Tuple[Any, ...]],
    conn: sqlite3.Connection,
) -> None:
    """
    Человеческий вывод: на каждое execution показываем сам execution и связанный order (если есть).
    """
    if not exec_rows:
        print("В таблице executions пока нет записей.")
        return

    print(f"\nПоследние {len(exec_rows)} исполнений (с привязкой к orders):\n")

    for idx, exec_row in enumerate(exec_rows, 1):
        # Преобразуем execution в dict для удобства
        exec_data = dict(zip(exec_cols, exec_row))
        order_id = str(exec_data.get("order_id"))

        print(f"=== trade #{idx} ===")
        print("--- Execution ---")
        for name in exec_cols:
            print(f"{name:12}: {exec_data.get(name)}")

        # Тащим связанный ордер
        order_cols, order_row = fetch_order_by_id(conn, order_id)

        if order_row is None:
            print("\n(Связанный ордер в таблице 'orders' не найден)\n")
            continue

        order_data = dict(zip(order_cols, order_row))

        print("\n--- Order ---")
        for name in order_cols:
            print(f"{name:12}: {order_data.get(name)}")

        print()  # пустая строка между трейдами


def main() -> None:
    # Лимит из аргументов командной строки
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
        exec_cols, exec_rows = fetch_last_executions(conn, limit=limit)
        print_trades(exec_cols, exec_rows, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
