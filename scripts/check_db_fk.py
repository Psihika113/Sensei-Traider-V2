# -*- coding: utf-8 -*-
from app.db import connect
from app.dao import DAO
from core.schemas import Signal

if __name__ == "__main__":
    conn = connect("data/trader.db")
    dao = DAO(conn)
    sig = Signal(
        signal_id="TEST-FK-0001",
        ts_utc="2025-09-23T12:00:00Z",
        symbol="AAPL",
        side="BUY",
        entry_type="LIMIT",
        entry=100.0, stop=98.0, take=104.0,
        p_win_raw=0.85
    )
    dao.insert_signal_if_absent(sig)
    print("OK: signal inserted")
