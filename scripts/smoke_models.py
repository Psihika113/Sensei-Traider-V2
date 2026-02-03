from datetime import datetime, timezone
from core.schemas import Signal, ParentOrder, OCOChildren, StopChild, TakeChild, Order, make_order_id

sig = Signal(
    signal_id="018f2b59-1f3a-7e37-9d5e-6a563fda7b10",
    ts_utc=datetime.now(timezone.utc),
    symbol="NVDA",
    entry_type="limit",
    entry=123.45,
    stop=120.0,
    take=130.0,
    p_win_raw=0.86,
    risk_pct_equity_max=0.0075,
)
oid = make_order_id(sig.signal_id, sig.symbol, sig.ts_utc)
ordr = Order(
    order_id=oid,
    symbol=sig.symbol,
    parent=ParentOrder(type="LIMIT", price=sig.entry, tif="DAY", outside_rth=False),
    oco_children=OCOChildren(stop=StopChild(price=sig.stop), take=TakeChild(price=sig.take)),
)
print("OK:", ordr.order_id[:12])
