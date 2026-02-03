BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS schema_migrations (
    version         INTEGER PRIMARY KEY,
    applied_at_utc  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id               TEXT PRIMARY KEY,              -- UUIDv7 РёР»Рё Р°РЅР°Р»РѕРі
    schema_version          TEXT NOT NULL DEFAULT '1.0',
    ts_utc                  TEXT NOT NULL,                 -- РјРѕРјРµРЅС‚ РіРµРЅРµСЂР°С†РёРё СЃРёРіРЅР°Р»Р° (UTC)
    symbol                  TEXT NOT NULL,                 -- С‚РёРєРµСЂ (AAPL, NVDA)
    asset_class             TEXT NOT NULL,                 -- stock / etf / ...
    side                    TEXT NOT NULL,                 -- BUY / SELL
    entry_type              TEXT NOT NULL,                 -- market / limit / stop / ...
    entry                   REAL NOT NULL,                 -- С†РµРЅР° РІС…РѕРґР°
    stop                    REAL NOT NULL,                 -- СЃС‚РѕРї-Р»РѕСЃСЃ
    take                    REAL NOT NULL,                 -- С‚РµР№Рє-РїСЂРѕС„РёС‚
    time_in_force           TEXT NOT NULL,                 -- DAY / GTC / ...
    p_win_raw               REAL NOT NULL,                 -- [0;1]
    risk_pct_equity_max     REAL NOT NULL,                 -- РґРѕР»СЏ equity РїРѕРґ СЂРёСЃРє (0.0075 = 0.75%)
    notes                   TEXT,                          -- РєСЂР°С‚РєРѕРµ РѕР±СЉСЏСЃРЅРµРЅРёРµ
    snapshot_hash           TEXT NOT NULL,                 -- sha256 СЃРЅР°РїС€РѕС‚Р° РІС…РѕРґРЅС‹С… РґР°РЅРЅС‹С…
    exchange                TEXT,                          -- РѕСЃРЅРѕРІРЅРѕР№ Р»РёСЃС‚РёРЅРі (NASDAQ, NYSE)
    tags_json               TEXT,                          -- JSON-РјР°СЃСЃРёРІ С‚РµРіРѕРІ (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts
    ON signals (symbol, ts_utc);
CREATE INDEX IF NOT EXISTS idx_signals_snapshot_hash
    ON signals (snapshot_hash);
CREATE TABLE IF NOT EXISTS approvals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id               TEXT NOT NULL UNIQUE,          -- 1 approval РЅР° 1 signal
    approved                INTEGER NOT NULL,              -- 0/1
    reason                  TEXT NOT NULL,                 -- enum ApprovalReason
    reason_detail           TEXT,                          -- С‚РµРєСЃС‚РѕРІРѕРµ РїРѕСЏСЃРЅРµРЅРёРµ
    p_win_calibrated        REAL NOT NULL,                 -- [0;1]
    ev_after_costs          REAL NOT NULL,                 -- РѕР¶РёРґР°РµРјРѕРµ Р·РЅР°С‡РµРЅРёРµ РїРѕСЃР»Рµ РєРѕРјРёСЃСЃРёР№ (РІ РґРѕР»СЏС…)
    rr                      REAL NOT NULL,                 -- reward/risk
    qty                     INTEGER NOT NULL,              -- РєРѕР»РёС‡РµСЃС‚РІРѕ РµРґРёРЅРёС† РёРЅСЃС‚СЂСѓРјРµРЅС‚Р°
    risk_usd                REAL NOT NULL,                 -- СЂРёСЃРє РІ РґРѕР»Р»Р°СЂР°С…
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_approvals_signal_id
    ON approvals (signal_id);
CREATE TABLE IF NOT EXISTS orders (
    order_id                TEXT PRIMARY KEY,              -- РґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅС‹Р№ hash(signal_id,symbol,ts_utc)
    signal_id               TEXT NOT NULL,                 -- СЃСЃС‹Р»РєР° РЅР° РёСЃС…РѕРґРЅС‹Р№ СЃРёРіРЅР°Р»
    approval_row_id         INTEGER,                       -- РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ: СЃСЃС‹Р»РєР° РЅР° approvals.id
    symbol                  TEXT NOT NULL,
    asset_class             TEXT NOT NULL,
    side                    TEXT NOT NULL,                 -- BUY / SELL
    qty                     INTEGER NOT NULL,
    parent_type             TEXT NOT NULL,                 -- MKT / LMT / ...
    parent_price            REAL,                          -- С†РµРЅР° РґР»СЏ LMT/STP_LMT
    parent_tif              TEXT,                          -- TIF СЂРѕРґРёС‚РµР»СЏ
    parent_outside_rth      INTEGER,                       -- 0/1
    child_stop_type         TEXT NOT NULL,                 -- STP / STP_LMT
    child_stop_price        REAL NOT NULL,
    child_stop_tif          TEXT,
    child_stop_outside_rth  INTEGER,
    child_take_type         TEXT NOT NULL,                 -- LMT
    child_take_price        REAL NOT NULL,
    child_take_tif          TEXT,
    child_take_outside_rth  INTEGER,
    time_in_force           TEXT NOT NULL,                 -- TIF РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РґР»СЏ РѕСЂРґРµСЂР°
    created_ts_utc          TEXT NOT NULL,                 -- РєРѕРіРґР° РѕСЂРґРµСЂ РїРѕСЃС‚СЂРѕРµРЅ
    status                  TEXT NOT NULL,                 -- enum OrderStatus
    last_update_ts_utc      TEXT NOT NULL,                 -- РїРѕСЃР»РµРґРЅРёР№ Р°РїРґРµР№С‚ СЃС‚Р°С‚СѓСЃР°
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
    order_id                TEXT NOT NULL,                 -- РЅР°С€ order_id
    ts_utc                  TEXT NOT NULL,
    price                   REAL NOT NULL,
    qty                     INTEGER NOT NULL,
    fee                     REAL NOT NULL,                 -- РєРѕРјРёСЃСЃРёСЏ Р·Р° СЌС‚РѕС‚ fill
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
    qty                     INTEGER NOT NULL,              -- РЅРµС‚С‚Рѕ РїРѕ РёРЅСЃС‚СЂСѓРјРµРЅС‚Сѓ
    avg_price               REAL NOT NULL,                 -- СЃСЂРµРґРЅСЏСЏ С†РµРЅР° РІС…РѕРґР°
    realized_pnl            REAL NOT NULL DEFAULT 0.0,     -- СЂРµР°Р»РёР·РѕРІР°РЅРЅС‹Р№ PnL
    unrealized_pnl          REAL NOT NULL DEFAULT 0.0,     -- РЅРµСЂРµР°Р»РёР·РѕРІР°РЅРЅС‹Р№ PnL
    last_update_ts_utc      TEXT NOT NULL,
    UNIQUE (symbol, asset_class),
    CHECK (qty <> 0)                                       -- РЅСѓР»РµРІР°СЏ РїРѕР·РёС†РёСЏ РЅРµ С…СЂР°РЅРёС‚СЃСЏ
);
CREATE INDEX IF NOT EXISTS idx_positions_symbol
    ON positions (symbol);
CREATE TABLE IF NOT EXISTS risk_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date_utc          TEXT NOT NULL,                 -- YYYY-MM-DD (РґР°С‚Р° РЅР°С‡Р°Р»Р° С‚РѕСЂРіРѕРІРѕРіРѕ РґРЅСЏ, UTC)
    equity_start_day        REAL NOT NULL,
    equity_current          REAL NOT NULL,
    realized_pnl_day        REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl_day      REAL NOT NULL DEFAULT 0.0,
    daily_loss_limit_pct    REAL NOT NULL,                 -- 0.02 = Р»РёРјРёС‚ -2%
    kill_switch_triggered   INTEGER NOT NULL DEFAULT 0,    -- 0/1
    equity_utilization      REAL NOT NULL,                 -- РґРѕР»СЏ Р·Р°РґРµР№СЃС‚РІРѕРІР°РЅРЅРѕРіРѕ equity [0;1]
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (as_of_date_utc)
);
CREATE INDEX IF NOT EXISTS idx_risk_snapshots_date
    ON risk_snapshots (as_of_date_utc);
CREATE TABLE IF NOT EXISTS runtime_flags (
    key                     TEXT PRIMARY KEY,              -- РЅР°РїСЂРёРјРµСЂ, 'kill_switch', 'mode'
    value                   TEXT NOT NULL,                 -- Р·РЅР°С‡РµРЅРёРµ РІ С‚РµРєСЃС‚РѕРІРѕРј РІРёРґРµ (JSON/СЃС‚СЂРѕРєР°)
    updated_at_utc          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sheets_sync_queue (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type             TEXT NOT NULL,                 -- 'trade', 'position', 'stats', ...
    entity_id               TEXT NOT NULL,                 -- ID СЃСѓС‰РЅРѕСЃС‚Рё (trade_id/order_id/position_id...)
    operation               TEXT NOT NULL,                 -- 'insert' / 'update'
    payload_json            TEXT NOT NULL,                 -- СЃРµСЂРёР°Р»РёР·РѕРІР°РЅРЅС‹Р№ JSON-РїР°РєРµС‚ РґР»СЏ Sheets
    retry_count             INTEGER NOT NULL DEFAULT 0,
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    last_attempt_at_utc     TEXT,
    UNIQUE (entity_type, entity_id, operation)
);
CREATE INDEX IF NOT EXISTS idx_sheets_queue_created
    ON sheets_sync_queue (created_at_utc);
CREATE TABLE IF NOT EXISTS telegram_notifications (
    notification_id         TEXT PRIMARY KEY,              -- СЃРѕРІРїР°РґР°РµС‚ СЃ model.notification_id
    ts_utc                  TEXT NOT NULL,
    type                    TEXT NOT NULL,                 -- enum NotificationType
    severity                TEXT NOT NULL,                 -- enum NotificationSeverity
    message                 TEXT NOT NULL,                 -- РѕСЃРЅРѕРІРЅРѕР№ РѕС‚РїСЂР°РІР»РµРЅРЅС‹Р№ С‚РµРєСЃС‚
    symbol                  TEXT,
    signal_id               TEXT,
    order_id                TEXT,
    trade_id                TEXT,
    extra_json              TEXT,                          -- СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ (JSON)
    sent_at_utc             TEXT,                          -- РєРѕРіРґР° СЂРµР°Р»СЊРЅРѕ РѕС‚РїСЂР°РІРёР»Рё (РёР»Рё NULL, РµСЃР»Рё РІ РѕС‡РµСЂРµРґРё)
    last_error              TEXT                           -- С‚РµРєСЃС‚ РѕС€РёР±РєРё РѕС‚РїСЂР°РІРєРё, РµСЃР»Рё Р±С‹Р»Р°
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
COMMIT;
