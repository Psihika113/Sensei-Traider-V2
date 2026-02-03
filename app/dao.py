# -*- coding: utf-8 -*-
"""
app/dao.py

DB access layer (SQLite).

Ориентировано на текущую минимальную схему v1b из app/migrations.py:
  tables:
    - signals
    - approvals
    - orders
    - executions
    - risk_snapshots
    - runtime_flags
    - sheets_sync_queue
    - telegram_notifications
    - outbox (если используется другим модулем)

Примечание по envelopes/decisions:
  В проекте может быть добавлена миграция для envelopes_v1 / decisions_v5.
  В dao предусмотрены безопасные функции, которые не падают, если таблиц ещё нет.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, List, Optional, Tuple

from app.db import Database, DatabaseError
from core.schemas import (
    Approval,
    ApprovalReason,
    Execution,
    NotificationSeverity,
    NotificationType,
    Order,
    OrderStatus,
    RiskSnapshot,
    Signal,
    TelegramNotification,
)


# =============================================================================
# Helpers
# =============================================================================

def _dt_to_str(x: datetime) -> str:
    """
    Храним ISO8601 UTC без микросекунд.
    """
    if x.tzinfo is None:
        x = x.replace(tzinfo=timezone.utc)
    x = x.astimezone(timezone.utc).replace(microsecond=0)
    return x.isoformat()


def _dt_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_dt(s: str) -> datetime:
    """
    Поддержка:
      - 2026-01-23T13:54:37+00:00
      - 2026-01-23T13:54:37Z
    """
    s = (s or "").strip()
    if not s:
        return _dt_utc_now()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    x = datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=timezone.utc)
    return x.astimezone(timezone.utc)


def _date_to_str(d: date) -> str:
    return d.isoformat()


# =============================================================================
# SIGNALS
# =============================================================================

def insert_signal(db: Database, signal: Signal) -> None:
    tags_json = json.dumps(signal.tags, ensure_ascii=False) if signal.tags is not None else None

    sql = """
    INSERT OR REPLACE INTO signals (
        signal_id, schema_version, ts_utc,
        symbol, asset_class, side, entry_type,
        entry, stop, take,
        time_in_force,
        p_win_raw, risk_pct_equity_max,
        notes, snapshot_hash,
        exchange, tags_json,
        created_at_utc
    ) VALUES (
        ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?, ?,
        ?,
        ?, ?,
        ?, ?,
        ?, ?,
        ?
    )
    """
    params = (
        signal.signal_id,
        signal.schema_version,
        _dt_to_str(signal.ts_utc),
        signal.symbol,
        str(signal.asset_class),
        str(signal.side),
        str(signal.entry_type),
        float(signal.entry),
        float(signal.stop),
        float(signal.take),
        str(signal.time_in_force),
        signal.p_win_raw,
        signal.risk_pct_equity_max,
        signal.notes,
        signal.snapshot_hash,
        signal.exchange,
        tags_json,
        _dt_to_str(_dt_utc_now()),
    )

    with db.transaction() as cur:
        cur.execute(sql, params)


def get_signal(db: Database, signal_id: str) -> Optional[Signal]:
    sql = "SELECT * FROM signals WHERE signal_id = ?"
    row = db.query_one(sql, (signal_id,))
    if row is None:
        return None

    tags = json.loads(row["tags_json"]) if row.get("tags_json") else None

    return Signal(
        schema_version=row["schema_version"],
        signal_id=row["signal_id"],
        ts_utc=_parse_dt(row["ts_utc"]),
        symbol=row["symbol"],
        asset_class=row["asset_class"],
        side=row["side"],
        entry_type=row["entry_type"],
        entry=row["entry"],
        stop=row["stop"],
        take=row["take"],
        time_in_force=row["time_in_force"],
        p_win_raw=row.get("p_win_raw"),
        risk_pct_equity_max=row.get("risk_pct_equity_max"),
        notes=row.get("notes"),
        snapshot_hash=row.get("snapshot_hash"),
        exchange=row.get("exchange"),
        tags=tags,
    )


# =============================================================================
# APPROVALS
# =============================================================================

def upsert_approval(db: Database, approval: Approval) -> int:
    """
    approvals (из migrations.py):
      id (AI), signal_id (UNIQUE), approved, reason, reason_detail,
      p_win_calibrated, rr, risk_pct_effective, qty, created_ts_utc
    """
    sql = """
    INSERT INTO approvals (
        signal_id,
        approved,
        reason,
        reason_detail,
        p_win_calibrated,
        rr,
        risk_pct_effective,
        qty,
        created_ts_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(signal_id) DO UPDATE SET
        approved          = excluded.approved,
        reason            = excluded.reason,
        reason_detail     = excluded.reason_detail,
        p_win_calibrated  = excluded.p_win_calibrated,
        rr                = excluded.rr,
        risk_pct_effective= excluded.risk_pct_effective,
        qty               = excluded.qty,
        created_ts_utc    = excluded.created_ts_utc
    """
    params = (
        approval.signal_id,
        1 if approval.approved else 0,
        approval.reason.value if hasattr(approval.reason, "value") else str(approval.reason),
        getattr(approval, "reason_detail", None),
        getattr(approval, "p_win_calibrated", None),
        getattr(approval, "rr", None),
        getattr(approval, "risk_pct_effective", None),
        getattr(approval, "qty", None),
        _dt_to_str(_dt_utc_now()),
    )

    with db.transaction() as cur:
        cur.execute(sql, params)
        cur.execute("SELECT id FROM approvals WHERE signal_id = ?", (approval.signal_id,))
        row = cur.fetchone()
        if row is None:
            raise DatabaseError(f"Approval upsert failed for signal_id={approval.signal_id}")
        return int(row["id"])


def get_approval(db: Database, signal_id: str) -> Optional[Approval]:
    sql = "SELECT * FROM approvals WHERE signal_id = ?"
    row = db.query_one(sql, (signal_id,))
    if row is None:
        return None

    return Approval(
        signal_id=row["signal_id"],
        approved=bool(row["approved"]),
        reason=ApprovalReason(row["reason"]),
        reason_detail=row.get("reason_detail"),
        p_win_calibrated=row.get("p_win_calibrated"),
        rr=row.get("rr"),
        risk_pct_effective=row.get("risk_pct_effective"),
        qty=row.get("qty"),
    )


# =============================================================================
# ORDERS
# =============================================================================

def upsert_order_minimal(
    db: Database,
    *,
    order_id: str,
    symbol: str,
    side: str,
    qty: float,
    status: str,
    reason: Optional[str] = None,
    ib_parent: Optional[str] = None,
    ib_take: Optional[str] = None,
    ib_stop: Optional[str] = None,
    order_ref: Optional[str] = None,
    created_ts_utc: Optional[datetime] = None,
) -> None:
    """
    orders (v1b минимальный):
      id, order_id UNIQUE, symbol, side, qty, status, reason,
      ib_parent, ib_take, ib_stop, created_ts (legacy), order_ref,
      created_ts_utc, last_update_ts_utc
    """
    now = _dt_utc_now()
    cts = created_ts_utc or now

    sql = """
    INSERT INTO orders (
        order_id,
        symbol,
        side,
        qty,
        status,
        reason,
        ib_parent,
        ib_take,
        ib_stop,
        created_ts,
        order_ref,
        created_ts_utc,
        last_update_ts_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(order_id) DO UPDATE SET
        symbol            = excluded.symbol,
        side              = excluded.side,
        qty               = excluded.qty,
        status            = excluded.status,
        reason            = excluded.reason,
        ib_parent         = excluded.ib_parent,
        ib_take           = excluded.ib_take,
        ib_stop           = excluded.ib_stop,
        order_ref         = excluded.order_ref,
        last_update_ts_utc= excluded.last_update_ts_utc
    """
    params = (
        order_id,
        symbol,
        side,
        float(qty),
        status,
        reason,
        ib_parent,
        ib_take,
        ib_stop,
        _dt_to_str(cts),          # created_ts (legacy)
        order_ref,
        _dt_to_str(cts),          # created_ts_utc
        _dt_to_str(now),          # last_update_ts_utc
    )

    with db.transaction() as cur:
        cur.execute(sql, params)


def get_order(db: Database, order_id: str) -> Optional[Order]:
    sql = "SELECT * FROM orders WHERE order_id = ?"
    row = db.query_one(sql, (order_id,))
    if row is None:
        return None

    return Order(
        order_id=row["order_id"],
        symbol=row["symbol"],
        side=row["side"],
        qty=row["qty"],
        status=OrderStatus(row["status"]) if "status" in row else OrderStatus.NEW,
        reason=row.get("reason"),
        ib_parent=row.get("ib_parent"),
        ib_take=row.get("ib_take"),
        ib_stop=row.get("ib_stop"),
        created_ts=_parse_dt(row["created_ts"]) if row.get("created_ts") else _parse_dt(row["created_ts_utc"]),
        order_ref=row.get("order_ref"),
    )


def update_order_status(db: Database, order_id: str, new_status: str) -> None:
    sql = """
    UPDATE orders
    SET status = ?, last_update_ts_utc = ?
    WHERE order_id = ?
    """
    params = (new_status, _dt_to_str(_dt_utc_now()), order_id)
    with db.transaction() as cur:
        cur.execute(sql, params)


def set_order_ib_ids(
    db: Database,
    order_id: str,
    *,
    ib_parent: Optional[str] = None,
    ib_take: Optional[str] = None,
    ib_stop: Optional[str] = None,
) -> None:
    sql = """
    UPDATE orders
    SET ib_parent = COALESCE(?, ib_parent),
        ib_take   = COALESCE(?, ib_take),
        ib_stop   = COALESCE(?, ib_stop),
        last_update_ts_utc = ?
    WHERE order_id = ?
    """
    params = (ib_parent, ib_take, ib_stop, _dt_to_str(_dt_utc_now()), order_id)
    with db.transaction() as cur:
        cur.execute(sql, params)


# =============================================================================
# EXECUTIONS
# =============================================================================

def insert_execution(db: Database, execution: Execution) -> None:
    """
    executions (v1b базовая):
      id (AI), order_id, leg, ts_utc, price, qty, fee
    """
    sql = """
    INSERT INTO executions (
        order_id,
        leg,
        ts_utc,
        price,
        qty,
        fee
    ) VALUES (?, ?, ?, ?, ?, ?)
    """
    params = (
        execution.order_id,
        getattr(execution, "leg", "PARENT"),
        _dt_to_str(execution.ts_utc),
        float(execution.price),
        float(execution.qty),
        float(getattr(execution, "fee", 0.0) or 0.0),
    )

    with db.transaction() as cur:
        cur.execute(sql, params)


def get_executions_for_order(db: Database, order_id: str) -> List[Execution]:
    sql = "SELECT * FROM executions WHERE order_id = ? ORDER BY ts_utc ASC, id ASC"
    rows = db.query_all(sql, (order_id,))
    out: List[Execution] = []

    for r in rows:
        out.append(
            Execution(
                order_id=r["order_id"],
                leg=r["leg"],
                ts_utc=_parse_dt(r["ts_utc"]),
                price=r["price"],
                qty=r["qty"],
                fee=r.get("fee", 0.0),
            )
        )
    return out


# =============================================================================
# RISK SNAPSHOTS & FLAGS
# =============================================================================

def get_risk_snapshot_for_date(db: Database, day_utc: date) -> Optional[RiskSnapshot]:
    sql = "SELECT * FROM risk_snapshots WHERE as_of_date_utc = ?"
    row = db.query_one(sql, (_date_to_str(day_utc),))
    if row is None:
        return None

    return RiskSnapshot(
        as_of_date=_parse_dt(row["as_of_date_utc"]),
        equity_start_day=row["equity_start_day"],
        equity_current=row["equity_current"],
        realized_pnl_day=row["realized_pnl_day"],
        unrealized_pnl_day=row["unrealized_pnl_day"],
        daily_loss_limit_pct=row["daily_loss_limit_pct"],
        kill_switch_triggered=bool(row["kill_switch_triggered"]),
        equity_utilization=row["equity_utilization"],
    )


def upsert_risk_snapshot(db: Database, snapshot: RiskSnapshot) -> None:
    as_of_str = _date_to_str(snapshot.as_of_date.date())

    sql = """
    INSERT INTO risk_snapshots (
        as_of_date_utc,
        equity_start_day,
        equity_current,
        realized_pnl_day,
        unrealized_pnl_day,
        daily_loss_limit_pct,
        kill_switch_triggered,
        equity_utilization,
        created_at_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(as_of_date_utc) DO UPDATE SET
        equity_start_day        = excluded.equity_start_day,
        equity_current          = excluded.equity_current,
        realized_pnl_day        = excluded.realized_pnl_day,
        unrealized_pnl_day      = excluded.unrealized_pnl_day,
        daily_loss_limit_pct    = excluded.daily_loss_limit_pct,
        kill_switch_triggered   = excluded.kill_switch_triggered,
        equity_utilization      = excluded.equity_utilization
    """
    params = (
        as_of_str,
        float(snapshot.equity_start_day),
        float(snapshot.equity_current),
        float(snapshot.realized_pnl_day),
        float(snapshot.unrealized_pnl_day),
        float(snapshot.daily_loss_limit_pct),
        1 if snapshot.kill_switch_triggered else 0,
        float(snapshot.equity_utilization),
        _dt_to_str(_dt_utc_now()),
    )

    with db.transaction() as cur:
        cur.execute(sql, params)


def get_flag(db: Database, key: str) -> Optional[str]:
    sql = "SELECT value FROM runtime_flags WHERE key = ?"
    row = db.query_one(sql, (key,))
    if row is None:
        return None
    return row["value"]


def set_flag(db: Database, key: str, value: str) -> None:
    sql = """
    INSERT INTO runtime_flags (key, value, updated_at_utc)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET
        value = excluded.value,
        updated_at_utc = excluded.updated_at_utc
    """
    params = (key, value, _dt_to_str(_dt_utc_now()))
    with db.transaction() as cur:
        cur.execute(sql, params)


# =============================================================================
# SHEETS SYNC QUEUE
# =============================================================================

def enqueue_sheets_sync(
    db: Database,
    entity_type: str,
    entity_id: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False)
    now_str = _dt_to_str(_dt_utc_now())

    sql = """
    INSERT INTO sheets_sync_queue (
        entity_type, entity_id, operation, payload_json,
        retry_count, created_at_utc, last_attempt_at_utc
    ) VALUES (
        ?, ?, ?, ?,
        COALESCE(
            (SELECT retry_count FROM sheets_sync_queue WHERE entity_type = ? AND entity_id = ? AND operation = ?),
            0
        ),
        COALESCE(
            (SELECT created_at_utc FROM sheets_sync_queue WHERE entity_type = ? AND entity_id = ? AND operation = ?),
            ?
        ),
        NULL
    )
    ON CONFLICT(entity_type, entity_id, operation) DO UPDATE SET
        payload_json = excluded.payload_json
    """
    params = (
        entity_type, entity_id, operation, payload_json,
        entity_type, entity_id, operation,
        entity_type, entity_id, operation, now_str,
    )

    with db.transaction() as cur:
        cur.execute(sql, params)


def list_sheets_sync_pending(db: Database, limit: int = 100) -> List[Tuple[int, str, str, str, str]]:
    sql = """
    SELECT id, entity_type, entity_id, operation, payload_json
    FROM sheets_sync_queue
    ORDER BY created_at_utc ASC
    LIMIT ?
    """
    rows = db.query_all(sql, (limit,))
    out: List[Tuple[int, str, str, str, str]] = []
    for r in rows:
        out.append((r["id"], r["entity_type"], r["entity_id"], r["operation"], r["payload_json"]))
    return out


def mark_sheets_sync_attempt(db: Database, row_id: int, success: bool) -> None:
    now_str = _dt_to_str(_dt_utc_now())
    with db.transaction() as cur:
        if success:
            cur.execute("DELETE FROM sheets_sync_queue WHERE id = ?", (row_id,))
        else:
            cur.execute(
                """
                UPDATE sheets_sync_queue
                SET retry_count = retry_count + 1,
                    last_attempt_at_utc = ?
                WHERE id = ?
                """,
                (now_str, row_id),
            )


# =============================================================================
# TELEGRAM NOTIFICATIONS
# =============================================================================

def save_notification(db: Database, notif: TelegramNotification) -> None:
    extra_json = json.dumps(notif.extra, ensure_ascii=False) if getattr(notif, "extra", None) else None

    sql = """
    INSERT OR REPLACE INTO telegram_notifications (
        notification_id,
        ts_utc,
        type,
        severity,
        message,
        symbol,
        signal_id,
        order_id,
        trade_id,
        extra_json,
        sent_at_utc,
        last_error
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        notif.notification_id,
        _dt_to_str(notif.ts_utc),
        notif.type.value if hasattr(notif.type, "value") else str(notif.type),
        notif.severity.value if hasattr(notif.severity, "value") else str(notif.severity),
        notif.message,
        notif.symbol,
        notif.signal_id,
        notif.order_id,
        getattr(notif, "trade_id", None),
        extra_json,
        None,
        None,
    )

    with db.transaction() as cur:
        cur.execute(sql, params)


def mark_notification_sent(db: Database, notification_id: str, sent_ts_utc: datetime) -> None:
    sql = """
    UPDATE telegram_notifications
    SET sent_at_utc = ?, last_error = NULL
    WHERE notification_id = ?
    """
    params = (_dt_to_str(sent_ts_utc), notification_id)
    with db.transaction() as cur:
        cur.execute(sql, params)


def mark_notification_error(db: Database, notification_id: str, error_message: str) -> None:
    sql = """
    UPDATE telegram_notifications
    SET last_error = ?
    WHERE notification_id = ?
    """
    params = (str(error_message)[:1024], notification_id)
    with db.transaction() as cur:
        cur.execute(sql, params)


def list_unsent_notifications(
    db: Database,
    severity_filter: str | None = None,
    limit: int = 50,
) -> List[TelegramNotification]:
    params: List[Any] = []
    sql = """
    SELECT
        notification_id,
        ts_utc,
        type,
        severity,
        message,
        symbol,
        signal_id,
        order_id,
        trade_id,
        extra_json,
        sent_at_utc,
        last_error
    FROM telegram_notifications
    WHERE sent_at_utc IS NULL
    """

    if severity_filter == "NONCRITICAL":
        sql += " AND severity <> ?"
        params.append(NotificationSeverity.CRITICAL.value)
    elif severity_filter == "CRITICAL":
        sql += " AND severity = ?"
        params.append(NotificationSeverity.CRITICAL.value)

    sql += " ORDER BY ts_utc ASC LIMIT ?"
    params.append(int(limit))

    rows = db.query_all(sql, params)
    out: List[TelegramNotification] = []

    for r in rows:
        extra = json.loads(r["extra_json"]) if r.get("extra_json") else None
        out.append(
            TelegramNotification(
                notification_id=r["notification_id"],
                ts_utc=_parse_dt(r["ts_utc"]),
                type=NotificationType(r["type"]),
                severity=NotificationSeverity(r["severity"]),
                message=r["message"],
                symbol=r.get("symbol"),
                signal_id=r.get("signal_id"),
                order_id=r.get("order_id"),
                trade_id=r.get("trade_id"),
                extra=extra,
            )
        )
    return out


# =============================================================================
# ENVELOPES / DECISIONS (optional tables)
# =============================================================================

def try_insert_envelope_v1(
    db: Database,
    *,
    source_file: str,
    symbol: str,
    ts_utc: datetime,
    session: Optional[str],
    payload: dict[str, Any],
    ingested_ts_utc: datetime,
    outcome: str,
    err: Optional[str] = None,
) -> None:
    """
    Безопасно: если таблицы envelopes_v1 нет — просто выходим.
    """
    sql = """
    INSERT INTO envelopes_v1 (
        source_file, symbol, ts_utc, session,
        payload_json, ingested_ts_utc,
        outcome, err
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        source_file,
        symbol,
        _dt_to_str(ts_utc),
        session,
        json.dumps(payload, ensure_ascii=False),
        _dt_to_str(ingested_ts_utc),
        outcome,
        err,
    )
    try:
        with db.transaction() as cur:
            cur.execute(sql, params)
    except sqlite3.OperationalError:
        return


def try_insert_decision_v5(
    db: Database,
    *,
    envelope_id: Optional[int],
    source_file: Optional[str],
    ts_utc: datetime,
    action: str,
    reason_code: str,
    reason_text: Optional[str],
    confidence: Optional[float],
    guards: Optional[list[str]],
    policy_version: Optional[str],
    strategy_id: Optional[str],
    payload: dict[str, Any],
) -> None:
    """
    Безопасно: если таблицы decisions_v5 нет — просто выходим.
    """
    sql = """
    INSERT INTO decisions_v5 (
        envelope_id,
        source_file,
        ts_utc,
        action,
        reason_code,
        reason_text,
        confidence,
        guards_json,
        policy_version,
        strategy_id,
        payload_json,
        created_ts_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        envelope_id,
        source_file,
        _dt_to_str(ts_utc),
        action,
        reason_code,
        reason_text,
        confidence,
        json.dumps(guards or [], ensure_ascii=False),
        policy_version,
        strategy_id,
        json.dumps(payload, ensure_ascii=False),
        _dt_to_str(_dt_utc_now()),
    )
    try:
        with db.transaction() as cur:
            cur.execute(sql, params)
    except sqlite3.OperationalError:
        return

def try_insert_envelope_v1_return_id(
    db: Database,
    *,
    source_file: str,
    symbol: str,
    ts_utc: datetime,
    session: Optional[str],
    payload: dict[str, Any],
    ingested_ts_utc: datetime,
    outcome: str,
    err: Optional[str] = None,
) -> Optional[int]:
    """
    Пишет envelopes_v1 и возвращает rowid (envelope_id).
    Безопасно: если таблицы нет — вернёт None.
    """
    sql = """
    INSERT INTO envelopes_v1 (
        source_file, symbol, ts_utc, session,
        payload_json, ingested_ts_utc,
        outcome, err
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        source_file,
        symbol,
        _dt_to_str(ts_utc),
        session,
        json.dumps(payload, ensure_ascii=False),
        _dt_to_str(ingested_ts_utc),
        outcome,
        err,
    )
    try:
        with db.transaction() as cur:
            cur.execute(sql, params)
            return int(cur.lastrowid)
    except sqlite3.OperationalError:
        return None
