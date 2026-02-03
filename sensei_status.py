# -*- coding: utf-8 -*-
"""
sensei_status.py — быстрый "кокпит" состояния SenseiTrader.

Показывает:
    1) Общую сводку по реализованному PnL и закрытым сделкам.
    2) Последнюю закрытую сделку.
    3) Текущие позиции по символам (на базе executions + orders).
    4) Последние executions (id, время, ордер, цена, qty, leg).

Запуск:
    python sensei_status.py
"""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple

from show_pnl import (
    get_db_path,
    fetch_execs_with_orders,
    signed_qty,
)
from show_equity import build_equity


# ---------------------------------------------------------------------------
# ПОЗИЦИИ
# ---------------------------------------------------------------------------

def build_positions(exec_with_orders: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Строим текущие позиции по символам на основе executions.

    Возвращает dict:
        {
            "AAPL": {
                "net_qty": float,
                "exec_count": int,
                "total_fee": float,
            },
            ...
        }
    """
    positions: Dict[str, Dict[str, float]] = {}

    for rec in exec_with_orders:
        symbol = rec.get("symbol") or "UNKNOWN"
        side = rec.get("side")
        leg = rec.get("leg")
        qty = rec.get("qty", 0.0) or 0.0
        fee = rec.get("fee", 0.0) or 0.0

        if not qty:
            continue

        sqty = signed_qty(side, leg, qty)

        if symbol not in positions:
            positions[symbol] = {
                "net_qty": 0.0,
                "exec_count": 0,
                "total_fee": 0.0,
            }

        pos = positions[symbol]
        pos["net_qty"] += sqty
        pos["exec_count"] += 1
        pos["total_fee"] += fee

    # оставляем только ненулевые позиции
    positions = {
        sym: info
        for sym, info in positions.items()
        if abs(info["net_qty"]) > 1e-8
    }

    return positions


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНОЕ: ПОСЛЕДНИЙ ЗАКРЫТЫЙ ОРДЕР
# ---------------------------------------------------------------------------

def parse_ts(ts: str | None) -> datetime | None:
    """
    Пытаемся распарсить строки вида:
        '2025-11-03T11:36:16Z'
        '2025-12-03T13:43:17.600480+00:00'
    Возвращаем datetime или None.
    """
    if not ts:
        return None

    # Пытаемся несколько форматов по очереди
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt)
        except Exception:
            continue

    # Фоллбек: берём только первые 19 символов 'YYYY-MM-DDTHH:MM:SS'
    try:
        base = ts[:19]
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def pick_last_closed_order(closed_orders: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """
    Выбирает последний закрытый ордер по полю close_ts.
    Если закрытых ордеров нет — возвращает None.
    """
    if not closed_orders:
        return None

    def _key(rec: Dict[str, Any]) -> datetime:
        ts = parse_ts(rec.get("close_ts"))
        # если по какой-то причине не парсится — считаем очень старой датой
        return ts or datetime(1970, 1, 1)

    return max(closed_orders, key=_key)


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНОЕ: ПОСЛЕДНИЕ EXECUTIONS
# ---------------------------------------------------------------------------

def get_last_executions(
    exec_with_orders: List[Dict[str, Any]],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Возвращает последние executions по времени ts_utc (если есть), иначе по id.
    """
    def _key(rec: Dict[str, Any]) -> Tuple[int, int]:
        ts = parse_ts(rec.get("ts_utc"))
        ts_ord = ts.toordinal() * 86400 + ts.hour * 3600 + ts.minute * 60 + ts.second if ts else 0
        # id может быть int или строкой, пытаемся привести к int
        rid = rec.get("exec_id") or rec.get("id")
        try:
            rid_int = int(rid)
        except Exception:
            rid_int = 0
        return (ts_ord, rid_int)

    sorted_execs = sorted(exec_with_orders, key=_key, reverse=True)
    return sorted_execs[:limit]


# ---------------------------------------------------------------------------
# ПЕЧАТЬ СТАТУСА
# ---------------------------------------------------------------------------

def print_status(
    closed_orders: List[Dict[str, Any]],
    open_orders_count: int,
    positions: Dict[str, Dict[str, float]],
    last_execs: List[Dict[str, Any]],
) -> None:
    """
    Печатает консольный дашборд.
    """

    print("=== SENSEI STATUS SNAPSHOT ===\n")

    # ---- 1. Общая сводка по закрытым ордерам ----
    if not closed_orders:
        print("Закрытых ордеров пока нет.\n")
        total_realized = 0.0
    else:
        total_realized = sum(float(o.get("realized_pnl", 0.0) or 0.0) for o in closed_orders)
        best = max(closed_orders, key=lambda o: float(o.get("realized_pnl", 0.0) or 0.0))
        worst = min(closed_orders, key=lambda o: float(o.get("realized_pnl", 0.0) or 0.0))

        print("=== PnL сводка по истории ===")
        print(f"Всего закрытых ордеров : {len(closed_orders)}")
        print(f"Суммарный realized PnL : {total_realized:.2f}")
        print(f"Лучший ордер           : {best.get('order_id')}  ({float(best.get('realized_pnl', 0.0) or 0.0):.2f})")
        print(f"Худший ордер           : {worst.get('order_id')} ({float(worst.get('realized_pnl', 0.0) or 0.0):.2f})")
        print()

    # ---- 2. Последний закрытый ордер ----
    last_closed = pick_last_closed_order(closed_orders)
    print("=== Последний закрытый ордер ===")
    if last_closed is None:
        print("Ещё нет закрытых ордеров.\n")
    else:
        print(f"close_ts     : {last_closed.get('close_ts')}")
        print(f"order_id     : {last_closed.get('order_id')}")
        print(f"symbol       : {last_closed.get('symbol')}")
        print(f"side         : {last_closed.get('side')}")
        print(f"execs        : {last_closed.get('execs')}")
        print(f"realized_pnl : {float(last_closed.get('realized_pnl', 0.0) or 0.0):.2f}")
        print(f"equity_after : {float(last_closed.get('equity_after', 0.0) or 0.0):.2f}")
        print()

    # ---- 3. Текущие позиции ----
    print("=== Текущие позиции (по executions) ===\n")
    if not positions:
        print("Открытых позиций нет.\n")
    else:
        for symbol, info in positions.items():
            net_qty = info["net_qty"]
            direction = "LONG" if net_qty > 0 else "SHORT"

            print(f"Символ: {symbol}")
            print(f"  Направление : {direction}")
            print(f"  net_qty     : {net_qty}")
            print(f"  exec_count  : {info['exec_count']}")
            print(f"  total_fee   : {info['total_fee']}\n")

    # ---- 4. Последние executions ----
    print("=== Последние executions ===\n")
    if not last_execs:
        print("Записей в executions нет.\n")
    else:
        for rec in last_execs:
            print(f"id        : {rec.get('exec_id') or rec.get('id')}")
            print(f"ts_utc    : {rec.get('ts_utc')}")
            print(f"order_id  : {rec.get('order_id')}")
            print(f"symbol    : {rec.get('symbol')}")
            print(f"side      : {rec.get('side')}")
            print(f"leg       : {rec.get('leg')}")
            print(f"price     : {rec.get('price')}")
            print(f"qty       : {rec.get('qty')}")
            print(f"fee       : {rec.get('fee')}")
            print("-" * 40)
        print()

    # ---- 5. Инфо по открытым ордерам (по equity-логике) ----
    print(f"Открытых ордеров (net_qty_order != 0): {open_orders_count}")
    print(f"Суммарный realized PnL по истории    : {total_realized:.2f}")
    print()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main(argv: List[str]) -> None:
    db_path: Path = get_db_path()

    if not db_path.exists():
        print(f"Файл БД не найден: {db_path}")
        return

    print(f"Используем БД: {db_path}\n")

    conn = sqlite3.connect(str(db_path))
    try:
        exec_with_orders = fetch_execs_with_orders(conn)

        # closed_orders и open_orders_count — та же логика, что в show_equity
        closed_orders, open_orders_count = build_equity(exec_with_orders)

        positions = build_positions(exec_with_orders)
        last_execs = get_last_executions(exec_with_orders, limit=10)

        print_status(
            closed_orders=closed_orders,
            open_orders_count=open_orders_count,
            positions=positions,
            last_execs=last_execs,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv)
