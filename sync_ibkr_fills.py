#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SenseiTrader: sync_ibkr_fills.py

Назначение:
- Подключиться к TWS/IB Gateway через ib_insync
- Считать executions (fills) и синхронизировать их в SQLite

Примечание (Windows):
- В тексте этого блока не используем обратный слэш, чтобы исключить unicode-escape ошибки.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, List

# --- Optional TOML config support (если нужно) ---
try:
    import tomllib  # py3.11+
except Exception:
    tomllib = None
    try:
        import tomli as tomllib  # type: ignore
    except Exception:
        tomllib = None

from ib_insync import IB, ExecutionFilter  # type: ignore


# =========================
# Helpers / logging
# =========================

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "+00:00")

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().lower()
    return v in ("1", "true", "yes", "y", "on")

def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    try:
        return int(v.strip())
    except Exception:
        return default

def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v

def _pfx(msg: str) -> str:
    return f"[sync_ibkr_fills] {msg}"

def log(msg: str) -> None:
    print(_pfx(msg), flush=True)

def debug_log(sp: "SyncParams", msg: str) -> None:
    if sp.debug:
        print(_pfx(f"debug: {msg}"), flush=True)

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _safe_int(x: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if x is None:
            return default
        if isinstance(x, bool):
            return int(x)
        return int(x)
    except Exception:
        return default

def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    return {k: r[k] for k in r.keys()}


# =========================
# Dataclasses
# =========================

@dataclass
class IBParams:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 2
    readonly: bool = False

@dataclass
class DBParams:
    path: str = "data/trader.db"

@dataclass
class SyncParams:
    db: DBParams = field(default_factory=DBParams)
    ib: IBParams = field(default_factory=IBParams)

    lookback_minutes: int = 1440
    nofilter: bool = False
    adopt: bool = False
    debug: bool = False

    # Если True, дополнительно отфильтровываем fills по since_utc даже при NOFILTER
    enforce_time_filter: bool = True


# =========================
# Config loading
# =========================

def _load_toml_config(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path):
        return {}
    if tomllib is None:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)  # type: ignore
    except Exception:
        return {}

def _apply_config(sp: SyncParams) -> None:
    # 1) ENV first
    sp.db.path = _env_str("SENSEI_DB_PATH", sp.db.path)

    sp.ib.host = _env_str("SENSEI_IB_HOST", sp.ib.host)
    sp.ib.port = _env_int("SENSEI_IB_PORT", sp.ib.port)
    sp.ib.client_id = _env_int("SENSEI_IB_SYNC_CLIENT_ID", sp.ib.client_id)

    sp.lookback_minutes = _env_int("SENSEI_IB_SYNC_LOOKBACK_MINUTES", sp.lookback_minutes)
    sp.nofilter = _env_bool("SENSEI_IB_SYNC_NOFILTER", sp.nofilter)
    sp.adopt = _env_bool("SENSEI_IB_SYNC_ADOPT", sp.adopt)
    sp.debug = _env_bool("SENSEI_IB_SYNC_DEBUG", sp.debug)

    # 2) TOML optional (если есть), но только если env не задан
    cfg_path = os.environ.get("SENSEI_CONFIG", "").strip()
    if not cfg_path:
        return

    cfg = _load_toml_config(cfg_path)
    if not cfg:
        return

    try:
        db = cfg.get("db", {}) if isinstance(cfg, dict) else {}
        ib = cfg.get("ib", {}) if isinstance(cfg, dict) else {}
        sync = cfg.get("sync", {}) if isinstance(cfg, dict) else {}

        if "SENSEI_DB_PATH" not in os.environ:
            if isinstance(db, dict) and isinstance(db.get("path"), str) and db.get("path"):
                sp.db.path = db["path"]

        if "SENSEI_IB_HOST" not in os.environ:
            if isinstance(ib, dict) and isinstance(ib.get("host"), str) and ib.get("host"):
                sp.ib.host = ib["host"]

        if "SENSEI_IB_PORT" not in os.environ:
            if isinstance(ib, dict) and isinstance(ib.get("port"), int):
                sp.ib.port = int(ib["port"])

        if "SENSEI_IB_SYNC_CLIENT_ID" not in os.environ:
            if isinstance(ib, dict) and isinstance(ib.get("client_id"), int):
                sp.ib.client_id = int(ib["client_id"])

        if "SENSEI_IB_SYNC_LOOKBACK_MINUTES" not in os.environ:
            if isinstance(sync, dict) and isinstance(sync.get("lookback_minutes"), int):
                sp.lookback_minutes = int(sync["lookback_minutes"])

        if "SENSEI_IB_SYNC_NOFILTER" not in os.environ:
            if isinstance(sync, dict) and isinstance(sync.get("nofilter"), bool):
                sp.nofilter = bool(sync["nofilter"])

        if "SENSEI_IB_SYNC_ADOPT" not in os.environ:
            if isinstance(sync, dict) and isinstance(sync.get("adopt"), bool):
                sp.adopt = bool(sync["adopt"])

        if "SENSEI_IB_SYNC_DEBUG" not in os.environ:
            if isinstance(sync, dict) and isinstance(sync.get("debug"), bool):
                sp.debug = bool(sync["debug"])

    except Exception:
        return


