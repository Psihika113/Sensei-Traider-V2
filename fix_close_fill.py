# fix_close_fill.py
import sqlite3
from ib_insync import IB

DB = r"data\trader_paper.db"
HOST = "127.0.0.1"
PORT = 7497
CLIENT_ID = 2

CLOSE_REF = "sensei-close-001"
ORDER_ID_TARGET = "sensei-dd44120cc8"   # к нему привязываем SELL как закрытие
LEG = "TAKE"                             # чтобы закрытие считалось выходом

def main():
    # 1) Берём execution из IBKR по orderRef
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID)
    ex = ib.reqExecutions()
    ib.disconnect()

    hits = [e for e in ex if getattr(e.execution, "orderRef", "") == CLOSE_REF]
    if not hits:
        raise SystemExit(f"NO IB EXEC with orderRef={CLOSE_REF}")

    e = hits[-1].execution
    exec_id = e.execId
    ts = str(e.time).replace(" ", "T")
    if "+" not in ts and "Z" not in ts:
        ts += "+00:00"

    price = float(e.price)
    qty = float(e.shares)

    # 2) Пишем в SQLite (в executions) если ещё не писали
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cols = [r["name"] for r in cur.execute("PRAGMA table_info(executions)")]
    key_col = "exec_id" if "exec_id" in cols else ("ib_exec_id" if "ib_exec_id" in cols else None)

    if key_col:
        cur.execute(f"SELECT 1 FROM executions WHERE {key_col}=? LIMIT 1", (exec_id,))
        if cur.fetchone():
            print("ALREADY IN DB:", exec_id)
            con.close()
            return

    row = {
        "order_id": ORDER_ID_TARGET,
        "leg": LEG,
        "ts_utc": ts,
        "price": price,
        "qty": qty,
        "fee": 0.0,
    }
    if key_col:
        row[key_col] = exec_id

    ins_keys = [k for k in row.keys() if k in cols]
    q = "INSERT INTO executions(" + ",".join(ins_keys) + ") VALUES (" + ",".join(["?"] * len(ins_keys)) + ")"
    cur.execute(q, tuple(row[k] for k in ins_keys))

    con.commit()
    con.close()

    print("INSERTED CLOSE FILL INTO DB:", exec_id, ts, price, qty)

if __name__ == "__main__":
    main()
