# -*- coding: utf-8 -*-
"""
app/migrations.py
"""

from __future__ import annotations

import sqlite3


# -----------------------------
# helpers
# -----------------------------

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    cur = conn.execute(f"PRAGMA table_info({table})")
    for row in cur.fetchall():
        if row[1] == column:
            return True
    return False


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    """
    Безопасно добавляет колонку:
    - если таблицы нет — тихо выходим;
    - если колонка уже есть — ничего не делаем;
    - иначе выполняем ALTER TABLE.
    """
    if not _table_exists(conn, table):
        return
    if _column_exists(conn, table, column):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


# -----------------------------
# base tables
# -----------------------------

def _ensure_base_orders_table(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "orders"):
        return

    conn.execute(
        """
        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id    TEXT    NOT NULL UNIQUE,
            symbol      TEXT    NOT NULL,
            side        TEXT    NOT NULL,     -- BUY / SELL
            qty         REAL    NOT NULL,
            status      TEXT    NOT NULL,     -- NEW / FILLED / PARTIALLY_FILLED / CANCELED ...
            reason      TEXT,                 -- SENSEI_DEMO / MANUAL / и т.п.
            ib_parent   TEXT,
            ib_take     TEXT,
            ib_stop     TEXT,
            created_ts  TEXT,                 -- legacy ISO 8601 UTC
            order_ref   TEXT                  -- v1b
        );
        """
    )


def _ensure_base_executions_table(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "executions"):
        return

    conn.execute(
        """
        CREATE TABLE executions (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT    NOT NULL,
            leg      TEXT    NOT NULL,   -- PARENT / TAKE / STOP ...
            ts_utc   TEXT    NOT NULL,   -- ISO 8601 UTC
            price    REAL    NOT NULL,
            qty      REAL    NOT NULL,
            fee      REAL    NOT NULL DEFAULT 0.0
        );
        """
    )


# -----------------------------
# v1b schema
# -----------------------------

def ensure_v1b_schema(conn: sqlite3.Connection) -> None:
    """
    Идемпотентная миграция v1b + совместимость со старыми БД.
    """
    _ensure_base_orders_table(conn)
    _ensure_base_executions_table(conn)

    _add_column(conn, "orders", "order_ref", "TEXT")

    # Чтобы RiskSnapshot мог работать аккуратно (service.py их использует)
    _add_column(conn, "orders", "created_ts_utc", "TEXT")
    _add_column(conn, "orders", "last_update_ts_utc", "TEXT")


# -----------------------------
# envelopes/decisions (new contour)
# -----------------------------

def _ensure_envelope_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS envelopes_v1 (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file      TEXT NOT NULL,
            symbol           TEXT NOT NULL,
            ts_utc           TEXT NOT NULL,
            session          TEXT,
            payload_json     TEXT NOT NULL,
            ingested_ts_utc  TEXT NOT NULL,
            outcome          TEXT NOT NULL,   -- accepted|stale|bad|done
            err              TEXT
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_envelopes_v1_ts_utc ON envelopes_v1(ts_utc)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_envelopes_v1_symbol ON envelopes_v1(symbol)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_envelopes_v1_source_file ON envelopes_v1(source_file)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions_v5 (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            envelope_id      INTEGER,         -- связь с envelopes_v1.id
            source_file      TEXT,
            ts_utc           TEXT NOT NULL,
            action           TEXT NOT NULL,
            reason_code      TEXT NOT NULL,
            reason_text      TEXT,
            confidence       REAL,
            guards_json      TEXT,
            policy_version   TEXT,
            strategy_id      TEXT,
            payload_json     TEXT NOT NULL,
            created_ts_utc   TEXT NOT NULL
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_v5_ts_utc ON decisions_v5(ts_utc)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_v5_action ON decisions_v5(action)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_v5_envelope_id ON decisions_v5(envelope_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_v5_source_file ON decisions_v5(source_file)")

    conn.commit()


# -----------------------------
# aux tables (нужны dao/notify/sheets/outbox)
# -----------------------------

def ensure_aux_tables(conn: sqlite3.Connection) -> None:
    """
    Таблицы, которые используются в dao.py / notify.py / sheets.py / outbox.py
    и должны существовать всегда.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_flags (
            key            TEXT PRIMARY KEY,
            value          TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_notifications (
            notification_id TEXT PRIMARY KEY,
            ts_utc          TEXT NOT NULL,
            type            TEXT NOT NULL,
            severity        TEXT NOT NULL,
            message         TEXT NOT NULL,
            symbol          TEXT,
            signal_id       TEXT,
            order_id        TEXT,
            trade_id        TEXT,
            extra_json      TEXT,
            sent_at_utc     TEXT,
            last_error      TEXT
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sheets_sync_queue (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type     TEXT NOT NULL,
            entity_id       TEXT NOT NULL,
            operation       TEXT NOT NULL,
            payload_json    TEXT NOT NULL,
            retry_count     INTEGER NOT NULL DEFAULT 0,
            created_at_utc  TEXT NOT NULL DEFAULT (datetime('now')),
            last_attempt_at_utc TEXT,
            UNIQUE(entity_type, entity_id, operation)
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel         TEXT NOT NULL,
            payload         TEXT NOT NULL,
            created_ts_utc  TEXT NOT NULL,
            attempts        INTEGER NOT NULL DEFAULT 0,
            next_try_utc    TEXT NOT NULL,
            last_error      TEXT,
            max_attempts    INTEGER NOT NULL DEFAULT 12
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_snapshots (
            snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date_utc      TEXT NOT NULL UNIQUE,
            equity_start_day    REAL NOT NULL,
            equity_current      REAL NOT NULL,
            realized_pnl_day    REAL NOT NULL DEFAULT 0.0,
            unrealized_pnl_day  REAL NOT NULL DEFAULT 0.0,
            daily_loss_limit_pct REAL NOT NULL,
            kill_switch_triggered INTEGER NOT NULL DEFAULT 0,
            equity_utilization  REAL NOT NULL,
            created_at_utc      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    # --- schema_meta (versioning) ---
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_ts TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
        """
    )
    cur.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value, updated_ts) VALUES ('schema_version', 'v1b', CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value, updated_ts) VALUES ('schema_source', 'migrations', CURRENT_TIMESTAMP)"
    )
    conn.commit()

    # --- signals ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            signal_id           TEXT PRIMARY KEY,
            schema_version      TEXT NOT NULL,
            ts_utc              TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            asset_class         TEXT NOT NULL,
            side                TEXT NOT NULL,
            entry_type          TEXT NOT NULL,
            entry               REAL NOT NULL,
            stop                REAL NOT NULL,
            take                REAL NOT NULL,
            time_in_force       TEXT NOT NULL,
            p_win_raw           REAL,
            risk_pct_equity_max REAL,
            notes               TEXT,
            snapshot_hash       TEXT,
            exchange            TEXT,
            tags_json           TEXT,
            created_at_utc      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts_utc ON signals(ts_utc);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);")

    # --- approvals ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id           TEXT NOT NULL UNIQUE,
            approved            INTEGER NOT NULL,
            reason              TEXT NOT NULL,
            reason_detail       TEXT,
            p_win_calibrated    REAL,
            rr                  REAL,
            risk_pct_effective  REAL,
            qty                 REAL,
            created_ts_utc      TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(signal_id) REFERENCES signals(signal_id) ON DELETE CASCADE
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_created_ts ON approvals(created_ts_utc);")

    # --- new contour tables ---
    _ensure_envelope_tables(conn)


