CREATE TABLE IF NOT EXISTS schema_migrations (
    version         INTEGER PRIMARY KEY,
    applied_at_utc  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id               TEXT PRIMARY KEY,              -- UUIDv7 Р С‘Р В»Р С‘ Р В°Р Р…Р В°Р В»Р С•Р С–
    schema_version          TEXT NOT NULL DEFAULT '1.0',
    ts_utc                  TEXT NOT NULL,                 -- Р СР С•Р СР ВµР Р…РЎвЂљ Р С–Р ВµР Р…Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘ РЎРѓР С‘Р С–Р Р…Р В°Р В»Р В° (UTC)
    symbol                  TEXT NOT NULL,                 -- РЎвЂљР С‘Р С”Р ВµРЎР‚ (AAPL, NVDA)
    asset_class             TEXT NOT NULL,                 -- stock / etf / ...
    side                    TEXT NOT NULL,                 -- BUY / SELL
    entry_type              TEXT NOT NULL,                 -- market / limit / stop / ...
    entry                   REAL NOT NULL,                 -- РЎвЂ Р ВµР Р…Р В° Р Р†РЎвЂ¦Р С•Р Т‘Р В°
    stop                    REAL NOT NULL,                 -- РЎРѓРЎвЂљР С•Р С—-Р В»Р С•РЎРѓРЎРѓ
    take                    REAL NOT NULL,                 -- РЎвЂљР ВµР в„–Р С”-Р С—РЎР‚Р С•РЎвЂћР С‘РЎвЂљ
    time_in_force           TEXT NOT NULL,                 -- DAY / GTC / ...
    p_win_raw               REAL NOT NULL,                 -- [0;1]
    risk_pct_equity_max     REAL NOT NULL,                 -- Р Т‘Р С•Р В»РЎРЏ equity Р С—Р С•Р Т‘ РЎР‚Р С‘РЎРѓР С” (0.0075 = 0.75%)
    notes                   TEXT,                          -- Р С”РЎР‚Р В°РЎвЂљР С”Р С•Р Вµ Р С•Р В±РЎР‰РЎРЏРЎРѓР Р…Р ВµР Р…Р С‘Р Вµ
    snapshot_hash           TEXT NOT NULL,                 -- sha256 РЎРѓР Р…Р В°Р С—РЎв‚¬Р С•РЎвЂљР В° Р Р†РЎвЂ¦Р С•Р Т‘Р Р…РЎвЂ№РЎвЂ¦ Р Т‘Р В°Р Р…Р Р…РЎвЂ№РЎвЂ¦
    exchange                TEXT,                          -- Р С•РЎРѓР Р…Р С•Р Р†Р Р…Р С•Р в„– Р В»Р С‘РЎРѓРЎвЂљР С‘Р Р…Р С– (NASDAQ, NYSE)
    tags_json               TEXT,                          -- JSON-Р СР В°РЎРѓРЎРѓР С‘Р Р† РЎвЂљР ВµР С–Р С•Р Р† (Р С•Р С—РЎвЂ Р С‘Р С•Р Р…Р В°Р В»РЎРЉР Р…Р С•)
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts
    ON signals (symbol, ts_utc);
CREATE INDEX IF NOT EXISTS idx_signals_snapshot_hash
    ON signals (snapshot_hash);
CREATE TABLE IF NOT EXISTS approvals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id               TEXT NOT NULL UNIQUE,          -- 1 approval Р Р…Р В° 1 signal
    approved                INTEGER NOT NULL,              -- 0/1
    reason                  TEXT NOT NULL,                 -- enum ApprovalReason
    reason_detail           TEXT,                          -- РЎвЂљР ВµР С”РЎРѓРЎвЂљР С•Р Р†Р С•Р Вµ Р С—Р С•РЎРЏРЎРѓР Р…Р ВµР Р…Р С‘Р Вµ
    p_win_calibrated        REAL NOT NULL,                 -- [0;1]
    ev_after_costs          REAL NOT NULL,                 -- Р С•Р В¶Р С‘Р Т‘Р В°Р ВµР СР С•Р Вµ Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘Р Вµ Р С—Р С•РЎРѓР В»Р Вµ Р С”Р С•Р СР С‘РЎРѓРЎРѓР С‘Р в„– (Р Р† Р Т‘Р С•Р В»РЎРЏРЎвЂ¦)
    rr                      REAL NOT NULL,                 -- reward/risk
    qty                     INTEGER NOT NULL,              -- Р С”Р С•Р В»Р С‘РЎвЂЎР ВµРЎРѓРЎвЂљР Р†Р С• Р ВµР Т‘Р С‘Р Р…Р С‘РЎвЂ  Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљР В°
    risk_usd                REAL NOT NULL,                 -- РЎР‚Р С‘РЎРѓР С” Р Р† Р Т‘Р С•Р В»Р В»Р В°РЎР‚Р В°РЎвЂ¦
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_approvals_signal_id
    ON approvals (signal_id);
CREATE TABLE IF NOT EXISTS orders (
    order_id                TEXT PRIMARY KEY,              -- Р Т‘Р ВµРЎвЂљР ВµРЎР‚Р СР С‘Р Р…Р С‘РЎР‚Р С•Р Р†Р В°Р Р…Р Р…РЎвЂ№Р в„– hash(signal_id,symbol,ts_utc)
    signal_id               TEXT NOT NULL,                 -- РЎРѓРЎРѓРЎвЂ№Р В»Р С”Р В° Р Р…Р В° Р С‘РЎРѓРЎвЂ¦Р С•Р Т‘Р Р…РЎвЂ№Р в„– РЎРѓР С‘Р С–Р Р…Р В°Р В»
    approval_row_id         INTEGER,                       -- Р С•Р С—РЎвЂ Р С‘Р С•Р Р…Р В°Р В»РЎРЉР Р…Р С•: РЎРѓРЎРѓРЎвЂ№Р В»Р С”Р В° Р Р…Р В° approvals.id
    symbol                  TEXT NOT NULL,
    asset_class             TEXT NOT NULL,
    side                    TEXT NOT NULL,                 -- BUY / SELL
    qty                     INTEGER NOT NULL,
    parent_type             TEXT NOT NULL,                 -- MKT / LMT / ...
    parent_price            REAL,                          -- РЎвЂ Р ВµР Р…Р В° Р Т‘Р В»РЎРЏ LMT/STP_LMT
    parent_tif              TEXT,                          -- TIF РЎР‚Р С•Р Т‘Р С‘РЎвЂљР ВµР В»РЎРЏ
    parent_outside_rth      INTEGER,                       -- 0/1
    child_stop_type         TEXT NOT NULL,                 -- STP / STP_LMT
    child_stop_price        REAL NOT NULL,
    child_stop_tif          TEXT,
    child_stop_outside_rth  INTEGER,
    child_take_type         TEXT NOT NULL,                 -- LMT
    child_take_price        REAL NOT NULL,
    child_take_tif          TEXT,
    child_take_outside_rth  INTEGER,
    time_in_force           TEXT NOT NULL,                 -- TIF Р С—Р С• РЎС“Р СР С•Р В»РЎвЂЎР В°Р Р…Р С‘РЎР‹ Р Т‘Р В»РЎРЏ Р С•РЎР‚Р Т‘Р ВµРЎР‚Р В°
    created_ts_utc          TEXT NOT NULL,                 -- Р С”Р С•Р С–Р Т‘Р В° Р С•РЎР‚Р Т‘Р ВµРЎР‚ Р С—Р С•РЎРѓРЎвЂљРЎР‚Р С•Р ВµР Р…
    status                  TEXT NOT NULL,                 -- enum OrderStatus
    last_update_ts_utc      TEXT NOT NULL,                 -- Р С—Р С•РЎРѓР В»Р ВµР Т‘Р Р…Р С‘Р в„– Р В°Р С—Р Т‘Р ВµР в„–РЎвЂљ РЎРѓРЎвЂљР В°РЎвЂљРЎС“РЎРѓР В°
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (approval_row_id) REFERENCES approvals (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_orders_symbol_status
    ON orders (symbol, status);
CREATE INDEX IF NOT EXISTS idx_orders_signal_id
    ON orders (signal_id);
CREATE TABLE IF NOT EXISTS executions (
    exec_id                 TEXT PRIMARY KEY,              -- broker-native ID
    order_id                TEXT NOT NULL,                 -- Р Р…Р В°РЎв‚¬ order_id
    ts_utc                  TEXT NOT NULL,
    price                   REAL NOT NULL,
    qty                     INTEGER NOT NULL,
    fee                     REAL NOT NULL,                 -- Р С”Р С•Р СР С‘РЎРѓРЎРѓР С‘РЎРЏ Р В·Р В° РЎРЊРЎвЂљР С•РЎвЂљ fill
    status                  TEXT NOT NULL,                 -- enum ExecutionStatus
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (order_id) REFERENCES orders (order_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_executions_order_ts
    ON executions (order_id, ts_utc);
CREATE TABLE IF NOT EXISTS positions (
    position_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol                  TEXT NOT NULL,
    asset_class             TEXT NOT NULL,
    side                    TEXT NOT NULL,                 -- LONG / SHORT
    qty                     INTEGER NOT NULL,              -- Р Р…Р ВµРЎвЂљРЎвЂљР С• Р С—Р С• Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљРЎС“
    avg_price               REAL NOT NULL,                 -- РЎРѓРЎР‚Р ВµР Т‘Р Р…РЎРЏРЎРЏ РЎвЂ Р ВµР Р…Р В° Р Р†РЎвЂ¦Р С•Р Т‘Р В°
    realized_pnl            REAL NOT NULL DEFAULT 0.0,     -- РЎР‚Р ВµР В°Р В»Р С‘Р В·Р С•Р Р†Р В°Р Р…Р Р…РЎвЂ№Р в„– PnL
    unrealized_pnl          REAL NOT NULL DEFAULT 0.0,     -- Р Р…Р ВµРЎР‚Р ВµР В°Р В»Р С‘Р В·Р С•Р Р†Р В°Р Р…Р Р…РЎвЂ№Р в„– PnL
    last_update_ts_utc      TEXT NOT NULL,
    UNIQUE (symbol, asset_class),
    CHECK (qty <> 0)                                       -- Р Р…РЎС“Р В»Р ВµР Р†Р В°РЎРЏ Р С—Р С•Р В·Р С‘РЎвЂ Р С‘РЎРЏ Р Р…Р Вµ РЎвЂ¦РЎР‚Р В°Р Р…Р С‘РЎвЂљРЎРѓРЎРЏ
);
CREATE INDEX IF NOT EXISTS idx_positions_symbol
    ON positions (symbol);
CREATE TABLE IF NOT EXISTS risk_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date_utc          TEXT NOT NULL,                 -- YYYY-MM-DD (Р Т‘Р В°РЎвЂљР В° Р Р…Р В°РЎвЂЎР В°Р В»Р В° РЎвЂљР С•РЎР‚Р С–Р С•Р Р†Р С•Р С–Р С• Р Т‘Р Р…РЎРЏ, UTC)
    equity_start_day        REAL NOT NULL,
    equity_current          REAL NOT NULL,
    realized_pnl_day        REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl_day      REAL NOT NULL DEFAULT 0.0,
    daily_loss_limit_pct    REAL NOT NULL,                 -- 0.02 = Р В»Р С‘Р СР С‘РЎвЂљ -2%
    kill_switch_triggered   INTEGER NOT NULL DEFAULT 0,    -- 0/1
    equity_utilization      REAL NOT NULL,                 -- Р Т‘Р С•Р В»РЎРЏ Р В·Р В°Р Т‘Р ВµР в„–РЎРѓРЎвЂљР Р†Р С•Р Р†Р В°Р Р…Р Р…Р С•Р С–Р С• equity [0;1]
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (as_of_date_utc)
);
CREATE INDEX IF NOT EXISTS idx_risk_snapshots_date
    ON risk_snapshots (as_of_date_utc);
CREATE TABLE IF NOT EXISTS runtime_flags (
    key                     TEXT PRIMARY KEY,              -- Р Р…Р В°Р С—РЎР‚Р С‘Р СР ВµРЎР‚, 'kill_switch', 'mode'
    value                   TEXT NOT NULL,                 -- Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘Р Вµ Р Р† РЎвЂљР ВµР С”РЎРѓРЎвЂљР С•Р Р†Р С•Р С Р Р†Р С‘Р Т‘Р Вµ (JSON/РЎРѓРЎвЂљРЎР‚Р С•Р С”Р В°)
    updated_at_utc          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sheets_sync_queue (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type             TEXT NOT NULL,                 -- 'trade', 'position', 'stats', ...
    entity_id               TEXT NOT NULL,                 -- ID РЎРѓРЎС“РЎвЂ°Р Р…Р С•РЎРѓРЎвЂљР С‘ (trade_id/order_id/position_id...)
    operation               TEXT NOT NULL,                 -- 'insert' / 'update'
    payload_json            TEXT NOT NULL,                 -- РЎРѓР ВµРЎР‚Р С‘Р В°Р В»Р С‘Р В·Р С•Р Р†Р В°Р Р…Р Р…РЎвЂ№Р в„– JSON-Р С—Р В°Р С”Р ВµРЎвЂљ Р Т‘Р В»РЎРЏ Sheets
    retry_count             INTEGER NOT NULL DEFAULT 0,
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    last_attempt_at_utc     TEXT,
    UNIQUE (entity_type, entity_id, operation)
);
CREATE INDEX IF NOT EXISTS idx_sheets_queue_created
    ON sheets_sync_queue (created_at_utc);
CREATE TABLE IF NOT EXISTS telegram_notifications (
    notification_id         TEXT PRIMARY KEY,              -- РЎРѓР С•Р Р†Р С—Р В°Р Т‘Р В°Р ВµРЎвЂљ РЎРѓ model.notification_id
    ts_utc                  TEXT NOT NULL,
    type                    TEXT NOT NULL,                 -- enum NotificationType
    severity                TEXT NOT NULL,                 -- enum NotificationSeverity
    message                 TEXT NOT NULL,                 -- Р С•РЎРѓР Р…Р С•Р Р†Р Р…Р С•Р в„– Р С•РЎвЂљР С—РЎР‚Р В°Р Р†Р В»Р ВµР Р…Р Р…РЎвЂ№Р в„– РЎвЂљР ВµР С”РЎРѓРЎвЂљ
    symbol                  TEXT,
    signal_id               TEXT,
    order_id                TEXT,
    trade_id                TEXT,
    extra_json              TEXT,                          -- РЎРѓРЎвЂљРЎР‚РЎС“Р С”РЎвЂљРЎС“РЎР‚Р С‘РЎР‚Р С•Р Р†Р В°Р Р…Р Р…РЎвЂ№Р Вµ Р Т‘Р В°Р Р…Р Р…РЎвЂ№Р Вµ (JSON)
    sent_at_utc             TEXT,                          -- Р С”Р С•Р С–Р Т‘Р В° РЎР‚Р ВµР В°Р В»РЎРЉР Р…Р С• Р С•РЎвЂљР С—РЎР‚Р В°Р Р†Р С‘Р В»Р С‘ (Р С‘Р В»Р С‘ NULL, Р ВµРЎРѓР В»Р С‘ Р Р† Р С•РЎвЂЎР ВµРЎР‚Р ВµР Т‘Р С‘)
    last_error              TEXT                           -- РЎвЂљР ВµР С”РЎРѓРЎвЂљ Р С•РЎв‚¬Р С‘Р В±Р С”Р С‘ Р С•РЎвЂљР С—РЎР‚Р В°Р Р†Р С”Р С‘, Р ВµРЎРѓР В»Р С‘ Р В±РЎвЂ№Р В»Р В°
);
CREATE INDEX IF NOT EXISTS idx_telegram_notifications_ts
    ON telegram_notifications (ts_utc);
CREATE INDEX IF NOT EXISTS idx_telegram_notifications_status
    ON telegram_notifications (sent_at_utc);
CREATE VIEW IF NOT EXISTS v_order_pnl_r AS
SELECT
    o.order_id                              AS order_id,
    o.signal_id                             AS signal_id,
    o.symbol                                AS symbol,
    o.side                                  AS side,
    o.qty                                   AS qty_planned,
    COALESCE(SUM(e.qty), 0)                 AS qty_executed,
    COALESCE(
        SUM(
            CASE
                WHEN o.side = 'BUY'  THEN -e.price * e.qty
                WHEN o.side = 'SELL' THEN  e.price * e.qty
                ELSE 0
            END
        ),
        0
    )                                       AS gross_cash,
    COALESCE(SUM(e.fee), 0)                 AS total_fee,
    COALESCE(
        SUM(
            CASE
                WHEN o.side = 'BUY'  THEN -e.price * e.qty
                WHEN o.side = 'SELL' THEN  e.price * e.qty
                ELSE 0
            END
        ),
        0
    ) - COALESCE(SUM(e.fee), 0)             AS realized_pnl,
    a.risk_usd                              AS risk_usd,
    a.rr                                    AS rr_planned,
    CASE
        WHEN a.risk_usd IS NOT NULL AND a.risk_usd <> 0 THEN
            (
                COALESCE(
                    SUM(
                        CASE
                            WHEN o.side = 'BUY'  THEN -e.price * e.qty
                            WHEN o.side = 'SELL' THEN  e.price * e.qty
                            ELSE 0
                        END
                    ),
                    0
                ) - COALESCE(SUM(e.fee), 0)
            ) / a.risk_usd
        ELSE
            NULL
    END                                     AS realized_R
FROM orders o
LEFT JOIN executions e
    ON e.order_id = o.order_id
LEFT JOIN approvals a
    ON a.id = o.approval_row_id
GROUP BY
    o.order_id,
    o.signal_id,
    o.symbol,
    o.side,
    o.qty,
    a.risk_usd,
    a.rr;
