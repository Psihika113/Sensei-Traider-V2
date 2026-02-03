# -*- coding: utf-8 -*-
import os
import time
import datetime as dt

from app.config import load_app_config
from adapters.ibkr.client import IBKRClient

from ib_insync import Stock, MarketOrder


def main():
    cfg = load_app_config(os.getenv("SENSEI_CONFIG", "config/app.toml"))

    c = IBKRClient(cfg.ibkr)
    c.connect()
    ib = c.ib

    print("Connected:", ib.isConnected())
    print("managedAccounts:", ib.managedAccounts())

    # Ловим ошибки от TWS (самое важное)
    def on_error(reqId, errorCode, errorString, contract):
        sym = getattr(contract, "symbol", None) if contract else None
        print(f"[TWS-ERROR] reqId={reqId} code={errorCode} symbol={sym} msg={errorString}")

    ib.errorEvent += on_error

    # Контракт AAPL
    contract = Stock("AAPL", "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        print("qualifyContracts failed: empty result")
        return
    qc = qualified[0]
    print("Qualified:", qc)

    # MARKET BUY 1
    ref = f"sensei-smoke-{dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    order = MarketOrder("BUY", 1)
    order.tif = "DAY"
    order.orderRef = ref
    # На всякий случай: разрешить вне основной сессии (можно убрать позже)
    order.outsideRth = True

    print("Placing orderRef:", ref)
    trade = ib.placeOrder(qc, order)

    # Подождём статусов
    for i in range(10):
        ib.sleep(1.0)
        st = getattr(trade.orderStatus, "status", None)
        filled = getattr(trade.orderStatus, "filled", None)
        remaining = getattr(trade.orderStatus, "remaining", None)
        avg = getattr(trade.orderStatus, "avgFillPrice", None)
        print(f"[{i+1}/10] status={st} filled={filled} remaining={remaining} avgFill={avg}")

    # Обновим openOrders / trades
    try:
        ib.reqOpenOrders()
        ib.sleep(1.0)
    except Exception as e:
        print("reqOpenOrders error:", e)

    print("openOrders():", len(ib.openOrders() or []))
    print("trades():", len(ib.trades() or []))

    # executions без фильтра
    try:
        ex = ib.reqExecutions()
        print("reqExecutions() no-filter:", len(ex or []))
        for f in (ex or [])[:10]:
            e = f.execution
            print(f"execId={e.execId} orderId={e.orderId} shares={e.shares} price={e.price} time={e.time}")
    except Exception as e:
        print("reqExecutions() failed:", e)

    # Если вдруг завис в Submitted и не исполнился — отменим (на paper безопасно)
    st = getattr(trade.orderStatus, "status", "") or ""
    if st.lower() in ("submitted", "presubmitted"):
        print("Cancelling (still not filled)...")
        ib.cancelOrder(trade.order)
        ib.sleep(2.0)
        print("After cancel status:", getattr(trade.orderStatus, "status", None))

    print("DONE")


if __name__ == "__main__":
    main()
