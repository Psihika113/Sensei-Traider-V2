# sensei_offline_review.py
"""
Оффлайновый "Sensei-коуч":
делает короткий разбор торгового дня по данным из SQLite-БД SenseiTrader.

Логика:
- Тянем orders + executions из data/trader.db
- Считаем по каждому order:
    * net_qty_order
    * realized_pnl (если ордер полностью закрыт)
    * close_ts (по последнему execution)
- На основе этого строим:
    * статистику по выбранному дню (trades_closed, day_realized_pnl, winrate и т.п.)
    * сводку по истории (total_closed_orders, total_realized_pnl)
    * текущие позиции (по незакрытым ордерам)
- По простым правилам печатаем "оценку дня" + риски.
"""

import os
import sys
import sqlite3
from typing import Dict, List, Any, Tuple


# ----------------------------------------------------------------------
# Вспомогательные функции работы с БД
# ----------------------------------------------------------------------

def get_db_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "data", "trader.db")


def load_orders_and_executions(conn: sqlite3.Connection) -> Tuple[Dict[str, sqlite3.Row], Dict[str, List[sqlite3.Row]]]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM orders")
    orders_rows = cur.fetchall()
    orders: Dict[str, sqlite3.Row] = {row["order_id"]: row for row in orders_rows}

    cur.execute("SELECT * FROM executions")
    exec_rows = cur.fetchall()
    execs_by_order: Dict[str, List[sqlite3.Row]] = {}
    for row in exec_rows:
        order_id = row["order_id"]
        execs_by_order.setdefault(order_id, []).append(row)

    return orders, execs_by_order


# ----------------------------------------------------------------------
# Построение статистики по ордерам
# ----------------------------------------------------------------------

def build_order_stats(
    orders: Dict[str, sqlite3.Row],
    execs_by_order: Dict[str, List[sqlite3.Row]],
) -> List[Dict[str, Any]]:
    """
    Возвращает список словарей, один словарь на order_id:
    {
        'order_id', 'symbol', 'side',
        'exec_count', 'net_qty_order',
        'realized_pnl', 'total_fee',
        'is_closed', 'close_ts',
        'execs': [Row, ...]
    }
    """
    stats: List[Dict[str, Any]] = []

    for order_id, o in orders.items():
        symbol = o["symbol"]
        side = (o["side"] or "").upper()
        execs = execs_by_order.get(order_id, [])

        if not execs:
            # ордер без исполнений — для PnL/позиции не интересен
            continue

        # Считаем нетто-кол-во и PnL.
        # Для BUY:
        #   открывающие (PARENT) увеличивают позицию, закрывающие (TAKE/STOP) уменьшают.
        # Для SELL — наоборот.
        net_qty_order = 0.0
        total_fee = 0.0
        exec_count = 0

        cost = 0.0      # сколько "уплыло" из кармана
        proceeds = 0.0  # сколько "пришло" в карман

        # close_ts берём по последнему execution
        close_ts = None

        for e in execs:
            exec_count += 1
            leg = (e["leg"] or "").upper()
            price = float(e["price"] or 0.0)
            qty = float(e["qty"] or 0.0)
            fee = float(e["fee"] or 0.0)
            ts_utc = e["ts_utc"]

            total_fee += fee

            # считаем, открывающий это лег или закрывающий
            # считаем PARENT как открывающий, TAKE/STOP как закрывающий
            is_open_leg = leg in ("PARENT", "P", "", "OPEN")
            is_close_leg = leg in ("TAKE", "STOP", "CLOSE", "T")

            if not (is_open_leg or is_close_leg):
                # на всякий случай: неизвестные типы ног считаем открывающими
                is_open_leg = True

            if side == "BUY":
                # LONG: open -> +qty, close -> -qty
                if is_open_leg:
                    net_qty_order += qty
                    cost += price * qty
                else:
                    net_qty_order -= qty
                    proceeds += price * qty
            else:
                # SELL (SHORT): open -> -qty, close -> +qty
                if is_open_leg:
                    net_qty_order -= qty
                    proceeds += price * qty  # при открытии шорта деньги приходят
                else:
                    net_qty_order += qty
                    cost += price * qty      # при закрытии шорта деньги уходят

            # обновляем close_ts
            if ts_utc:
                if close_ts is None or ts_utc > close_ts:
                    close_ts = ts_utc

        is_closed = abs(net_qty_order) < 1e-9

        realized_pnl = None
        if is_closed:
            gross_pnl = proceeds - cost
            realized_pnl = gross_pnl - total_fee

        stats.append(
            {
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "exec_count": exec_count,
                "net_qty_order": net_qty_order,
                "total_fee": total_fee,
                "realized_pnl": realized_pnl,
                "is_closed": is_closed,
                "close_ts": close_ts,
                "execs": execs,
            }
        )

    return stats


