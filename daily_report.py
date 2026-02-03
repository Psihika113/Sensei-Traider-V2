# -*- coding: utf-8 -*-
"""
daily_report.py — сводный дневной отчёт по данным БД SenseiTrader.

Даёт:
    1) PnL по закрытым ордерам, агрегированный по датам (equity по дням).
    2) Итоговую статистику по выбранному периоду.
    3) Снимок текущих позиций на базе executions.

Период задаётся так:
    python daily_report.py           -> весь период
    python daily_report.py 30        -> последние 30 дней (включая сегодня)

Зависимости:
    - show_pnl.get_db_path
    - show_pnl.fetch_execs_with_orders
    - show_pnl.signed_qty
    - show_equity.build_equity
"""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Tuple

from show_pnl import (
    get_db_path,
    fetch_execs_with_orders,
    signed_qty,
)
from show_equity import build_equity


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ---------------------------------------------------------------------------

def parse_days_back(argv: List[str]) -> int | None:
    """
    Парсим количество дней из аргументов командной строки.

    Примеры:
        []              -> None  (значит "весь период")
        ["daily_report.py", "30"] -> 30
    """
    if len(argv) < 2:
        return None

    try:
        days = int(argv[1])
        if days <= 0:
            return None
        return days
    except ValueError:
        return None


def extract_date(ts: str | None) -> date | None:
    """
    Берёт строку вида '2025-11-03T11:36:16Z' или '2025-12-03T13:43:17.600480+00:00'
    и возвращает date(2025, 11, 3).

    Если формат неожиданно другой или ts пустой — возвращает None.
    """
    if not ts:
        return None

    # Берём первые 10 символов 'YYYY-MM-DD'
    s = ts[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


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

    # Фильтруем только реальные открытые позиции (ненулевая qty)
    positions = {
        sym: info
        for sym, info in positions.items()
        if abs(info["net_qty"]) > 1e-8
    }

    return positions


# ---------------------------------------------------------------------------
# ОТЧЁТ ПО ДНЯМ
# ---------------------------------------------------------------------------

def build_daily_pnl(
    closed_orders: List[Dict[str, Any]],
    days_back: int | None,
) -> Tuple[Dict[date, Dict[str, float]], float]:
    """
    Агрегирует закрытые ордера по датам.

    Параметры:
        closed_orders — список закрытых ордеров (из build_equity)
        days_back     — если None -> используем весь период,
                        если число -> только даты >= today - (days_back - 1)

    Возвращает:
        (daily_stats, period_realized_pnl)

        daily_stats: dict[date] = {
            "trades": int,
            "realized_pnl": float,
        }

        period_realized_pnl: суммарный PnL за выбранный период.
    """
    today = date.today()
    cutoff_date: date | None = None

    if days_back is not None:
        cutoff_date = today - timedelta(days=days_back - 1)

    daily_stats: Dict[date, Dict[str, float]] = {}

    for rec in closed_orders:
        d = extract_date(rec.get("close_ts"))
        if d is None:
            continue

        # Фильтрация по периоду, если указано
        if cutoff_date is not None and d < cutoff_date:
            continue

        pnl = float(rec.get("realized_pnl", 0.0) or 0.0)

        if d not in daily_stats:
            daily_stats[d] = {
                "trades": 0,
                "realized_pnl": 0.0,
            }

        daily_stats[d]["trades"] += 1
        daily_stats[d]["realized_pnl"] += pnl

    # Суммарный PnL за период
    period_realized_pnl = sum(v["realized_pnl"] for v in daily_stats.values())

    return daily_stats, period_realized_pnl


# ---------------------------------------------------------------------------
# ПЕЧАТЬ ОТЧЁТА
# ---------------------------------------------------------------------------

def print_daily_report(
    closed_orders: List[Dict[str, Any]],
    positions: Dict[str, Dict[str, float]],
    days_back: int | None,
) -> None:
    """
    Красивый вывод дневного отчёта.
    """
    # --- 1. Агрегируем PnL по дням ---
    daily_stats, period_realized_pnl = build_daily_pnl(closed_orders, days_back)

    # Заголовок
    if days_back is None:
        print("=== Ежедневный отчёт по закрытым сделкам (весь период) ===\n")
    else:
        print(f"=== Ежедневный отчёт по закрытым сделкам (последние {days_back} дней, включая сегодня) ===\n")

    if not daily_stats:
        print("За выбранный период закрытых сделок нет.\n")
    else:
        # Сортируем даты по возрастанию
        all_dates = sorted(daily_stats.keys())

        print(f"{'Дата':<12} {'Сделок':>8} {'Realized PnL':>16} {'Equity (внутри периода)':>26}")
        print("-" * 70)

        equity = 0.0
        for d in all_dates:
            trades = daily_stats[d]["trades"]
            pnl = daily_stats[d]["realized_pnl"]
            equity += pnl
            print(
                f"{d.isoformat():<12} "
                f"{trades:>8d} "
                f"{pnl:>16.2f} "
                f"{equity:>26.2f}"
            )

        print()

        # Итоги по периоду
        total_trades = sum(v["trades"] for v in daily_stats.values())
        best_day = max(daily_stats.items(), key=lambda kv: kv[1]["realized_pnl"])
        worst_day = min(daily_stats.items(), key=lambda kv: kv[1]["realized_pnl"])

        print("=== Итоги по выбранному периоду ===\n")
        print(f"Всего дней с активностью : {len(daily_stats)}")
        print(f"Всего закрытых сделок    : {total_trades}")
        print(f"Суммарный realized PnL   : {period_realized_pnl:.2f}")
        print(f"Лучший день              : {best_day[0].isoformat()}  ({best_day[1]['realized_pnl']:.2f})")
        print(f"Худший день              : {worst_day[0].isoformat()}  ({worst_day[1]['realized_pnl']:.2f})")
        print()

    # --- 2. Снимок текущих позиций ---
    print("=== Текущие позиции (по executions) ===\n")

    if not positions:
        print("Открытых позиций нет.\n")
    else:
        for symbol, info in positions.items():
            net_qty = info["net_qty"]
            exec_count = info["exec_count"]
            total_fee = info["total_fee"]

            direction = "LONG" if net_qty > 0 else "SHORT"

            print(f"Символ: {symbol}")
            print(f"  Направление : {direction}")
            print(f"  net_qty     : {net_qty}")
            print(f"  exec_count  : {exec_count}")
            print(f"  total_fee   : {total_fee}\n")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main(argv: List[str]) -> None:
    # 1) Период отчёта
    days_back = parse_days_back(argv)

    # 2) Путь к БД
    db_path: Path = get_db_path()

    if not db_path.exists():
        print(f"Файл БД не найден: {db_path}")
        return

    print(f"Используем БД: {db_path}\n")

    # 3) Подключаемся к БД и вытаскиваем executions + orders
    conn = sqlite3.connect(str(db_path))
    try:
        exec_with_orders = fetch_execs_with_orders(conn)

        # 4) Закрытые ордера (используем ту же логику, что в show_equity)
        closed_orders, open_orders_count = build_equity(exec_with_orders)

        # 5) Позиции по символам
        positions = build_positions(exec_with_orders)

        # 6) Печатаем отчёт
        print_daily_report(closed_orders, positions, days_back)

        # Дополнительно можно вывести количество открытых ордеров (не позиций, а именно ордеров)
        print(f"Открытых ордеров (по order_id, где net_qty_order != 0): {open_orders_count}")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv)
