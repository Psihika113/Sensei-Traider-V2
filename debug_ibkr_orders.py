# -*- coding: utf-8 -*-
import os
from app.config import load_app_config
from adapters.ibkr.client import IBKRClient

def main():
    cfg = load_app_config(os.getenv("SENSEI_CONFIG", "config/app.toml"))
    c = IBKRClient(cfg.ibkr)
    c.connect()
    ib = c.ib

    print("Connected:", ib.isConnected())
    print("managedAccounts:", ib.managedAccounts())
    print("clientId:", getattr(ib, "clientId", None))
    try:
        print("serverVersion:", ib.client.serverVersion())
    except Exception:
        print("serverVersion: (n/a)")

    # ВАЖНО: запросить открытые ордера у TWS
    try:
        ib.reqOpenOrders()
        ib.sleep(1.0)
    except Exception as e:
        print("reqOpenOrders error:", e)

    try:
        ib.reqAllOpenOrders()
        ib.sleep(1.0)
    except Exception as e:
        print("reqAllOpenOrders error:", e)

    # openOrders (из ib_insync кеша)
    open_orders = list(ib.openOrders() or [])
    print("\nopenOrders():", len(open_orders))
    for i, o in enumerate(open_orders[:30], 1):
        print(f"\n--- openOrder #{i} ---")
        print("orderId:", getattr(o, "orderId", None),
              "parentId:", getattr(o, "parentId", None),
              "ocaGroup:", getattr(o, "ocaGroup", None))
        print("action:", getattr(o, "action", None),
              "type:", getattr(o, "orderType", None),
              "qty:", getattr(o, "totalQuantity", None))
        print("lmtPrice:", getattr(o, "lmtPrice", None),
              "auxPrice:", getattr(o, "auxPrice", None),
              "tif:", getattr(o, "tif", None),
              "outsideRth:", getattr(o, "outsideRth", None),
              "transmit:", getattr(o, "transmit", None))

    # openTrades / trades
    trades = list(ib.trades() or [])
    open_trades = [t for t in trades if getattr(t, "isDone", lambda: False)() is False]
    print("\ntrades():", len(trades))
    print("open_trades:", len(open_trades))

    for i, t in enumerate(trades[:30], 1):
        o = t.order
        s = t.orderStatus
        con = t.contract
        print(f"\n--- trade #{i} ---")
        print("symbol:", getattr(con, "symbol", None),
              "secType:", getattr(con, "secType", None),
              "exchange:", getattr(con, "exchange", None),
              "currency:", getattr(con, "currency", None))
        print("orderId:", getattr(o, "orderId", None),
              "parentId:", getattr(o, "parentId", None),
              "ocaGroup:", getattr(o, "ocaGroup", None))
        print("action:", getattr(o, "action", None),
              "type:", getattr(o, "orderType", None),
              "qty:", getattr(o, "totalQuantity", None))
        print("lmtPrice:", getattr(o, "lmtPrice", None),
              "auxPrice:", getattr(o, "auxPrice", None),
              "tif:", getattr(o, "tif", None),
              "outsideRth:", getattr(o, "outsideRth", None))
        print("status:", getattr(s, "status", None),
              "filled:", getattr(s, "filled", None),
              "remaining:", getattr(s, "remaining", None),
              "avgFillPrice:", getattr(s, "avgFillPrice", None))

    # executions без фильтра
    try:
        ex = ib.reqExecutions()
        print("\nreqExecutions() no-filter:", len(ex or []))
        for i, f in enumerate((ex or [])[:20], 1):
            e = f.execution
            print(f"exec#{i} execId={e.execId} orderId={e.orderId} shares={e.shares} price={e.price} time={e.time}")
    except Exception as e:
        print("reqExecutions() failed:", e)

if __name__ == "__main__":
    main()
