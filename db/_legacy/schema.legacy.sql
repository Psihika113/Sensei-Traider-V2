CREATE TABLE IF NOT EXISTS schema_migrations (
    version         INTEGER PRIMARY KEY,
    applied_at_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         TEXT NOT NULL UNIQUE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    status          TEXT NOT NULL,
    reason          TEXT NOT NULL,
    created_ts      TEXT NOT NULL,
    created_ts_utc  TEXT,
    order_ref       TEXT,
    ib_parent       INTEGER,
    ib_take         INTEGER,
    ib_stop         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol   ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);

CREATE TABLE IF NOT EXISTS executions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exec_id          TEXT UNIQUE,
    order_id         TEXT NOT NULL,
    leg             TEXT NOT NULL,
    ts_utc          TEXT NOT NULL,
    price           REAL NOT NULL,
    qty             INTEGER NOT NULL,
    fee             REAL NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'FILLED',
    created_at_utc  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exec_order_id ON executions(order_id);
CREATE INDEX IF NOT EXISTS idx_exec_ts       ON executions(ts_utc);
CREATE INDEX IF NOT EXISTS idx_exec_leg      ON executions(leg);
