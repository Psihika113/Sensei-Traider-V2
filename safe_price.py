# ===== safe_price.py (полная замена) =====
import sys
import argparse
import math
from ib_insync import IB, Stock, Forex

# ---------- утилиты ----------
def ok_num(x):
    return (x is not None) and isinstance(x, (int, float)) and not math.isnan(x)

def make_contract(symbol: str, sec: str):
    sec = (sec or "STK").upper()
    if sec == "CASH":
        pair = symbol.replace("/", "").upper()
        if len(pair) != 6:
            raise ValueError(f"FX символ должен быть как 'EURUSD' (6 букв), получено: {symbol}")
        return Forex(pair)
    # STK
    c = Stock(symbol.upper(), "SMART", "USD")
    c.primaryExchange = "NASDAQ"  # ускоряет квалификацию для US тикеров
    return c

# ---------- источники цены ----------
def try_stream(ib: IB, contract, timeout: float = 8.0):
    """
    Пытаемся получить цену из стрима (в т.ч. delayed, если включено в TWS).
    Возвращаем (price, 'stream:...') или (None, None)
    """
    ib.reqMarketDataType(3)  # 1=live, 3=delayed
    t = ib.reqMktData(contract, "", False, False)
    ib.waitOnUpdate(timeout=timeout)

    # берём last, иначе mid, иначе close
    if ok_num(t.last):
        return float(t.last), "stream:last"
    if ok_num(t.bid) and ok_num(t.ask):
        return (float(t.bid) + float(t.ask)) / 2.0, "stream:mid"
    if ok_num(t.close):
        return float(t.close), "stream:close"
    return None, None

def try_hist(ib: IB, contract, sec: str):
    """
    Исторические бары как фолбэк.
    STK: 1D / 5m / TRADES (RTH)
    CASH: 1800 S / 1m / MIDPOINT
    """
    if sec == "CASH":
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1800 S",      # 30 минут
            barSizeSetting="1 min",
            whatToShow="MIDPOINT",
            useRTH=False,
            formatDate=1,
        )
        src = "hist:CASH:30m/1m:MIDPOINT"
    else:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="5 mins",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        src = "hist:STK:1D/5m:TRADES"

    if bars:
        return float(bars[-1].close), src
    return None, "hist:none"

# ---------- main ----------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("symbol", help="Тикер. Примеры: AAPL, EURUSD")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7497, help="TWS=7497, IBG=4002 (по умолчанию 7497)")
    p.add_argument("--cid",  type=int, default=321,  help="clientId")
    p.add_argument("--sec", choices=["STK", "CASH"], default="STK", help="Тип инструмента")
    p.add_argument("--feed", choices=["auto", "stream", "hist"], default="auto",
                   help="Источник цены: stream|hist|auto")
    p.add_argument("--json", action="store_true", help="Вывод в JSON для машинного парсинга")
    args = p.parse_args()

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.cid, timeout=30)
    except Exception as e:
        print(f"API connection failed: {e}\nMake sure API port on TWS/IBG is open")
        sys.exit(2)

    # приглушаем болтливые ошибки IB (оставляем чистый вывод):
    # в ib_insync v0.9.86 используем событие errorEvent
    try:
        ib.errorEvent.clear()  # чтобы не накапливать обработчики при повторных запусках
    except Exception:
        pass
    def _silent_error(reqId, code, msg, advancedOrderReject=None):
        # Просто глушим, не печатаем
        return
    ib.errorEvent += _silent_error

    # контракт
    sec = args.sec.upper()
    c = make_contract(args.symbol, sec)
    ib.qualifyContracts(c)

    px = None
    src = None

    # выбор источника
    if args.feed in ("auto", "stream"):
        px, src = try_stream(ib, c, timeout=8.0)

    if px is None and args.feed in ("auto", "hist"):
        px, src = try_hist(ib, c, sec)

    ib.disconnect()

    # вывод
    if px is None:
        msg = f"{args.symbol}: no price (нет ни стрима, ни истории) [{src}]"
        if args.json:
            import json
            print(json.dumps({"symbol": args.symbol, "price": None, "source": src, "ok": False}, ensure_ascii=False))
        else:
            print(msg)
        sys.exit(1)

    if args.json:
        import json
        print(json.dumps({"symbol": args.symbol, "price": px, "source": src, "ok": True}, ensure_ascii=False))
    else:
        print(f"{args.symbol}: {px}  [{src}]")

if __name__ == "__main__":
    main()
# ===== конец файла =====
