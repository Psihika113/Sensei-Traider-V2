# scripts/db_peek.py
# -*- coding: utf-8 -*-
import sqlite3, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "trader.db"

def rows(sql, params=()):
    con = sqlite3.connect(DB.as_posix())
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    for r in cur.fetchall():
        print(dict(zip(cols, r)))
    con.close()

if __name__ == "__main__":
    print("== executions (last 5) ==")
    rows("SELECT * FROM executions ORDER BY ts_utc DESC LIMIT 5")
    print("== positions ==")
    rows("SELECT * FROM positions")
