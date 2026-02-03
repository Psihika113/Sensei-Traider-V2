# run_sensei_link.py
from ib_insync import IB, Stock

IB.RequestTimeout = 30

def on_connected():
    print('✅ connected')

def on_disconnected():
    print('⚠️ disconnected')

def connect_ib(paper: bool = True, client_id: int = 321) -> IB:
    host = '127.0.0.1'
    port = 7497 if paper else 7496

    ib = IB()
    # подписки на события
    ib.connectedEvent += on_connected
    ib.disconnectedEvent += on_disconnected

    ib.connect(host, port, clientId=client_id, timeout=30)
    return ib

if __name__ == '__main__':
    ib = connect_ib(paper=True, client_id=321)
    print('ServerTime:', ib.reqCurrentTime())

    # Если нет живой подписки на маркет-дату — используем delayed
    ib.reqMarketDataType(3)  # 1=live, 2=frozen, 3=delayed, 4=delayed frozen

    aapl = Stock('AAPL', 'SMART', 'USD')
    ib.qualifyContracts(aapl)
    t = ib.reqMktData(aapl, '', False, False)
    ib.sleep(2.0)  # подождать прихода тиков
    print('AAPL last/bid/ask:', t.last, t.bid, t.ask)

    ib.disconnect()
