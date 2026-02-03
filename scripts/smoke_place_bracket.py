# scripts/smoke_place_bracket.py
from adapters.ibkr.client import IBKRClient, IBConfig
from core.schemas import ParentOrder, OCOChildren, StopChild, TakeChild, Order

# поправь порт на свой рабочий (из шага 1)
cfg = IBConfig(host="127.0.0.1", port=7497, client_id=123)
cli = IBKRClient(cfg)

def main():
    cli.connect()

    core_order = Order(
        order_id="demo-order-id-001",
        symbol="AAPL",
        parent=ParentOrder(type="LIMIT", price=225.0, tif="DAY", outside_rth=False),
        oco_children=OCOChildren(
            stop=StopChild(price=220.0),
            take=TakeChild(price=230.0),
        ),
    )

    parent, take, stop = cli.place_bracket_from_core(core_order, qty=1)
    print("Placed:", parent.order.orderId, take.order.orderId, stop.order.orderId)
    cli.disconnect()

if __name__ == "__main__":
    main()
