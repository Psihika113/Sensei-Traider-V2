PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_ts_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty_planned REAL,
  status TEXT,
  created_ts_utc TEXT,
  last_update_ts_utc TEXT
);

CREATE TABLE IF NOT EXISTS executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id TEXT NOT NULL,
  leg TEXT NOT NULL,
  ts_utc TEXT NOT NULL,
  price REAL NOT NULL,
  qty REAL NOT NULL,
  fee REAL NOT NULL DEFAULT 0.0,
  FOREIGN KEY(order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_exec_order_id ON executions(order_id);
CREATE INDEX IF NOT EXISTS idx_exec_ts ON executions(ts_utc);
