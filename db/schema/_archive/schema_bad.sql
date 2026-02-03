-- =========================================================
-- SenseiTrader v1 - SQLite schema
-- =========================================================

-- ВАЖНО:
-- 1) Все timestamp-ы в UTC, формат ISO8601 (TEXT).
-- 2) Включай PRAGMA foreign_keys = ON; при подключении.
-- 3) Журналирование WAL включаем в коде: PRAGMA journal_mode=WAL;
-- =========================================================

BEGIN TRANSACTION;

-- -----------------------------
-- 0. Версионность схемы
-- -----------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version         INTEGER PRIMARY KEY,
    applied_at_utc  TEXT NOT NULL
);

-- -----------------------------
-- 1. Таблица signals
--    Сигналы от Sensei (LLM → сервис)
-- -----------------------------
CREATE TABLE IF NOT EXISTS signals (
    signal_id               TEXT PRIMARY KEY,              -- UUIDv7 или аналог
    schema_version          TEXT NOT NULL DEFAULT '1.0',

    ts_utc                  TEXT NOT NULL,                 -- момент генерации сигнала (UTC)

    symbol                  TEXT NOT NULL,                 -- тикер (AAPL, NVDA)
    asset_class             TEXT NOT NULL,                 -- stock / etf / ...
    side                    TEXT NOT NULL,                 -- BUY / SELL
    entry_type              TEXT NOT NULL,                 -- market / limit / stop / ...

    entry                   REAL NOT NULL,                 -- цена входа
    stop                    REAL NOT NULL,                 -- стоп-лосс
    take                    REAL NOT NULL,                 -- тейк-профит

    time_in_force           TEXT NOT NULL,                 -- DAY / GTC / ...

    p_win_raw               REAL NOT NULL,                 -- [0;1]
    risk_pct_equity_max     REAL NOT NULL,                 -- доля equity под риск (0.0075 = 0.75%)

    notes                   TEXT,                          -- краткое объяснение
    snapshot_hash           TEXT NOT NULL,                 -- sha256 снапшота входных данных

    exchange                TEXT,                          -- основной листинг (NASDAQ, NYSE)
    tags_json               TEXT,                          -- JSON-массив тегов (опционально)

    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts
    ON signals (symbol, ts_utc);

CREATE INDEX IF NOT EXISTS idx_signals_snapshot_hash
    ON signals (snapshot_hash);


-- -----------------------------
-- 2. Таблица approvals
--    Решения RiskGate по сигналам
-- -----------------------------
CREATE TABLE IF NOT EXISTS approvals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id               TEXT NOT NULL UNIQUE,          -- 1 approval на 1 signal

    approved                INTEGER NOT NULL,              -- 0/1
    reason                  TEXT NOT NULL,                 -- enum ApprovalReason
    reason_detail           TEXT,                          -- текстовое пояснение

    p_win_calibrated        REAL NOT NULL,                 -- [0;1]
    ev_after_costs          REAL NOT NULL,                 -- ожидаемое значение после комиссий (в долях)
    rr                      REAL NOT NULL,                 -- reward/risk

    qty                     INTEGER NOT NULL,              -- количество единиц инструмента
    risk_usd                REAL NOT NULL,                 -- риск в долларах

    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (signal_id) REFERENCES signals (signal_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_approvals_signal_id
    ON approvals (signal_id);


-- -----------------------------
-- 3. Таблица orders
--    Наши ордера (parent + OCO дети)
-- -----------------------------
CREATE TABLE IF NOT EXISTS orders (
    order_id                TEXT PRIMARY KEY,              -- детерминированный hash(signal_id,symbol,ts_utc)

    signal_id               TEXT NOT NULL,                 -- ссылка на исходный сигнал
    approval_row_id         INTEGER,                       -- опционально: ссылка на approvals.id

    symbol                  TEXT NOT NULL,
    asset_class             TEXT NOT NULL,
    side                    TEXT NOT NULL,                 -- BUY / SELL
    qty                     INTEGER NOT NULL,

    -- Родительский ордер
    parent_type             TEXT NOT NULL,                 -- MKT / LMT / ...
    parent_price            REAL,                          -- цена для LMT/STP_LMT
    parent_tif              TEXT,                          -- TIF родителя
    parent_outside_rth      INTEGER,                       -- 0/1

    -- STOP-ребёнок
    child_stop_type         TEXT NOT NULL,                 -- STP / STP_LMT
    child_stop_price        REAL NOT NULL,
    child_stop_tif          TEXT,
    child_stop_outside_rth  INTEGER,

    -- TAKE-ребёнок
    child_take_type         TEXT NOT NULL,                 -- LMT
    child_take_price        REAL NOT NULL,
    child_take_tif          TEXT,
    child_take_outside_rth  INTEGER,

    time_in_force           TEXT NOT NULL,                 -- TIF по умолчанию для ордера

    created_ts_utc          TEXT NOT NULL,                 -- когда ордер построен
    status                  TEXT NOT NULL,                 -- enum OrderStatus
    last_update_ts_utc      TEXT NOT NULL,                 -- последний апдейт статуса

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


-- -----------------------------
-- 4. Таблица executions
--    Исполнения от брокера (partial/full)
-- -----------------------------
CREATE TABLE IF NOT EXISTS executions (
    exec_id                 TEXT PRIMARY KEY,              -- broker-native ID
    order_id                TEXT NOT NULL,                 -- наш order_id

    ts_utc                  TEXT NOT NULL,
    price                   REAL NOT NULL,
    qty                     INTEGER NOT NULL,
    fee                     REAL NOT NULL,                 -- комиссия за этот fill

    status                  TEXT NOT NULL,                 -- enum ExecutionStatus

    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (order_id) REFERENCES orders (order_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_executions_order_ts
    ON executions (order_id, ts_utc);


-- -----------------------------
-- 5. Таблица positions
--    Агрегированные позиции по инструментам
-- -----------------------------
CREATE TABLE IF NOT EXISTS positions (
    position_id             INTEGER PRIMARY KEY AUTOINCREMENT,

    symbol                  TEXT NOT NULL,
    asset_class             TEXT NOT NULL,
    side                    TEXT NOT NULL,                 -- LONG / SHORT

    qty                     INTEGER NOT NULL,              -- нетто по инструменту
    avg_price               REAL NOT NULL,                 -- средняя цена входа

    realized_pnl            REAL NOT NULL DEFAULT 0.0,     -- реализованный PnL
    unrealized_pnl          REAL NOT NULL DEFAULT 0.0,     -- нереализованный PnL

    last_update_ts_utc      TEXT NOT NULL,

    UNIQUE (symbol, asset_class),
    CHECK (qty <> 0)                                       -- нулевая позиция не хранится
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol
    ON positions (symbol);


-- -----------------------------
-- 6. Таблица risk_snapshots
--    Дневные снимки риска / equity
-- -----------------------------
CREATE TABLE IF NOT EXISTS risk_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,

    as_of_date_utc          TEXT NOT NULL,                 -- YYYY-MM-DD (дата начала торгового дня, UTC)
    equity_start_day        REAL NOT NULL,
    equity_current          REAL NOT NULL,

    realized_pnl_day        REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl_day      REAL NOT NULL DEFAULT 0.0,

    daily_loss_limit_pct    REAL NOT NULL,                 -- 0.02 = лимит -2%
    kill_switch_triggered   INTEGER NOT NULL DEFAULT 0,    -- 0/1

    equity_utilization      REAL NOT NULL,                 -- доля задействованного equity [0;1]

    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE (as_of_date_utc)
);

CREATE INDEX IF NOT EXISTS idx_risk_snapshots_date
    ON risk_snapshots (as_of_date_utc);


-- -----------------------------
-- 7. Таблица runtime_flags
--    Флаги исполнения (kill-switch и др.)
-- -----------------------------
CREATE TABLE IF NOT EXISTS runtime_flags (
    key                     TEXT PRIMARY KEY,              -- например, 'kill_switch', 'mode'
    value                   TEXT NOT NULL,                 -- значение в текстовом виде (JSON/строка)
    updated_at_utc          TEXT NOT NULL DEFAULT (datetime('now'))
);


-- -----------------------------
-- 8. Таблица sheets_sync_queue
--    Очередь на синхронизацию с Google Sheets
-- -----------------------------
CREATE TABLE IF NOT EXISTS sheets_sync_queue (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,

    entity_type             TEXT NOT NULL,                 -- 'trade', 'position', 'stats', ...
    entity_id               TEXT NOT NULL,                 -- ID сущности (trade_id/order_id/position_id...)
    operation               TEXT NOT NULL,                 -- 'insert' / 'update'

    payload_json            TEXT NOT NULL,                 -- сериализованный JSON-пакет для Sheets
    retry_count             INTEGER NOT NULL DEFAULT 0,

    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    last_attempt_at_utc     TEXT,

    UNIQUE (entity_type, entity_id, operation)
);

CREATE INDEX IF NOT EXISTS idx_sheets_queue_created
    ON sheets_sync_queue (created_at_utc);


-- -----------------------------
-- 9. Таблица telegram_notifications
--    Учёт уведомлений в Telegram (для идемпотентности и аудита)
-- -----------------------------
CREATE TABLE IF NOT EXISTS telegram_notifications (
    notification_id         TEXT PRIMARY KEY,              -- совпадает с model.notification_id
    ts_utc                  TEXT NOT NULL,

    type                    TEXT NOT NULL,                 -- enum NotificationType
    severity                TEXT NOT NULL,                 -- enum NotificationSeverity

    message                 TEXT NOT NULL,                 -- основной отправленный текст

    symbol                  TEXT,
    signal_id               TEXT,
    order_id                TEXT,
    trade_id                TEXT,

    extra_json              TEXT,                          -- структурированные данные (JSON)

    sent_at_utc             TEXT,                          -- когда реально отправили (или NULL, если в очереди)
    last_error              TEXT                           -- текст ошибки отправки, если была
);

CREATE INDEX IF NOT EXISTS idx_telegram_notifications_ts
    ON telegram_notifications (ts_utc);

CREATE INDEX IF NOT EXISTS idx_telegram_notifications_status
    ON telegram_notifications (sent_at_utc);


-- -----------------------------
-- 10. View: v_order_pnl_r
--     PnL и R по ордерам
-- -----------------------------
CREATE VIEW IF NOT EXISTS v_order_pnl_r AS
SELECT
    o.order_id                              AS order_id,
    o.signal_id                             AS signal_id,
    o.symbol                                AS symbol,
    o.side                                  AS side,
    o.qty                                   AS qty_planned,

    -- сколько реально исполнено
    COALESCE(SUM(e.qty), 0)                 AS qty_executed,

    -- "денежный поток" по сделке (с учётом направления)
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

    -- реализованный PnL по ордеру
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

    -- плановый риск и R из approvals
    a.risk_usd                              AS risk_usd,
    a.rr                                    AS rr_planned,

    -- PnL в R: сколько R реально заработано/потеряно
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
