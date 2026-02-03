# test_place_order.py
"""
Простой e2e-тест IBKRClient: создаём один bracket-ордер и отправляем его в TWS.

⚠️ Запускать ТОЛЬКО на paper-аккаунте.
Перед запуском поправь:
    - symbol
    - qty
    - уровни цен entry/stop/take
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from adapters.ibkr.client import IBKRClient, IBKRConnectionParams
from core.schemas import (
    Order,
    OrderLeg,
    OCOChildren,
    Side,
    OrderType,
    TimeInForce,
    AssetClass,
    OrderStatus,
)

# Простейшая настройка логгера, чтобы видеть, что делает IBKRClient
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def build_test_order() -> Order:
    """
    Собираем тестовый ордер:
    - лонг по акции (BUY)
    - лимитный вход
    - стоп-лосс и тейк-профит как OCO-пара
    """

    # ⚠️ ПОДРЕДАКТИРУЙ ПЕРЕД ЗАПУСКОМ:
    symbol = "AAPL"          # тикер
    qty = 1                  # количество (минимальный размер для теста)
    entry = 200.0            # цена входа (лимитка)
    stop = 190.0             # стоп-лосс
    take = 210.0             # тейк-профит

    # Родительская нога (лимитный вход)
    parent_leg = OrderLeg(
        type=OrderType.LMT,
        price=entry,
        tif=TimeInForce.DAY,
        outside_rth=False,
    )

    # Стоп-лосс
    stop_leg = OrderLeg(
        type=OrderType.STP,
        price=stop,
        tif=TimeInForce.DAY,
        outside_rth=False,
    )

    # Тейк-профит
    take_leg = OrderLeg(
        type=OrderType.LMT,
        price=take,
        tif=TimeInForce.DAY,
        outside_rth=False,
    )

    oco = OCOChildren(stop=stop_leg, take=take_leg)

    now_utc = datetime.now(timezone.utc)

    order = Order(
        order_id=f"TEST-{now_utc.isoformat()}",
        symbol=symbol,
        asset_class=AssetClass.STOCK,
        side=Side.BUY,
        qty=qty,
        parent=parent_leg,
        oco_children=oco,
        time_in_force=TimeInForce.DAY,
        created_ts_utc=now_utc,
        status=OrderStatus.NEW,
        signal_id="TEST-SIGNAL",
        approval_id=None,
    )

    return order


def main() -> None:
    # Параметры подключения — те же, что в config/app.toml (dev/paper)
    params = IBKRConnectionParams(
        host="127.0.0.1",
        port=7497,
        client_id=1,   # ⚠️ Если сервис запущен с client_id=1 одновременно, здесь можно поставить 2
    )

    client = IBKRClient(params=params)

    print("Connecting to IBKR from test_place_order.py ...")
    try:
        client.connect()
    except Exception as exc:
        print("\n❌ Failed to connect to IBKR from test_place_order.py")
        print(f"   type: {type(exc).__name__}")
        print(f"   msg : {exc}")
        return

    print("✅ Connected, building test order...")

    st_order = build_test_order()

    print(
        f"\nPlacing bracket order for {st_order.symbol}: "
        f"qty={st_order.qty}, side={st_order.side}"
    )
    print("Parent / stop / take prices:",
          st_order.parent.price,
          st_order.oco_children.stop.price,
          st_order.oco_children.take.price)

    try:
        ids = client.place_bracket_order(st_order)
    except Exception as exc:
        print("\n❌ Failed to place bracket order")
        print(f"   type: {type(exc).__name__}")
        print(f"   msg : {exc}")
        client.disconnect()
        return

    print("\n✅ Bracket order placed successfully.")
    print(f"   IB IDs: parent={ids['parent']}, take={ids['take']}, stop={ids['stop']}")

    # Покажем, что IB действительно видит открытые ордера
    try:
        open_orders = client.get_open_orders()
        print("\nOpen orders from IBKR:")
        if not open_orders:
            print("  (no open orders returned)")
        else:
            for o in open_orders:
                # ib_insync.Order имеет нормальный __repr__, можно печатать напрямую
                print("  ", o)
    except Exception as exc:
        print("\n⚠️ Could not fetch open orders")
        print(f"   type: {type(exc).__name__}")
        print(f"   msg : {exc}")

    client.disconnect()
    print("\nDisconnected from IBKR. Test finished.")


if __name__ == "__main__":
    main()