# =========================
# DB helpers
# =========================

def _connect_db(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con

def _table_columns(cur: sqlite3.Cursor, table: str) -> List[str]:
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]

def _load_orders_maps(cur: sqlite3.Cursor, debug: bool) -> Tuple[Dict[str, Dict[str, Any]],
                                                                Dict[str, Dict[str, Any]],
                                                                Dict[int, Dict[str, Any]]]:
    rows = cur.execute("SELECT * FROM orders").fetchall()
    orders_by_oid: Dict[str, Dict[str, Any]] = {}
    orders_by_ref: Dict[str, Dict[str, Any]] = {}
    orders_by_ib: Dict[int, Dict[str, Any]] = {}

    for r in rows:
        d = _row_to_dict(r)
        oid = d.get("order_id")
        if isinstance(oid, str) and oid:
            orders_by_oid[oid] = d

        oref = d.get("order_ref")
        if isinstance(oref, str) and oref:
            orders_by_ref[oref] = d

        for k in ("ib_parent", "ib_take", "ib_stop"):
            iv = _safe_int(d.get(k))
            if iv is not None:
                orders_by_ib[iv] = d

    if debug:
        print(_pfx(f"debug: orders_ib_map size={len(orders_by_ib)}"), flush=True)

    return orders_by_oid, orders_by_ref, orders_by_ib

def _exec_exists(cur: sqlite3.Cursor, exec_id: str) -> bool:
    r = cur.execute("SELECT 1 FROM executions WHERE exec_id=? LIMIT 1", (exec_id,)).fetchone()
    return r is not None

def _insert_execution(cur: sqlite3.Cursor,
                      order_id: str,
                      leg: str,
                      ts_utc: str,
                      price: float,
                      qty: float,
                      fee: float,
                      exec_id: str) -> bool:
    if _exec_exists(cur, exec_id):
        return False

    cur.execute(
        "INSERT INTO executions(order_id, leg, ts_utc, price, qty, fee, exec_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (order_id, leg, ts_utc, price, qty, fee, exec_id),
    )
    return True

def _create_stub_order(cur: sqlite3.Cursor,
                       order_id: str,
                       symbol: str,
                       side: str,
                       qty: float,
                       status: str,
                       reason: str,
                       order_ref: Optional[str],
                       ib_parent: Optional[int],
                       created_ts_utc: str) -> None:
    created_ts = created_ts_utc
    last_update_ts_utc = created_ts_utc

    cur.execute(
        "INSERT INTO orders(order_id, symbol, side, qty, status, reason, ib_parent, ib_take, ib_stop, "
        "created_ts, order_ref, created_ts_utc, last_update_ts_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            order_id,
            symbol,
            side,
            float(qty),
            status,
            reason,
            ib_parent,
            None,
            None,
            created_ts,
            order_ref,
            created_ts_utc,
            last_update_ts_utc,
        ),
    )

def _update_order_ib_parent_if_empty(cur: sqlite3.Cursor, order_id: str, ib_parent: int) -> int:
    cur.execute(
        "UPDATE orders SET ib_parent=?, last_update_ts_utc=? "
        "WHERE order_id=? AND (ib_parent IS NULL OR ib_parent='')",
        (ib_parent, _iso_utc(_now_utc()), order_id),
    )
    return cur.rowcount


# =========================
# IB helpers
# =========================

def _connect_ib(sp: SyncParams) -> IB:
    ib = IB()
    debug_log(sp, f"connect host={sp.ib.host} port={sp.ib.port} clientId={sp.ib.client_id} readonly={sp.ib.readonly}")
    try:
        ib.connect(sp.ib.host, sp.ib.port, clientId=sp.ib.client_id, readonly=sp.ib.readonly)
    except Exception as e:
        log(f"API connection failed: {repr(e)}")
        log("Make sure TWS/IB Gateway is running and API port is open.")
        raise
    return ib

def _since_utc(sp: SyncParams) -> datetime:
    return _now_utc() - timedelta(minutes=int(sp.lookback_minutes))

def _ib_filter_time_str(dt_utc: datetime) -> str:
    dt = dt_utc.astimezone(timezone.utc)
    return dt.strftime("%Y%m%d %H:%M:%S")

def _fill_time_to_utc(dt: Any) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return _now_utc()

def _commission(fill: Any) -> float:
    try:
        cr = getattr(fill, "commissionReport", None)
        if cr and getattr(cr, "commission", None) is not None:
            return float(cr.commission)
    except Exception:
        pass
    return 0.0


# =========================
# Core sync
# =========================

