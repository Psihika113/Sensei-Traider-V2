# -*- coding: utf-8 -*-
from __future__ import annotations
import os, datetime as dt, sqlite3, yaml
from typing import Tuple

LAST_ROLLOVER_FILE = "data/last_rollover.txt"

def _yyyymm_utc(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.utcnow()
    return now.strftime("%Y%m")

def _month_bounds_utc(year: int, month: int) -> Tuple[dt.datetime, dt.datetime]:
    start = dt.datetime(year, month, 1)
    end = dt.datetime(year + (1 if month == 12 else 0), (1 if month == 12 else month + 1), 1)
    return start, end

def _load_risk_cfg(path: str = "config/risk_config.yaml") -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def _read_last_rollover() -> str | None:
    try:
        with open(LAST_ROLLOVER_FILE, "r", encoding="utf-8") as f:
            return (f.read() or "").strip() or None
    except Exception:
        return None

def _write_last_rollover(yyyymm: str):
    os.makedirs(os.path.dirname(LAST_ROLLOVER_FILE), exist_ok=True)
    with open(LAST_ROLLOVER_FILE, "w", encoding="utf-8") as f:
        f.write(yyyymm)

def _collect_month_metrics(conn: sqlite3.Connection, year: int, month: int) -> dict:
    start, end = _month_bounds_utc(year, month)
    cur = conn.cursor()

    def q(sql: str, params=()):
        cur.execute(sql, params)
        row = cur.fetchone()
        return 0 if not row or row[0] is None else row[0]

    orders_total  = q("SELECT COUNT(*) FROM orders WHERE placed_ts_utc >= ? AND placed_ts_utc < ?", (start.isoformat(), end.isoformat()))
    orders_placed = q("SELECT COUNT(*) FROM orders WHERE status='PLACED' AND placed_ts_utc >= ? AND placed_ts_utc < ?", (start.isoformat(), end.isoformat()))
    orders_failed = q("SELECT COUNT(*) FROM orders WHERE status='FAILED' AND placed_ts_utc >= ? AND placed_ts_utc < ?", (start.isoformat(), end.isoformat()))
    exec_qty      = q("SELECT SUM(qty)   FROM executions WHERE ts_utc >= ? AND ts_utc < ?", (start.isoformat(), end.isoformat()))
    fees_sum      = q("SELECT SUM(fee)   FROM executions WHERE ts_utc >= ? AND ts_utc < ?", (start.isoformat(), end.isoformat()))
    avg_price     = q("SELECT AVG(price) FROM executions WHERE ts_utc >= ? AND ts_utc < ?", (start.isoformat(), end.isoformat()))

    return {
        "yyyymm": f"{year}{month:02d}",
        "orders_total": int(orders_total or 0),
        "orders_placed": int(orders_placed or 0),
        "orders_failed": int(orders_failed or 0),
        "exec_qty": int(exec_qty or 0),
        "fees_sum": float(fees_sum or 0.0),
        "avg_price": float(avg_price or 0.0),
    }

def monthly_rollover_and_report(sheets, notifier, conn: sqlite3.Connection, logger, now: dt.datetime | None = None):
    now = now or dt.datetime.utcnow()
    cur_year, cur_month = now.year, now.month
    prev_year  = cur_year if cur_month > 1 else cur_year - 1
    prev_month = (cur_month - 1) if cur_month > 1 else 12
    cur_yyyymm = f"{cur_year}{cur_month:02d}"
    prev_yyyymm = f"{prev_year}{prev_month:02d}"

    # создать лист текущего месяца (на всякий случай)
    try:
        sheets.ensure_month_sheet(cur_yyyymm)
    except Exception:
        pass

    # собрать метрики прошлого месяца, записать в Stats и прислать TG
    summary = _collect_month_metrics(conn, prev_year, prev_month)
    summary["note"] = "auto-rollover"
    try:
        sheets.append_month_summary(summary)
    except Exception:
        pass

    try:
        if notifier:
            notifier.critical({
                "event":"monthly.report",
                "prev_yyyymm": prev_yyyymm,
                "orders_total": summary["orders_total"],
                "orders_placed": summary["orders_placed"],
                "orders_failed": summary["orders_failed"],
                "exec_qty": summary["exec_qty"],
                "fees_sum": summary["fees_sum"],
                "avg_price": summary["avg_price"]
            })
    except Exception:
        pass

    _write_last_rollover(cur_yyyymm)

def _should_do_rollover(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.utcnow()
    if now.day != 1:
        return False
    last = _read_last_rollover()
    cur = _yyyymm_utc(now)
    return last != cur
