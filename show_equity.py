# -*- coding: utf-8 -*-
"""
show_equity.py — текстовая equity-кривая и расширенная статистика по данным БД SenseiTrader.

Использует вспомогательные функции из show_pnl.py:
    - get_db_path()
    - fetch_execs_with_orders()
    - signed_qty()

Идея:
    1. Берём все executions + orders.
    2. Группируем по order_id.
    3. Для каждого order_id считаем:
        - net_qty_order  — Σ signed_qty (BUY/SELL + parent/take/stop)
        - sum_leg        — Σ (signed_qty * price)
        - total_fee      — Σ fee
        - close_ts       — максимальный ts_utc среди исполнений ордера
        - realized_pnl   — если net_qty_order == 0 (позиция по ордеру закрыта)
    4. Сортируем закрытые ордера по close_ts (времени закрытия).
    5. Строим кумулятивную equity-кривую:
        equity_after_n = Σ realized_pnl[0..n].
    6. Считаем расширенную статистику:
        - winrate
        - средний профит / убыток
        - profit factor
        - максимальная просадка по equity (max drawdown).
"""

from typing import Dict, Any, List, Tuple

from show_pnl import (
    get_db_path,
    fetch_execs_with_orders,
    signed_qty,
)

import sqlite3
from pathlib import Path


def build_equity(exec_with_orders: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Строим структуру по ордерам и считаем realized PnL и equity.

    Возвращает:
        closed_orders: список dict
            {
                "order_id": ...,
                "symbol": ...,
                "side": ...,
                "close_ts": ... (строка ts_utc),
                "realized_pnl": float,
                "total_fee": float,
                "exec_count": int,
                "equity_after": float,  # заполняется позже
            }

        open_orders_count: int — количество ордеров, у которых net_qty_order != 0.
    """
    by_order: Dict[str, Dict[str, Any]] = {}

    # --- 1. Агрегируем по order_id ---
    for rec in exec_with_orders:
        order_id = rec["order_id"]
        symbol = rec["symbol"] or "UNKNOWN"
        side = rec["side"]
        leg = rec["leg"]
        qty = rec["qty"]
        price = rec["price"]
        fee = rec["fee"]
        ts_utc = rec["ts_utc"]

        if qty == 0:
            continue

        sqty = signed_qty(side, leg, qty)
        contrib = sqty * price

        if order_id not in by_order:
            by_order[order_id] = {
                "symbol": symbol,
                "side": side,
                "net_qty_order": 0.0,
                "sum_leg": 0.0,
                "total_fee": 0.0,
                "execs": [],        # для определения времени закрытия
                "exec_count": 0,
            }

        data = by_order[order_id]
        data["net_qty_order"] += sqty
        data["sum_leg"] += contrib
        data["total_fee"] += fee
        data["exec_count"] += 1
        data["execs"].append(ts_utc)

    # --- 2. Выделяем закрытые ордера и считаем PnL ---
    closed_orders: List[Dict[str, Any]] = []
    open_orders_count = 0

    for order_id, data in by_order.items():
        net_qty_order = data["net_qty_order"]
        sum_leg = data["sum_leg"]
        total_fee = data["total_fee"]
        exec_count = data["exec_count"]
        symbol = data["symbol"]
        side = data["side"]
        exec_ts_list = [ts for ts in data["execs"] if ts is not None]

        if abs(net_qty_order) < 1e-8:
            # Позиция по ордеру закрыта -> считаем денежный результат
            cash = -sum_leg
            realized_pnl = cash - total_fee

            # Время "закрытия" ордера считаем как максимум ts_utc по его исполнений
            close_ts = max(exec_ts_list) if exec_ts_list else ""

            closed_orders.append(
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "close_ts": close_ts,
                    "realized_pnl": realized_pnl,
                    "total_fee": total_fee,
                    "exec_count": exec_count,
                }
            )
        else:
            open_orders_count += 1

    # --- 3. Сортируем закрытые ордера по времени закрытия ---
    closed_orders.sort(key=lambda rec: rec["close_ts"])

    # --- 4. Считаем equity-кривую (накопленный realized PnL) ---
    equity = 0.0
    for rec in closed_orders:
        equity += rec["realized_pnl"]
        rec["equity_after"] = equity

    return closed_orders, open_orders_count


def calc_advanced_stats(closed_orders: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Считает расширенную статистику по списку закрытых ордеров.

    Возвращает dict:
        {
            "total_closed": int,
            "total_realized": float,
            "best_trade": float,
            "worst_trade": float,
            "wins": int,
            "losses": int,
            "breakeven": int,
            "winrate_pct": float,
            "avg_win": float,
            "avg_loss": float,
            "profit_factor": float,
            "max_drawdown": float,
        }
    """
    total_closed = len(closed_orders)
    total_realized = sum(rec["realized_pnl"] for rec in closed_orders) if closed_orders else 0.0

    if closed_orders:
        best_trade = max(rec["realized_pnl"] for rec in closed_orders)
        worst_trade = min(rec["realized_pnl"] for rec in closed_orders)
    else:
        best_trade = 0.0
        worst_trade = 0.0

    # --- Win / Loss / Breakeven ---
    wins_list = [rec["realized_pnl"] for rec in closed_orders if rec["realized_pnl"] > 0]
    losses_list = [rec["realized_pnl"] for rec in closed_orders if rec["realized_pnl"] < 0]
    breakeven_list = [rec["realized_pnl"] for rec in closed_orders if abs(rec["realized_pnl"]) < 1e-8]

    wins = len(wins_list)
    losses = len(losses_list)
    breakeven = len(breakeven_list)

    winrate_pct = (wins / total_closed * 100.0) if total_closed > 0 else 0.0

    avg_win = sum(wins_list) / wins if wins > 0 else 0.0
    avg_loss = sum(losses_list) / losses if losses > 0 else 0.0  # будет отрицательным

    # --- Profit factor: сумма профитных / |сумма убыточных| ---
    gross_profit = sum(wins_list)
    gross_loss = sum(losses_list)  # отрицательное или 0
    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss) if abs(gross_loss) > 1e-8 else 0.0
    else:
        profit_factor = 0.0  # нет убыточных сделок -> формально бесконечность, но ставим 0.0 для устойчивости

    # --- Max drawdown по equity ---
    # Здесь используем поле equity_after в closed_orders (уже накопленный PnL).
    max_drawdown = 0.0
    peak = float("-inf")

    for rec in closed_orders:
        eq = rec["equity_after"]
        if eq > peak:
            peak = eq
        drawdown = peak - eq
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return {
        "total_closed": total_closed,
        "total_realized": total_realized,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "winrate_pct": winrate_pct,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
    }


