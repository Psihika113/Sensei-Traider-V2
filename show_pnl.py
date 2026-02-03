# -*- coding: utf-8 -*-
"""
show_pnl.py — отчёт PnL по ордерам из SQLite.

Важное:
- расчёт строится ТОЛЬКО на таблице executions (leg=PARENT/TAKE/STOP)
- PARENT считается "entry", TAKE/STOP — "exit"
- для BUY:
    entry_qty = +, entry_cash = -price*qty
    exit_qty  = -, exit_cash  = +price*qty
  для SELL (шорт):
    entry_qty = -, entry_cash = +price*qty
    exit_qty  = +, exit_cash  = -price*qty

ENV:
- SENSEI_DB_PATH: путь к БД (default data/trader.db)

Запуск:
  set SENSEI_DB_PATH=data\\trader_paper.db
  python show_pnl.py
"""

from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# =========================
# Public helpers (used by sensei_status.py / show_equity.py)
# =========================

def get_db_path(default_rel: str = r"data\trader.db") -> Path:
    """
    Priority:
      1) CLI: --db <path> or --db=<path>
      2) ENV: SENSEI_DB_PATH
      3) DEFAULT: project-relative default_rel
    Returns: pathlib.Path (absolute).
    """
    argv = sys.argv[1:]

    # 1) CLI
    chosen: Optional[str] = None
    for i, a in enumerate(argv):
        if a == "--db" and i + 1 < len(argv):
            chosen = argv[i + 1]
            break
        if a.startswith("--db="):
            chosen = a.split("=", 1)[1]
            break

    # 2) ENV
    if not chosen:
        env = os.environ.get("SENSEI_DB_PATH", "").strip()
        if env:
            chosen = env

    # 3) DEFAULT
    if not chosen:
        chosen = default_rel

    p = Path(chosen).expanduser()
    if not p.is_absolute():
        p = (Path(__file__).parent / p).resolve()
    return p


def signed_qty(side: str, qty: float) -> float:
    """
    For BUY: +qty
    For SELL: -qty
    """
    s = (side or "").upper()
    if s == "BUY":
        return float(qty)
    return -float(qty)


def fetch_execs_with_orders(con: sqlite3.Connection) -> List[sqlite3.Row]:
    """
    Returns joined executions with their order fields used by status/equity/pnl.
    Columns: order_id, symbol, side, leg, ts_utc, price, qty, fee
    """
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT
            o.order_id AS order_id,
            o.symbol   AS symbol,
            o.side     AS side,
            e.leg      AS leg,
            e.ts_utc   AS ts_utc,
            e.price    AS price,
            e.qty      AS qty,
            e.fee      AS fee
        FROM executions e
        JOIN orders o ON o.order_id = e.order_id
        ORDER BY e.ts_utc ASC, e.id ASC
        """
    ).fetchall()
    return rows


# =========================
# Local helpers
# =========================

def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    cols = []
    for r in con.execute(f"PRAGMA table_info({table})").fetchall():
        cols.append(r[1])
    return cols


def pick_qty_col(order_cols: List[str]) -> Optional[str]:
    for c in ("qty_planned", "qty", "quantity", "total_qty", "size"):
        if c in order_cols:
            return c
    return None


def money(x: float) -> float:
    return float(x)


def main() -> int:
    # используем общий резолвер (чтобы поведение совпадало с другими скриптами)
    db_path = get_db_path(r"data\trader.db")
    db_abs = Path(db_path)
    if not db_abs.is_absolute():
        db_abs = (Path(__file__).parent / db_abs).resolve()

    print(f"Используем БД: {db_abs}\n")

    con = open_db(str(db_abs))

    try:
        orders_cols = table_columns(con, "orders")
        exec_cols = table_columns(con, "executions")

        # минимально нужные колонки orders
        need_orders = ["order_id", "symbol", "side"]
        for c in need_orders:
            if c not in orders_cols:
                raise RuntimeError(f"В таблице orders нет колонки '{c}'. Есть: {orders_cols}")

        qty_col = pick_qty_col(orders_cols)

        # читаем ордера
        select_orders = ["order_id", "symbol", "side"]
        if qty_col:
            select_orders.append(qty_col)

        orders = con.execute(
            "SELECT " + ",".join(select_orders) + " FROM orders ORDER BY rowid ASC"
        ).fetchall()

        # проверка executions
        for c in ("order_id", "leg", "ts_utc", "price", "qty", "fee"):
            if c not in exec_cols:
                raise RuntimeError(f"В таблице executions нет колонки '{c}'. Есть: {exec_cols}")

        # читаем executions (как и раньше, без join)
        execs = con.execute(
            """
            SELECT order_id, leg, ts_utc, price, qty, fee
            FROM executions
            ORDER BY ts_utc ASC, id ASC
            """
        ).fetchall()

        # группируем executions по order_id
        ex_by_order: Dict[str, List[sqlite3.Row]] = {}
        for e in execs:
            oid = str(e["order_id"])
            ex_by_order.setdefault(oid, []).append(e)

        print("=== PnL по ордерам ===\n")

        # summary (только закрытые)
        closed_by_symbol: Dict[str, Tuple[int, float]] = {}

        for o in orders:
            order_id = str(o["order_id"])
            symbol = str(o["symbol"])
            side = str(o["side"]).upper()

            planned_qty = float(o[qty_col]) if qty_col and o[qty_col] is not None else 0.0

            ex_list = ex_by_order.get(order_id, [])
            exec_count = len(ex_list)

            # агрегации
            net_qty = 0.0
            cash = 0.0
            total_fee = 0.0

            for e in ex_list:
                leg = str(e["leg"]).upper()
                price = float(e["price"] or 0.0)
                qty = float(e["qty"] or 0.0)
                fee = float(e["fee"] or 0.0)

                total_fee += fee

                is_entry = (leg == "PARENT")
                is_exit = (leg in ("TAKE", "STOP"))

                if not (is_entry or is_exit):
                    continue

                if side == "BUY":
                    if is_entry:
                        net_qty += qty
                        cash += -(price * qty)
                    else:  # exit
                        net_qty -= qty
                        cash += +(price * qty)
                else:  # SELL (шорт)
                    if is_entry:
                        net_qty -= qty
                        cash += +(price * qty)
                    else:  # exit
                        net_qty += qty
                        cash += -(price * qty)

            # вывод
            print(f"order_id       : {order_id}")
            print(f"  symbol       : {symbol}")
            print(f"  side         : {side}")
            print(f"  qty_planned  : {planned_qty}")
            print(f"  exec_count   : {exec_count}")
            print(f"  net_qty_order: {money(net_qty)}")
            print(f"  cash         : {money(cash)}")
            print(f"  total_fee    : {money(total_fee)}")

            if abs(net_qty) > 1e-9:
                print("  realized_pnl : (open)\n")
            else:
                realized = cash - total_fee
                print(f"  realized_pnl : {money(realized)}\n")

                cnt, pnl = closed_by_symbol.get(symbol, (0, 0.0))
                closed_by_symbol[symbol] = (cnt + 1, pnl + realized)

        print("=== Summary by symbol (closed only) ===\n")
        if not closed_by_symbol:
            print("(no closed orders)\n")
        else:
            for sym in sorted(closed_by_symbol.keys()):
                cnt, pnl = closed_by_symbol[sym]
                print(f"{sym}: closed_orders={cnt}, closed_pnl={money(pnl)}")

        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
