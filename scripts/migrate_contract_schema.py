# -*- coding: utf-8 -*-
import sqlite3, os, sys

DB = os.path.join(os.path.dirname(__file__), "..", "data", "trader.db")
DB = os.path.abspath(DB)

def main():
    if not os.path.exists(DB):
        print(f"DB not found: {DB} — пропускаю (создастся при старте).")
        return 0
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(signals)")
    cols = [r[1] for r in cur.fetchall()]
    if "contract_schema" not in cols:
        cur.execute("ALTER TABLE signals ADD COLUMN contract_schema TEXT NOT NULL DEFAULT 'signal.v1.1'")
        print("OK: added column contract_schema")
    else:
        print("OK: column contract_schema already exists")
    con.commit(); con.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