# -----------------------------
# views (PnL)
# -----------------------------

def ensure_views(conn: sqlite3.Connection) -> None:
    """
    VIEW v_order_pnl_r — реализованный PnL по ордеру (пока очень грубо, но стабильно).
    """
    cur = conn.cursor()
    try:
        cur.execute("DROP VIEW IF EXISTS v_order_pnl_r;")
        cur.execute(
            """
            CREATE VIEW v_order_pnl_r AS
            WITH agg AS (
                SELECT
                    o.order_id AS order_id,
                    o.symbol   AS symbol,
                    o.side     AS side,
                    o.qty      AS order_qty,
                    COUNT(e.order_id) AS exec_count,
                    SUM(
                        CASE
                            WHEN UPPER(o.side) = 'BUY'  AND LOWER(e.leg) IN ('parent','open','entry')
                                THEN e.qty
                            WHEN UPPER(o.side) = 'BUY'  AND LOWER(e.leg) IN ('take','take_profit','tp','close')
                                THEN -e.qty
                            WHEN UPPER(o.side) = 'SELL' AND LOWER(e.leg) IN ('parent','open','entry')
                                THEN -e.qty
                            WHEN UPPER(o.side) = 'SELL' AND LOWER(e.leg) IN ('take','take_profit','tp','close')
                                THEN e.qty
                            ELSE 0
                        END
                    ) AS net_qty_order,
                    SUM(
                        CASE
                            WHEN UPPER(o.side) = 'BUY'  AND LOWER(e.leg) IN ('parent','open','entry')
                                THEN -e.price * e.qty
                            WHEN UPPER(o.side) = 'BUY'  AND LOWER(e.leg) IN ('take','take_profit','tp','close')
                                THEN  e.price * e.qty
                            WHEN UPPER(o.side) = 'SELL' AND LOWER(e.leg) IN ('parent','open','entry')
                                THEN  e.price * e.qty
                            WHEN UPPER(o.side) = 'SELL' AND LOWER(e.leg) IN ('take','take_profit','tp','close')
                                THEN -e.price * e.qty
                            ELSE 0
                        END
                    ) AS cash,
                    SUM(COALESCE(e.fee, 0.0)) AS total_fee
                FROM orders o
                LEFT JOIN executions e
                    ON e.order_id = o.order_id
                GROUP BY o.order_id, o.symbol, o.side, o.qty
            )
            SELECT
                order_id,
                symbol,
                side,
                order_qty,
                COALESCE(exec_count, 0) AS exec_count,
                COALESCE(net_qty_order, 0.0) AS net_qty_order,
                COALESCE(cash, 0.0) AS cash,
                COALESCE(total_fee, 0.0) AS total_fee,
                CASE
                    WHEN ABS(COALESCE(net_qty_order, 0.0)) < 1e-9
                        THEN (COALESCE(cash, 0.0) - COALESCE(total_fee, 0.0))
                    ELSE 0.0
                END AS realized_pnl
            FROM agg;
            """
        )
    finally:
        cur.close()