# ----------------------------------------------------------------------
# Агрегации по датам и позициям
# ----------------------------------------------------------------------

def extract_date_from_ts(ts_utc: str) -> str:
    """
    Берём YYYY-MM-DD из ISO-подобной строки.
    На вход могут приходить '2025-11-03T11:36:16Z'
    или '2025-12-03T13:43:17.600480+00:00'.
    """
    return ts_utc[:10]


def choose_default_date(order_stats: List[Dict[str, Any]]) -> str:
    """
    Если есть закрытые ордера — используем дату последнего закрытия.
    Иначе — сегодняшнюю дату (строкой).
    """
    closed_orders = [o for o in order_stats if o["is_closed"] and o["close_ts"]]
    if closed_orders:
        last_date = max(extract_date_from_ts(o["close_ts"]) for o in closed_orders)
        return last_date

    import datetime as _dt
    return _dt.date.today().isoformat()


def build_day_stats(order_stats: List[Dict[str, Any]], target_date: str) -> Dict[str, Any]:
    day_orders = [
        o for o in order_stats
        if o["is_closed"] and o["close_ts"] and extract_date_from_ts(o["close_ts"]) == target_date
    ]

    trades_closed = len(day_orders)
    day_realized_pnl = sum(o["realized_pnl"] or 0.0 for o in day_orders)

    wins = sum(1 for o in day_orders if (o["realized_pnl"] or 0.0) > 0)
    losses = sum(1 for o in day_orders if (o["realized_pnl"] or 0.0) < 0)
    breakeven = trades_closed - wins - losses

    best_order = None
    worst_order = None

    if day_orders:
        best_order = max(day_orders, key=lambda o: o["realized_pnl"] or 0.0)
        worst_order = min(day_orders, key=lambda o: o["realized_pnl"] or 0.0)

    history_closed = [o for o in order_stats if o["is_closed"] and o["realized_pnl"] is not None]
    total_closed_orders = len(history_closed)
    total_realized_pnl = sum(o["realized_pnl"] or 0.0 for o in history_closed)

    return {
        "target_date": target_date,
        "day_orders": day_orders,
        "trades_closed": trades_closed,
        "day_realized_pnl": day_realized_pnl,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "best_order": best_order,
        "worst_order": worst_order,
        "total_closed_orders": total_closed_orders,
        "total_realized_pnl": total_realized_pnl,
    }


