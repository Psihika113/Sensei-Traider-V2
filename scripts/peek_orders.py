# -*- coding: utf-8 -*-
import sqlite3, json
DB = "data/trader.db"

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # последние 10 ордеров
    cur.execute("""
        SELECT order_id, order_ref, symbol, side, qty, status, placed_ts_utc
        FROM orders
        ORDER BY rowid DESC
        LIMIT 10
    """)
    rows = [dict(r) for r in cur.fetchall()]
    print(json.dumps(rows, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
