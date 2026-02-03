# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple

from app.db import Database
from adapters.ibkr.client import IBKRClient


def _ensure_table_ib_exec_seen(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ib_exec_seen (
            exec_id     TEXT PRIMARY KEY,
            order_id    TEXT NOT NULL,
            ib_order_id INTEGER,
            leg         TEXT NOT NULL,
            ts_utc      TEXT NOT NULL,
            price       REAL NOT NULL,
            qty         REAL NOT NULL,
            fee         REAL NOT NULL DEFAULT 0.0,
            created_at_utc TEXT NOT NULL
        );
        """
    )


def _execution_columns(conn: sqlite3.Connection) -> set[str]:
    cols: set[str] = set()
    cur = conn.execute("PRAGMA table_info(executions)")
    for row in cur.fetchall():
        cols.add(row[1])
    return cols


def _orders_ib_map(conn: sqlite3.Connection) -> dict[int, Tuple[str, str, float]]:
    """
    broker orderId -> (our_order_id, leg, planned_qty)
    leg: parent/take/stop
    """
    m: dict[int, Tuple[str, str, float]] = {}
    cur = conn.execute(
        """
        SELECT order_id, qty, ib_parent, ib_take, ib_stop
        FROM orders
        WHERE ib_parent IS NOT NULL OR ib_take IS NOT NULL OR ib_stop IS NOT NULL
        """
    )
    for order_id, qty, ib_parent, ib_take, ib_stop in cur.fetchall():
        planned_qty = float(qty or 0.0)
        if ib_parent:
            try:
                m[int(ib_parent)] = (order_id, "parent", planned_qty)
            except Exception:
                pass
        if ib_take:
            try:
                m[int(ib_take)] = (order_id, "take", planned_qty)
            except Exception:
                pass
        if ib_stop:
            try:
                m[int(ib_stop)] = (order_id, "stop", planned_qty)
            except Exception:
                pass
    return m


def _to_utc_iso(x) -> str:
    if isinstance(x, str):
        try:
            parsed = datetime.fromisoformat(x.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except Exception:
            return x

    if isinstance(x, datetime):
        if x.tzinfo is None:
            x = x.replace(tzinfo=timezone.utc)
        return x.astimezone(timezone.utc).isoformat()

    return datetime.now(timezone.utc).isoformat()


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _fetch_fills(ib, lookback_minutes: int) -> list:
    since_dt = datetime.now(timezone.utc) - timedelta(minutes=int(lookback_minutes))
    try:
        from ib_insync import ExecutionFilter  # type: ignore

        f = ExecutionFilter()
        f.time = since_dt.strftime("%Y%m%d %H:%M:%S")
        fills = ib.reqExecutions(f)
        return list(fills or [])
    except Exception:
        return list(getattr(ib, "fills", lambda: [])() or [])


def _recompute_order_status(conn: sqlite3.Connection, order_id: str) -> str:
    row = conn.execute("SELECT qty, status FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        return "UNKNOWN"

    planned_qty = float(row[0] or 0.0)
    prev_status = str(row[1] or "NEW")

    ent = conn.execute(
        "SELECT COALESCE(SUM(qty), 0.0) FROM executions WHERE order_id=? AND LOWER(leg)='parent'",
        (order_id,),
    ).fetchone()[0]
    ex = conn.execute(
        "SELECT COALESCE(SUM(qty), 0.0) FROM executions WHERE order_id=? AND LOWER(leg) IN ('take','stop')",
        (order_id,),
    ).fetchone()[0]

    entry_qty = float(ent or 0.0)
    exit_qty = float(ex or 0.0)

    if entry_qty <= 0.0:
        return prev_status

    if exit_qty >= entry_qty - 1e-9 and entry_qty > 0:
        return "CLOSED"

    if planned_qty > 0 and entry_qty < planned_qty - 1e-9:
        return "PARTIAL_ENTRY"

    return "OPEN"


def sync_ibkr_fills_once(
    *,
    db: Database,
    ib_client: IBKRClient,
    log: logging.Logger,
    lookback_minutes: int | None = None,
) -> Dict[str, Any]:
    """
    Читает fills из IBKR и пишет новые записи в:
      - ib_exec_seen (дедуп по exec_id)
      - executions
    Обновляет orders.status (NEW/SUBMITTED -> OPEN/PARTIAL_ENTRY/CLOSED)
    """
    if lookback_minutes is None:
        lookback_minutes = int(os.getenv("SENSEI_IB_SYNC_LOOKBACK_MINUTES", "240"))

    conn = db.conn
    cols = _execution_columns(conn)

    # Мапа broker orderId -> (our_order_id, leg, planned_qty)
    ib_map = _orders_ib_map(conn)
    if not ib_map:
        return {"fills_total": 0, "inserted": 0, "skipped": 0, "orders_updated": 0, "note": "no_ib_orders_in_db"}

    ib_client.ensure_connected()
    fills = _fetch_fills(ib_client.ib, int(lookback_minutes))
    if not fills:
        return {"fills_total": 0, "inserted": 0, "skipped": 0, "orders_updated": 0}

    inserted = 0
    skipped = 0
    updated_orders: set[str] = set()

    now_iso = datetime.now(timezone.utc).isoformat()

    with db.transaction() as cur:
        _ensure_table_ib_exec_seen(cur)

        for f in fills:
            # ib_insync Fill/Execution
            exec_obj = getattr(f, "execution", None)
            if exec_obj is None:
                skipped += 1
                continue

            exec_id = getattr(exec_obj, "execId", None) or getattr(exec_obj, "execID", None)
            if not exec_id:
                skipped += 1
                continue

            ib_order_id = getattr(exec_obj, "orderId", None)
            try:
                ib_order_id_int = int(ib_order_id)
            except Exception:
                ib_order_id_int = None

            if ib_order_id_int is None or ib_order_id_int not in ib_map:
                skipped += 1
                continue

            our_order_id, leg, _planned_qty = ib_map[ib_order_id_int]

            ts_utc = _to_utc_iso(getattr(exec_obj, "time", None) or getattr(f, "time", None))

            price = _safe_float(getattr(exec_obj, "price", 0.0), 0.0)
            qty = _safe_float(getattr(exec_obj, "shares", None) or getattr(exec_obj, "qty", None) or 0.0, 0.0)

            fee = 0.0
            cr = getattr(f, "commissionReport", None)
            if cr is not None:
                fee = _safe_float(getattr(cr, "commission", 0.0), 0.0)

            # 1) seen (дедуп)
            try:
                cur.execute(
                    """
                    INSERT INTO ib_exec_seen(exec_id, order_id, ib_order_id, leg, ts_utc, price, qty, fee, created_at_utc)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (str(exec_id), our_order_id, ib_order_id_int, leg, ts_utc, float(price), float(qty), float(fee), now_iso),
                )
            except Exception:
                # уже видели
                skipped += 1
                continue

            # 2) executions
            if "exec_id" in cols:
                cur.execute(
                    """
                    INSERT INTO executions(exec_id, order_id, leg, ts_utc, price, qty, fee)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (str(exec_id), our_order_id, leg.upper(), ts_utc, float(price), float(qty), float(fee)),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO executions(order_id, leg, ts_utc, price, qty, fee)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (our_order_id, leg.upper(), ts_utc, float(price), float(qty), float(fee)),
                )

            inserted += 1
            updated_orders.add(our_order_id)

        # 3) обновим статус ордеров
        orders_updated = 0
        for oid in updated_orders:
            new_status = _recompute_order_status(conn, oid)
            cur.execute("UPDATE orders SET status=? WHERE order_id=?", (new_status, oid))
            orders_updated += 1

    return {"fills_total": len(fills), "inserted": inserted, "skipped": skipped, "orders_updated": len(updated_orders)}
