import sqlite3
from pathlib import Path

db_path = Path("data/trader.db")
print(f"DB: {db_path}")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

for name in ("positions", "v_order_pnl_r"):
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name=?",
        (name,)
    ).fetchone()
    print("\n=== VIEW", name, "===")
    if row and row[0]:
        print(row[0])
    else:
        print("НЕ НАЙДЕНА")

conn.close()
