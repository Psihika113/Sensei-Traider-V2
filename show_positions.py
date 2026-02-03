# -*- coding: utf-8 -*-
"""
show_positions.py — простой просмотр позиций по данным из БД SenseiTrader.

Считает net_qty по каждому символу на основе executions + orders
с учётом типа ноги (leg):
    - parent / PARENT  -> открытие позиции
    - take / stop      -> закрытие (обратный знак к parent)

Запуск:
    python show_positions.py
"""

import sqlite3
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple

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


def fetch_execs_with_orders(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Забираем все executions и джойним к ним orders по order_id.

    Возвращаем список dict'ов:
      {
        "order_id": ...,
        "leg": ...,
        "ts_utc": ...,
        "price": ...,
        "qty": ...,
        "fee": ...,
        "symbol": ...,
        "side": ...,
      }
    """
    exec_cols = get_table_columns(conn, "executions")
    order_cols = get_table_columns(conn, "orders")

    # Проверим, что нужные поля точно есть
    required_exec = {"order_id", "leg", "ts_utc", "price", "qty", "fee"}
    required_ord = {"order_id", "symbol", "side"}

    if not required_exec.issubset(set(exec_cols)):
        raise RuntimeError(f"В таблице executions не хватает колонок: {required_exec - set(exec_cols)}")

    if not required_ord.issubset(set(order_cols)):
        raise RuntimeError(f"В таблице orders не хватает колонок: {required_ord - set(order_cols)}")

    cur = conn.cursor()
    # Берём только то, что нам нужно
    cur.execute(
        """
        SELECT 
            e.order_id,
            e.leg,
            e.ts_utc,
            e.price,
            e.qty,
            e.fee,
            o.symbol,
            o.side
        FROM executions e
        JOIN orders o
          ON e.order_id = o.order_id
        ORDER BY e.rowid ASC
        """
    )
    rows = cur.fetchall()

    results: List[Dict[str, Any]] = []
    for row in rows:
        order_id, leg, ts_utc, price, qty, fee, symbol, side = row
        results.append(
            {
                "order_id": order_id,
                "leg": leg,
                "ts_utc": ts_utc,
                "price": float(price) if price is not None else 0.0,
                "qty": float(qty) if qty is not None else 0.0,
                "fee": float(fee) if fee is not None else 0.0,
                "symbol": symbol,
                "side": side,
            }
        )

    return results


def signed_qty(side: str, leg: str, qty: float) -> float:
    """
    Считаем подписанное количество с учётом направления сделки и типа ноги.

    Логика:
      - BUY + parent  -> +qty (открытие)
      - BUY + take/stop -> -qty (закрытие)
      - SELL + parent -> -qty (открытие шорта)
      - SELL + take/stop -> +qty (покрытие шорта)

    Если leg неизвестен — считаем как parent (открытие).
    """
    side_up = (side or "").upper()
    leg_low = (leg or "parent").lower()

    is_close_leg = leg_low in ("take", "stop")

    # Базовое направление для открывающей ноги
    if side_up == "BUY":
        base_sign = 1.0
    elif side_up == "SELL":
        base_sign = -1.0
    else:
        # На всякий случай: если side какой-то странный — считаем как BUY
        base_sign = 1.0

    if is_close_leg:
        # Закрытие — разворачиваем знак
        return -base_sign * qty
    else:
        # Открытие
        return base_sign * qty


def aggregate_positions(exec_with_orders: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Агрегируем позиции по символам.

    Для каждого символа считаем:
      - net_qty       — чистая позиция
      - total_fee     — суммарная комиссия
      - exec_count    — количество исполнений
    """
    positions: Dict[str, Dict[str, Any]] = {}

    for rec in exec_with_orders:
        symbol = rec["symbol"] or "UNKNOWN"
        side = rec["side"]
        leg = rec["leg"]
        qty = rec["qty"]
        fee = rec["fee"]

        if qty == 0:
            continue

        sqty = signed_qty(side, leg, qty)

        if symbol not in positions:
            positions[symbol] = {
                "net_qty": 0.0,
                "total_fee": 0.0,
                "exec_count": 0,
            }

        positions[symbol]["net_qty"] += sqty
        positions[symbol]["total_fee"] += fee
        positions[symbol]["exec_count"] += 1

    return positions


def print_positions(positions: Dict[str, Dict[str, Any]]) -> None:
    """
    Человекочитаемый вывод позиций.
    """
    if not positions:
        print("Пока нет позиций (таблица executions пуста или нет связей с orders).")
        return

    print("Текущие позиции по данным executions + orders:\n")

    for symbol in sorted(positions.keys()):
        pos = positions[symbol]
        print(f"Символ: {symbol}")
        print(f"  net_qty      : {pos['net_qty']}")
        print(f"  exec_count   : {pos['exec_count']}")
        print(f"  total_fee    : {pos['total_fee']}")
        print()  # пустая строка между символами


def main() -> None:
    db_path = get_db_path()

    if not db_path.exists():
        print(f"Файл БД не найден: {db_path}")
        return

    print(f"Используем БД: {db_path}\n")

    conn = sqlite3.connect(str(db_path))

    try:
        exec_with_orders = fetch_execs_with_orders(conn)
        positions = aggregate_positions(exec_with_orders)
        print_positions(positions)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