def print_equity(closed_orders: List[Dict[str, Any]], open_orders_count: int) -> None:
    """
    Красивый вывод equity-кривой и статистики.
    """
    print("=== Equity по закрытым ордерам (только реализованный PnL) ===\n")

    if not closed_orders:
        print("Закрытых ордеров пока нет.\n")
    else:
        # Шапка
        print(
            f"{'#':<3} {'close_ts':<30} {'order_id':<24} {'symbol':<8} "
            f"{'side':<6} {'execs':<5} {'realized_pnl':>14} {'equity_after':>14}"
        )
        print("-" * 110)

        for idx, rec in enumerate(closed_orders, start=1):
            print(
                f"{idx:<3} "
                f"{rec['close_ts']:<30} "
                f"{rec['order_id']:<24} "
                f"{rec['symbol']:<8} "
                f"{str(rec['side']):<6} "
                f"{rec['exec_count']:<5d} "
                f"{rec['realized_pnl']:>14.2f} "
                f"{rec['equity_after']:>14.2f}"
            )

        print()

    # --- Базовая сводка ---
    stats = calc_advanced_stats(closed_orders)

    print("=== Сводка по PnL ===\n")
    print(f"Всего закрытых ордеров : {stats['total_closed']}")
    print(f"Суммарный realized PnL : {stats['total_realized']:.2f}")
    print(f"Лучший PnL по сделке   : {stats['best_trade']:.2f}")
    print(f"Худший PnL по сделке   : {stats['worst_trade']:.2f}")
    print(f"Открытых ордеров       : {open_orders_count}")
    print()

    # --- Расширенная статистика ---
    print("=== Расширенная статистика ===\n")
    print(f"Профитных сделок       : {stats['wins']}")
    print(f"Убыточных сделок       : {stats['losses']}")
    print(f"Безубыточных сделок    : {stats['breakeven']}")
    print(f"Winrate                : {stats['winrate_pct']:.2f}%")
    print(f"Средний профит (win)   : {stats['avg_win']:.2f}")
    print(f"Средний убыток (loss)  : {stats['avg_loss']:.2f}")
    print(f"Profit factor          : {stats['profit_factor']:.2f}")
    print(f"Макс. просадка equity  : {stats['max_drawdown']:.2f}")
    print()


def main() -> None:
    db_path: Path = get_db_path()

    if not db_path.exists():
        print(f"Файл БД не найден: {db_path}")
        return

    print(f"Используем БД: {db_path}\n")

    conn = sqlite3.connect(str(db_path))
    try:
        exec_with_orders = fetch_execs_with_orders(conn)
        closed_orders, open_orders_count = build_equity(exec_with_orders)
        print_equity(closed_orders, open_orders_count)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
