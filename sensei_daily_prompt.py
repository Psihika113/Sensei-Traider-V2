# -*- coding: utf-8 -*-
"""
sensei_daily_prompt.py — генератор промпта для LLM по торговому дню.

Назначение:
    - прочитать БД trader.db;
    - выбрать торговый день (по умолчанию — последний день с закрытыми сделками);
    - собрать статистику по дню + исторический контекст + текущие позиции;
    - вывести в консоль готовый промпт, который можно скопировать в LLM.

Использование:
    python sensei_daily_prompt.py
        → промпт по последнему дню с закрытыми сделками.

    python sensei_daily_prompt.py 2025-11-03
        → промпт по указанной дате (формат YYYY-MM-DD).
"""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

from show_pnl import (
    get_db_path,
    fetch_execs_with_orders,
)
from show_equity import build_equity
from daily_journal import (
    build_positions,
    group_closed_by_date,
    choose_target_date,
)


def compute_day_stats(orders_for_day: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Считает агрегаты по одному дню на основе списка закрытых ордеров за этот день.
    """
    if not orders_for_day:
        return {
            "trades_count": 0,
            "day_realized_pnl": 0.0,
            "best_order": None,
            "worst_order": None,
        }

    day_realized = sum(float(o.get("realized_pnl", 0.0) or 0.0) for o in orders_for_day)
    best = max(orders_for_day, key=lambda o: float(o.get("realized_pnl", 0.0) or 0.0))
    worst = min(orders_for_day, key=lambda o: float(o.get("realized_pnl", 0.0) or 0.0))

    return {
        "trades_count": len(orders_for_day),
        "day_realized_pnl": day_realized,
        "best_order": best,
        "worst_order": worst,
    }


def format_trade_line(o: Dict[str, Any]) -> str:
    """
    Формирует одну строку описания сделки для блока [TRADES].
    """
    order_id = o.get("order_id")
    symbol = o.get("symbol")
    side = o.get("side")
    realized = float(o.get("realized_pnl", 0.0) or 0.0)
    close_ts = o.get("close_ts")
    execs = o.get("execs")

    return (
        f"- order_id: {order_id}\n"
        f"  symbol: {symbol}\n"
        f"  side: {side}\n"
        f"  close_ts: {close_ts}\n"
        f"  execs: {execs}\n"
        f"  realized_pnl: {realized:.2f}\n"
    )


def format_positions_block(positions: Dict[str, Dict[str, float]]) -> str:
    """
    Формирует текстовый блок [POSITIONS] по текущим позициям.
    """
    if not positions:
        return "Нет открытых позиций.\n"

    lines: List[str] = []
    for symbol, info in positions.items():
        net_qty = info["net_qty"]
        direction = "LONG" if net_qty > 0 else "SHORT"
        lines.append(
            f"- symbol: {symbol}\n"
            f"  direction: {direction}\n"
            f"  net_qty: {net_qty}\n"
            f"  exec_count: {info['exec_count']}\n"
            f"  total_fee: {info['total_fee']}\n"
        )
    return "".join(lines)


def build_llm_prompt(
    day: str,
    orders_for_day: List[Dict[str, Any]],
    positions: Dict[str, Dict[str, float]],
    all_closed_orders: List[Dict[str, Any]],
) -> str:
    """
    Собирает финальный текст промпта для LLM.
    """
    stats = compute_day_stats(orders_for_day)

    trades_count = stats["trades_count"]
    day_realized = stats["day_realized_pnl"]
    best_order = stats["best_order"]
    worst_order = stats["worst_order"]

    total_realized = sum(float(o.get("realized_pnl", 0.0) or 0.0) for o in all_closed_orders)
    total_trades = len(all_closed_orders)

    # --- Заголовок и роль ---
    parts: List[str] = []
    parts.append("===== SENSEI_PROMPT_BEGIN =====\n")
    parts.append(
        "Ты — мой трейдинговый наставник (SenseiTrader Coach).\n"
        "Проанализируй торговый день на основе данных ниже.\n"
        "Сделай упор на риск-менеджмент, качество входов/выходов и общую дисциплину.\n"
        "Говори кратко, по пунктам, без воды.\n\n"
    )

    # --- Секция DAY_STATS ---
    parts.append("=== [DAY_STATS] ===\n")
    parts.append(f"date: {day}\n")
    parts.append(f"trades_closed: {trades_count}\n")
    parts.append(f"day_realized_pnl: {day_realized:.2f}\n")

    if best_order is not None:
        parts.append(
            "best_order:\n"
            f"  order_id: {best_order.get('order_id')}\n"
            f"  realized_pnl: {float(best_order.get('realized_pnl', 0.0) or 0.0):.2f}\n"
            f"  symbol: {best_order.get('symbol')}\n"
            f"  side: {best_order.get('side')}\n"
        )
    else:
        parts.append("best_order: null\n")

    if worst_order is not None:
        parts.append(
            "worst_order:\n"
            f"  order_id: {worst_order.get('order_id')}\n"
            f"  realized_pnl: {float(worst_order.get('realized_pnl', 0.0) or 0.0):.2f}\n"
            f"  symbol: {worst_order.get('symbol')}\n"
            f"  side: {worst_order.get('side')}\n"
        )
    else:
        parts.append("worst_order: null\n")

    parts.append("\n")

    # --- Секция TRADES ---
    parts.append("=== [TRADES] ===\n")
    if not orders_for_day:
        parts.append("# В этот день закрытых сделок не было.\n\n")
    else:
        for o in orders_for_day:
            parts.append(format_trade_line(o))
            parts.append("\n")

    # --- Секция HISTORY_SUMMARY ---
    parts.append("=== [HISTORY_SUMMARY] ===\n")
    parts.append(f"total_closed_orders: {total_trades}\n")
    parts.append(f"total_realized_pnl: {total_realized:.2f}\n\n")

    # --- Секция POSITIONS ---
    parts.append("=== [POSITIONS] ===\n")
    parts.append(format_positions_block(positions))
    parts.append("\n")

    # --- Секция QUESTIONS_FOR_SENSEI ---
    parts.append("=== [QUESTIONS_FOR_SENSEI] ===\n")
    parts.append(
        "- Какие сильные стороны ты видишь в моих сделках за этот день?\n"
        "- Какие ключевые ошибки или риски ты замечаешь (даже если PnL положительный)?\n"
        "- Что бы ты порекомендовал изменить в правилах входа/выхода или риск-менеджмента?\n"
        "- Какие конкретные метрики мне стоит отслеживать ежедневно, исходя из этих данных?\n"
    )

    parts.append("\n===== SENSEI_PROMPT_END =====\n")

    return "".join(parts)


def main(argv: List[str]) -> None:
    db_path: Path = get_db_path()

    if not db_path.exists():
        print(f"Файл БД не найден: {db_path}")
        return

    print(f"Используем БД: {db_path}\n")

    conn = sqlite3.connect(str(db_path))
    try:
        exec_with_orders = fetch_execs_with_orders(conn)

        # строим закрытые ордера и считаем открытую позицию (как в show_equity / daily_journal)
        closed_orders, open_orders_count = build_equity(exec_with_orders)

        grouped = group_closed_by_date(closed_orders)
        target_day = choose_target_date(grouped, argv)

        if target_day is None:
            print("Закрытых сделок в истории пока нет — промпт формировать не из чего.\n")
            return

        orders_for_day = grouped.get(target_day, [])
        positions = build_positions(exec_with_orders)

        print(f"Используем дату: {target_day}\n")

        prompt = build_llm_prompt(
            day=target_day,
            orders_for_day=orders_for_day,
            positions=positions,
            all_closed_orders=closed_orders,
        )

        print(prompt)

    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv)
