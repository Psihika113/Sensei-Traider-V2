# -*- coding: utf-8 -*-
from adapters.ibkr.client import IBKRClient
from app.logger import setup_logger

def normalize_result(res):
    """Приводим разные варианты ответа к (ok: bool, order_id: str|int|None, msg: str)."""
    ok = True
    order_id = None
    msg = ""

    if isinstance(res, tuple):
        # Возможные формы: (ok, msg) или (ok, order_id, msg)
        if len(res) == 2:
            ok, msg = res
        elif len(res) == 3:
            ok, order_id, msg = res
        else:
            msg = f"unexpected tuple result: {res}"
            ok = False
    elif isinstance(res, dict):
        ok = res.get("ok", True)
        order_id = res.get("order_id")
        msg = res.get("msg") or str(res)
    else:
        # число/строка — трактуем как order_id
        order_id = res
        msg = f"result: {res}"

    return ok, order_id, msg

def main():
    logger = setup_logger("logs", "INFO", True)
    ib = IBKRClient("127.0.0.1", 7497, 999, logger)

    if not ib.connect():
        print("Connect failed")
        return

    try:
        raw = ib.place_bracket(
            symbol="AAPL",
            side="BUY",           # ОБЯЗАТЕЛЬНО
            parent_type="MKT",
            parent_price=None,
            stop_price=190.00,
            take_price=210.00,
            qty=1,
            tif="DAY",
            outside_rth=False
        )
        ok, order_id, msg = normalize_result(raw)
        print("OK:", ok, "| order_id:", order_id, "|", msg)
    finally:
        if hasattr(ib, "disconnect"):
            ib.disconnect()

if __name__ == "__main__":
    main()