def sync() -> int:
    sp = SyncParams()
    _apply_config(sp)

    log(f"DB: {sp.db.path}")

    con = _connect_db(sp.db.path)
    cur = con.cursor()

    if sp.debug:
        try:
            exec_cols = _table_columns(cur, "executions")
            ord_cols = _table_columns(cur, "orders")
            debug_log(sp, f"executions cols={exec_cols}")
            debug_log(sp, f"orders cols={ord_cols}")
        except Exception:
            pass

    orders_by_oid, orders_by_ref, orders_by_ib = _load_orders_maps(cur, sp.debug)

    since = _since_utc(sp)
    debug_log(sp, f"lookback_min={sp.lookback_minutes}, since_utc={_iso_utc(since)}")

    ib = _connect_ib(sp)

    inserted = 0
    adopted = 0
    skipped = 0
    unmatched = 0
    orders_updated = 0

    try:
        fills: List[Any] = []

        if sp.nofilter:
            fills = ib.reqExecutions()
            debug_log(sp, f"NOFILTER reqExecutions returned {len(fills)} fills")
        else:
            t_str = _ib_filter_time_str(since)
            ef = ExecutionFilter(time=t_str)
            fills = ib.reqExecutions(ef)
            debug_log(sp, f"ExecutionFilter(time={t_str}) returned {len(fills)} fills")

        if sp.enforce_time_filter:
            before = len(fills)
            ff: List[Any] = []
            for f in fills:
                try:
                    ft = _fill_time_to_utc(f.execution.time)
                    if ft >= since:
                        ff.append(f)
                except Exception:
                    ff.append(f)
            fills = ff
            debug_log(sp, f"After time-filter: {before} -> {len(fills)}")

        for f in fills:
            ex = f.execution
            exec_id = str(getattr(ex, "execId", "") or "")
            if not exec_id:
                skipped += 1
                continue

            order_ref = getattr(ex, "orderRef", None)
            order_ref = str(order_ref) if order_ref not in (None, "") else None

            ib_order_id = _safe_int(getattr(ex, "orderId", None))
            side = str(getattr(ex, "side", "") or "")
            shares = _safe_float(getattr(ex, "shares", 0.0))
            price = _safe_float(getattr(ex, "price", 0.0))
            ft_utc = _fill_time_to_utc(getattr(ex, "time", None))
            ts_utc = _iso_utc(ft_utc)

            symbol = ""
            try:
                c = getattr(f, "contract", None)
                if c is not None and getattr(c, "symbol", None):
                    symbol = str(c.symbol)
            except Exception:
                symbol = ""

            fee = _commission(f)

            matched_order: Optional[Dict[str, Any]] = None
            leg = "PARENT"

            if order_ref and order_ref in orders_by_ref:
                matched_order = orders_by_ref[order_ref]

            if matched_order is None and ib_order_id is not None and ib_order_id in orders_by_ib:
                matched_order = orders_by_ib[ib_order_id]

            if matched_order is None:
                if sp.adopt:
                    stub_oid = f"adopt-{exec_id}"
                    created_ts_utc = _iso_utc(_now_utc())
                    try:
                        _create_stub_order(
                            cur=cur,
                            order_id=stub_oid,
                            symbol=symbol or "UNKNOWN",
                            side=side or "UNKNOWN",
                            qty=shares if shares else 0.0,
                            status="FILLED",
                            reason="ADOPTED_FILL",
                            order_ref=order_ref,
                            ib_parent=ib_order_id,
                            created_ts_utc=created_ts_utc,
                        )
                        adopted += 1
                        d = {
                            "order_id": stub_oid,
                            "symbol": symbol or "UNKNOWN",
                            "side": side or "UNKNOWN",
                            "qty": shares if shares else 0.0,
                            "status": "FILLED",
                            "reason": "ADOPTED_FILL",
                            "order_ref": order_ref,
                            "ib_parent": ib_order_id,
                            "ib_take": None,
                            "ib_stop": None,
                        }
                        orders_by_oid[stub_oid] = d
                        if order_ref:
                            orders_by_ref[order_ref] = d
                        if ib_order_id is not None:
                            orders_by_ib[ib_order_id] = d
                        matched_order = d
                    except Exception:
                        unmatched += 1
                        continue
                else:
                    unmatched += 1
                    continue

            try:
                if ib_order_id is not None:
                    if _safe_int(matched_order.get("ib_take")) == ib_order_id:
                        leg = "TAKE"
                    elif _safe_int(matched_order.get("ib_stop")) == ib_order_id:
                        leg = "STOP"
                    elif _safe_int(matched_order.get("ib_parent")) == ib_order_id:
                        leg = "PARENT"
            except Exception:
                leg = "PARENT"

            oid = str(matched_order.get("order_id"))

            if ib_order_id is not None:
                try:
                    updated = _update_order_ib_parent_if_empty(cur, oid, ib_order_id)
                    if updated:
                        orders_updated += updated
                except Exception:
                    pass

            qty_signed = shares
            if side.upper() == "SELL":
                qty_signed = -abs(shares)

            ok = _insert_execution(
                cur=cur,
                order_id=oid,
                leg=leg,
                ts_utc=ts_utc,
                price=price,
                qty=qty_signed,
                fee=fee,
                exec_id=exec_id,
            )
            if ok:
                inserted += 1
            else:
                skipped += 1

        con.commit()

    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
        try:
            con.close()
        except Exception:
            pass

    log(f"Done. inserted={inserted}, adopted={adopted}, skipped={skipped}, unmatched={unmatched}, orders_updated={orders_updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(sync())

