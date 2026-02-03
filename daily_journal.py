# -*- coding: utf-8 -*-
"""
daily_journal.py — человеко-читаемый дневной журнал сделок SenseiTrader.

Использует ту же БД и те же вспомогательные функции, что и show_pnl / show_equity.

Функции:
    python daily_journal.py
        → отчёт по последнему дню, в который были закрытые сделки

    python daily_journal.py 2025-11-03
        → отчёт по конкретной дате (формат YYYY-MM-DD)
"""

from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, List, Tuple, Optional

from show_pnl import (
    get_db_path,
    fetch_execs_with_orders,
    signed_qty,
)
from show_equity import build_equity


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ПАРСЕРЫ ДАТ / ВРЕМЕНИ
# ---------------------------------------------------------------------------

def parse_ts(ts: Optional[str]) -> Optional[datetime]:
    """
    Пытаемся распарсить строки вида:
        '2025-11-03T11:36:16Z'
        '2025-12-03T13:43:17.600480+00:00'
    Возвращаем datetime или None, если не получилось.
    """
    if not ts:
        return None

    # Попробуем сначала с явным Z (UTC) и с таймзоной
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt)
        except Exception:
            continue

    # Фоллбек: отрежем микросекунды/зону, возьмём только до секунд
    try:
        base = ts[:19]  # 'YYYY-MM-DDTHH:MM:SS'
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def ts_to_date_str(ts: Optional[str]) -> Optional[str]:
    """
    Берёт строку времени и возвращает дату в виде 'YYYY-MM-DD'
    или None, если не удалось распарсить.
    """
    dt = parse_ts(ts)
    if not dt:
        return None
    return dt.date().isoformat()


# ---------------------------------------------------------------------------
# ПОЗИЦИИ (похожая логика, как в show_positions / sensei_status)
# ---------------------------------------------------------------------------

