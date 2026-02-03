#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SenseiTrader: create_order_stub.py

Назначение:
- Создать "заглушку" ордера в таблице orders (SQLite), если в БД есть исполнения (fills),
  но нет соответствующей строки orders (или нужно вручную привязать orderRef).

Почему нужно:
- show_pnl.py и show_positions.py считают PnL/позиции через связку orders + executions.
- sync_ibkr_fills.py матчит fills по orderRef/ib_parent/ib_take/ib_stop и order_id.
"""

import argparse
import datetime as dt
import os
import secrets
import sqlite3
from typing import Dict, List, Tuple


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _get_db_path(cli_db: str | None) -> str:
    if cli_db:
        return cli_db
    env = os.getenv("SENSEI_DB_PATH", "").strip()
    if env:
        return env
    # дефолт как в проекте
    return r"data\trader.db"


def _table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]  # name


def _order_exists(con: sqlite3.Connection, order_id: str) -> bool:
    row = con.execute("SELECT 1 FROM orders WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
    return row is not None


def _build_insert(table_cols: List[str], data: Dict[str, object]) -> Tuple[str, List[object]]:
    cols = [c for c in table_cols if c in data]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO orders ({','.join(cols)}) VALUES ({placeholders})"
    vals = [data[c] for c in cols]
    return sql, vals


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=None, help="Путь к SQLite DB (или SENSEI_DB_PATH)")
    p.add_argument("--order-id", default=None, help="order_id (если не задан — сгенерируем)")
    p.add_argument("--order-ref", default=None, help="order_ref (если не задан — равен order_id)")
    p.add_argument("--symbol", required=True, help="Тикер, например AAPL")
    p.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"], help="BUY/SELL")
    p.add_argument("--qty", required=True, type=float, help="Планируемое количество (qty)")
    p.add_argument("--status", default="NEW", help="Статус (NEW/FILLED/CANCELLED/...)")
    p.add_argument("--reason", default="STUB", help="Причина (для аудита)")
    p.add_argument("--ib-parent", default=None, help="IB parent orderId (int)")
    p.add_argument("--ib-take", default=None, help="IB take orderId (int)")
    p.add_argument("--ib-stop", default=None, help="IB stop orderId (int)")
    args = p.parse_args()

    db_path = _get_db_path(args.db)
    order_id = (args.order_id or f"sensei-stub-{secrets.token_hex(4)}").strip()
    order_ref = (args.order_ref or order_id).strip()
    symbol = args.symbol.strip().upper()
    side = args.side.strip().upper()
    qty = float(args.qty)

    now_iso = _utc_now_iso()

    # connect
    con = sqlite3.connect(db_path)
    try:
        cols = _table_columns(con, "orders")
        if not cols:
            print(f"[create_order_stub] ERROR: cannot read orders schema from DB={db_path}")
            return 2

        if _order_exists(con, order_id):
            print(f"[create_order_stub] exists: order_id={order_id} (no изменений)")
            return 0

        # Готовим данные, но вставляем только то, что реально есть в схеме
        data: Dict[str, object] = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "status": str(args.status).strip(),
            "reason": str(args.reason).strip(),
            "ib_parent": int(args.ib_parent) if args.ib_parent is not None else None,
            "ib_take": int(args.ib_take) if args.ib_take is not None else None,
            "ib_stop": int(args.ib_stop) if args.ib_stop is not None else None,
            "created_ts": now_iso,  # иногда в старых схемах
            "order_ref": order_ref,  # если колонка есть
            "created_ts_utc": now_iso,  # если колонка есть
            "last_update_ts_utc": now_iso,  # если колонка есть
        }

        # Убираем None, чтобы не конфликтовать с NOT NULL в некоторых схемах
        # (если колонка nullable — можно было бы оставить, но безопаснее так)
        data = {k: v for k, v in data.items() if v is not None}

        sql, vals = _build_insert(cols, data)

        con.execute(sql, vals)
        con.commit()

        print(f"[create_order_stub] OK: inserted order_id={order_id} symbol={symbol} side={side} qty={qty} order_ref={order_ref}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
