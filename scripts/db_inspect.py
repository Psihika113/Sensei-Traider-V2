# scripts/db_inspect.py
import sqlite3, pathlib

DB = pathlib.Path("data/trader.db")
print("DB:", DB.resolve(), "| exists:", DB.exists())

conn = sqlite3.connect(str(DB))
cur  = conn.cursor()

def cols(table):
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]

# список таблиц
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)

def smart_select(table, want_cols, order_clause="", limit=5):
    cs = cols(table)
    picked = [c for c in want_cols if c in cs]
    if not picked:  # fallback: покажем все колонки, но ограничим строки
        picked = cs
    sql = f"SELECT {', '.join(picked)} FROM {table}"
    if order_clause:
        sql += f" {order_clause}"
    if limit:
        sql += f" LIMIT {limit}"
    try:
        for r in cur.execute(sql):
            print(" ", r)
    except Exception as e:
        print(f" ! query error on {table}: {e}")

print("\norders columns:", cols("orders"))
print("orders last 5:")
# подберём подходящие имена: id/order_id, ts колонки, статус
orders_want = ["id","order_id","symbol","side","status","placed_ts_utc","created_ts_utc","ts_utc","qty"]
# попробуем отсортировать по времени, что найдём
if "placed_ts_utc" in cols("orders"):
    order_by = "ORDER BY placed_ts_utc DESC"
elif "created_ts_utc" in cols("orders"):
    order_by = "ORDER BY created_ts_utc DESC"
elif "ts_utc" in cols("orders"):
    order_by = "ORDER BY ts_utc DESC"
else:
    order_by = ""
smart_select("orders", orders_want, order_by, limit=5)

print("\nexecutions columns:", cols("executions"))
print("executions last 5:")
exec_want = ["exec_id","order_id","symbol","side","price","qty","fee","ts_utc"]
smart_select("executions", exec_want, "ORDER BY rowid DESC", limit=5)

print("\npositions columns:", cols("positions"))
print("positions:")
pos_want = ["symbol","qty","avg_price","updated_ts_utc","ts_utc"]
smart_select("positions", pos_want, "", limit=20)

print("\noutbox columns:", cols("outbox"))
print("outbox last 5:")
out_want = ["id","channel","attempts","tries","last_error","payload","next_at","created_at","updated_at"]
smart_select("outbox", out_want, "ORDER BY id DESC", limit=5)

print("\nheartbeat columns:", cols("heartbeat"))
print("heartbeat last 3:")
hb_want = ["name","ts_utc","ib_ok","sheets_ok","tg_ok"]
smart_select("heartbeat", hb_want, "ORDER BY ts_utc DESC", limit=3)

conn.close()
print("\nOK")