def build_positions(exec_with_orders: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Строим текущие позиции по символам на основе всех executions.

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

    # Оставляем только ненулевые позиции
    positions = {
        sym: info
        for sym, info in positions.items()
        if abs(info["net_qty"]) > 1e-8
    }

    return positions


# ---------------------------------------------------------------------------
# ГРУППИРОВКА ЗАКРЫТЫХ ОРДЕРОВ ПО ДАТАМ
# ---------------------------------------------------------------------------

def group_closed_by_date(closed_orders: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Группирует закрытые ордера по дате закрытия (close_ts → YYYY-MM-DD).
    """
    by_date: Dict[str, List[Dict[str, Any]]] = {}

    for o in closed_orders:
        d_str = ts_to_date_str(o.get("close_ts"))
        if not d_str:
            # если по какой-то причине нет даты закрытия — игнорируем
            continue
        by_date.setdefault(d_str, []).append(o)

    return by_date


def choose_target_date(
    grouped: Dict[str, List[Dict[str, Any]]],
    argv: List[str],
) -> Optional[str]:
    """
    Логика выбора даты:
        - если есть аргумент argv[1] → используем его как YYYY-MM-DD
        - иначе → берём максимальную доступную дату (последний торговый день)
    """
    if not grouped:
        return None

    # Если пользователь указал дату вручную
    if len(argv) > 1:
        requested = argv[1]
        # допускаем точное совпадение
        if requested in grouped:
            return requested
        # если такой даты нет в grouped — всё равно вернём её,
        # а дальше просто выдадим сообщение "сделок нет"
        return requested

    # По умолчанию — последняя дата, по которой есть закрытые сделки
    all_dates: List[date] = []
    for d_str in grouped.keys():
        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            all_dates.append(d_obj)
        except Exception:
            continue

    if not all_dates:
        return None

    last_date = max(all_dates)
    return last_date.isoformat()


# ---------------------------------------------------------------------------
# ПЕЧАТЬ ЖУРНАЛА
# ---------------------------------------------------------------------------

def print_journal_for_day(
    day: str,
    orders_for_day: List[Dict[str, Any]],
    positions: Dict[str, Dict[str, float]],
    all_closed_orders: List[Dict[str, Any]],
) -> None:
    """
    Печатает человеко-читаемый отчёт по одному дню.
    """
    print(f"Используем дату: {day}\n")

    if not orders_for_day:
        print("=== Трейд-журнал Sensei ===")
        print(f"В день {day} закрытых сделок не было.\n")
    else:
        # Считаем дневные агрегаты
        day_realized = sum(float(o.get("realized_pnl", 0.0) or 0.0) for o in orders_for_day)
        best = max(orders_for_day, key=lambda o: float(o.get("realized_pnl", 0.0) or 0.0))
        worst = min(orders_for_day, key=lambda o: float(o.get("realized_pnl", 0.0) or 0.0))

        print("=== Трейд-журнал Sensei ===")
        print(f"Торговый день: {day}")
        print(f"Количество закрытых сделок: {len(orders_for_day)}")
        print(f"Итоговый реализованный PnL за день: {day_realized:.2f}\n")

        print("Краткая сводка по дню:")
        print(f"- Лучшая сделка: {best.get('order_id')} ({float(best.get('realized_pnl', 0.0) or 0.0):.2f})")
        print(f"- Худшая сделка: {worst.get('order_id')} ({float(worst.get('realized_pnl', 0.0) or 0.0):.2f})")
        print()

        print("Детальный разбор сделок дня:\n")
        for idx, o in enumerate(orders_for_day, start=1):
            order_id = o.get("order_id")
            symbol = o.get("symbol")
            side = o.get("side")
            realized = float(o.get("realized_pnl", 0.0) or 0.0)
            execs = o.get("execs")
            close_ts = o.get("close_ts")

            print(f"--- Сделка #{idx} ---")
            print(f"order_id     : {order_id}")
            print(f"symbol       : {symbol}")
            print(f"side         : {side}")
            print(f"close_ts     : {close_ts}")
            print(f"execs count  : {execs}")
            print(f"realized PnL : {realized:.2f}")

            # Простая словесная интерпретация результата
            if realized > 0:
                result_word = "прибыльная"
            elif realized < 0:
                result_word = "убыточная"
            else:
                result_word = "безубыточная"

            print(f"Комментарий  : Сделка {result_word}, итог по ней {realized:.2f}.\n")

        # Общий исторический контекст (по всем закрытым ордерам)
        total_realized = sum(float(o.get("realized_pnl", 0.0) or 0.0) for o in all_closed_orders)
        print("Исторический контекст:")
        print(f"- Всего закрытых сделок в истории: {len(all_closed_orders)}")
        print(f"- Суммарный реализованный PnL     : {total_realized:.2f}\n")

    # Текущие открытые позиции на момент отчёта
    print("Текущие позиции на момент отчёта:\n")
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

    print("=== Конец дневного журнала ===\n")


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

        # Получаем закрытые ордера и число открытых (эта логика уже проверена в show_equity)
        closed_orders, open_orders_count = build_equity(exec_with_orders)

        grouped = group_closed_by_date(closed_orders)
        target_day = choose_target_date(grouped, argv)

        if target_day is None:
            # Вообще нет закрытых ордеров
            print("Закрытых сделок в истории пока нет. Журнал сформировать нечего.\n")
            positions = build_positions(exec_with_orders)
            if positions:
                print("Однако есть открытые позиции:\n")
                for symbol, info in positions.items():
                    net_qty = info["net_qty"]
                    direction = "LONG" if net_qty > 0 else "SHORT"
                    print(f"Символ: {symbol}")
                    print(f"  Направление : {direction}")
                    print(f"  net_qty     : {net_qty}")
                    print(f"  exec_count  : {info['exec_count']}")
                    print(f"  total_fee   : {info['total_fee']}\n")
            return

        orders_for_day = grouped.get(target_day, [])

        positions = build_positions(exec_with_orders)

        print_journal_for_day(
            day=target_day,
            orders_for_day=orders_for_day,
            positions=positions,
            all_closed_orders=closed_orders,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv)
