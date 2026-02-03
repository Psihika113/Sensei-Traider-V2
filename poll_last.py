# poll_last.py
from ib_insync import IB, Stock
import math
from ib_insync.util import startLoop

HOST, PORT, CID = '127.0.0.1', 7497, 321
SYMBOL = 'AAPL'

def ok(x):
    return isinstance(x, (int, float)) and not math.isnan(x)

def main():
    ib = IB()
    # повышаем таймаут на запросы
    IB.RequestTimeout = 45
    ib.connect(HOST, PORT, clientId=CID, timeout=30)

    c = Stock(SYMBOL, 'SMART', 'USD')
    c.primaryExchange = 'NASDAQ'
    ib.qualifyContracts(c)

    # 1) delayed-stream
    try:
        ib.reqMarketDataType(3)  # 3 = delayed
        t = ib.reqMktData(c, '', False, False)
        ib.sleep(4)
        if any(map(ok, [t.last, t.bid, t.ask, t.close])):
            print(f"{SYMBOL} stream last/bid/ask/close:", t.last, t.bid, t.ask, t.close)
            ib.cancelMktData(c)
            ib.disconnect()
            return
        ib.cancelMktData(c)
    except Exception as e:
        print("stream error:", e)

    # 2) snapshot
    try:
        t = ib.reqMktData(c, '', True, False)
        ib.sleep(3)
        if any(map(ok, [t.last, t.bid, t.ask, t.close])):
            print(f"{SYMBOL} snapshot last/bid/ask/close:", t.last, t.bid, t.ask, t.close)
            ib.disconnect()
            return
    except Exception as e:
        print("snapshot error:", e)

    # 3) последний бар (как у тебя получалось)
    try:
        bars = ib.reqHistoricalData(
            c, endDateTime='',
            durationStr='1 D', barSizeSetting='5 mins',
            whatToShow='TRADES', useRTH=True, formatDate=1
        )
        if bars:
            b = bars[-1]
            print(f"{SYMBOL} fallback last 5m close:", b.date, "->", b.close)
        else:
            print("no data (нет ни стрима, ни баров)")
    except Exception as e:
        print("historical error:", e)
        print("no data (нет ни стрима, ни баров)")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    # на Windows иногда нужен явный loop старта для ib_insync в одноразовых скриптах
    startLoop()
    main()