def build_positions(order_stats: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Возвращает словарь по символу:
    {
      symbol: {
        'net_qty': float,
        'exec_count': int,
        'total_fee': float
      }
    }
    """
    positions: Dict[str, Dict[str, Any]] = {}

    for o in order_stats:
        net_qty = o["net_qty_order"]
        if abs(net_qty) < 1e-9:
            continue

        sym = o["symbol"]
        pos = positions.setdefault(
            sym,
            {"net_qty": 0.0, "exec_count": 0, "total_fee": 0.0},
        )
        pos["net_qty"] += net_qty
        pos["exec_count"] += o["exec_count"]
        pos["total_fee"] += o["total_fee"]

    return positions


# ----------------------------------------------------------------------
# Печать оффлайнового "коуч-отчёта"
# ----------------------------------------------------------------------

def print_header(db_path: str, target_date: str):
    print(f"Используем БД: {db_path}")
    print()
    print("=== SENSEI OFFLINE REVIEW ===")
    print(f"Дата для разбора: {target_date}")
    print()


def print_day_summary(day: Dict[str, Any]):
    print("=== Сводка по дню ===")
    print(f"Закрытых сделок за день : {day['trades_closed']}")
    print(f"Realized PnL за день    : {day['day_realized_pnl']:.2f}")
    print(f"Побед / убытков / 0     : {day['wins']} / {day['losses']} / {day['breakeven']}")

    if day["best_order"]:
        bo = day["best_order"]
        print()
        print("Лучшая сделка:")
        print(f"  order_id     : {bo['order_id']}")
        print(f"  symbol       : {bo['symbol']}")
        print(f"  pnl          : {bo['realized_pnl']:.2f}")

    if day["worst_order"]:
        wo = day["worst_order"]
        print()
        print("Худшая сделка:")
        print(f"  order_id     : {wo['order_id']}")
        print(f"  symbol       : {wo['symbol']}")
        print(f"  pnl          : {wo['realized_pnl']:.2f}")

    print()


def print_history_summary(day: Dict[str, Any]):
    print("=== Исторический контекст ===")
    print(f"Всего закрытых сделок в истории : {day['total_closed_orders']}")
    print(f"Суммарный realized PnL          : {day['total_realized_pnl']:.2f}")
    print()


def print_positions_summary(positions: Dict[str, Dict[str, Any]]):
    print("=== Текущие позиции ===")
    if not positions:
        print("Открытых позиций нет.")
        print()
        return

    for sym, p in positions.items():
        direction = "LONG" if p["net_qty"] > 0 else "SHORT"
        print(f"Символ: {sym}")
        print(f"  Направление : {direction}")
        print(f"  net_qty     : {p['net_qty']:.2f}")
        print(f"  exec_count  : {p['exec_count']}")
        print(f"  total_fee   : {p['total_fee']:.2f}")
        print()

    print()


def print_offline_coach(day: Dict[str, Any], positions: Dict[str, Dict[str, Any]]):
    """
    Простая "оценка дня" по правилам:
    - Если сделок нет — фокус на управлении открытыми позициями.
    - Если сделки есть — краткая оценка качества + рисков.
    """
    print("=== Оценка Sensei (оффлайн) ===")

    trades_closed = day["trades_closed"]
    day_pnl = day["day_realized_pnl"]
    wins = day["wins"]
    losses = day["losses"]
    positions_open = bool(positions)

    if trades_closed == 0:
        print("Сегодня закрытых сделок не было.")
        if positions_open:
            print("Однако у тебя есть открытые позиции — главный акцент на управлении риском:")
            print("- Проверь, есть ли по каждой позиции актуальный стоп и план выхода.")
            print("- Оцени, не держишь ли позицию дольше, чем позволяет твой торговый протокол.")
            print("- Проследи, чтобы суммарный риск по всем открытым позициям не превышал твой лимит.")
        else:
            print("День без сделок и без открытых позиций — это нейтральный день.")
            print("- Важно не пытаться «насильно» искать входы там, где сетапов нет.")
            print("- Используй такой день для обзора статистики и корректировки стратегий.")
        print()
        return

    # Если сделки были:
    winrate = wins / trades_closed if trades_closed > 0 else 0.0

    if day_pnl > 0 and losses == 0:
        print("День прибыльный, без убыточных сделок.")
        print("- Не воспринимай это как норму: одна-две такие сессии легко создают иллюзию вседозволенности.")
        print("- Зафиксируй, какие условия рынка и какие сетапы привели к такому результату.")
    elif day_pnl > 0 and losses > 0:
        print("День завершился в плюс, но с убыточными сделками.")
        print("- Это хороший знак: есть прибыль, но важно отследить, не берёшь ли лишние риски.")
        print("- Посмотри на убыточные сделки: были ли они по плану или импульсивные.")
    elif day_pnl < 0:
        print("День убыточный.")
        print("- Главное — понять, это результат выполнения стратегии или нарушение дисциплины.")
        print("- Проследи, не увеличивал ли ты риск после первых убытков.")
    else:
        print("День около нуля по результату.")
        print("- Важнее не сам нулевой результат, а качество принятых решений.")
        print("- Если сделки были по плану — это нормальный рабочий день.")
    print()

    print(f"Winrate за день: {winrate * 100:.2f}%")
    if positions_open:
        print("У тебя остаются открытые позиции — учти их при оценке риска:")
        print("- Не забывай, что дневной PnL по закрытым сделкам не отражает будущий риск по открытым.")
        print("- Проверь стопы, объёмы и корреляцию между бумагами.")
    else:
        print("Открытых позиций на конец дня нет — риск по рынку на ночь не переносишь.")
    print()

    print("Рекомендуемый фокус на следующий день:")
    print("- Продолжай фиксировать сделки и статистику в той же структуре (PnL, winrate, серии).")
    print("- Добавь контроль по риску: риск на сделку и риск на день в процентах от капитала.")
    print("- Начни помечать для себя, где сделки были строго по плану, а где — импульсивные.")
    print()


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def main():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)

    try:
        orders, execs_by_order = load_orders_and_executions(conn)
        order_stats = build_order_stats(orders, execs_by_order)

        # Определяем дату: либо из аргумента, либо последнюю дату закрытия
        if len(sys.argv) > 1:
            target_date = sys.argv[1]
        else:
            target_date = choose_default_date(order_stats)

        print_header(db_path, target_date)

        day_stats = build_day_stats(order_stats, target_date)
        positions = build_positions(order_stats)

        print_day_summary(day_stats)
        print_history_summary(day_stats)
        print_positions_summary(positions)
        print_offline_coach(day_stats, positions)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
