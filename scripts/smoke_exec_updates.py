# scripts/smoke_exec_updates.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

from app.executor import ExecutorDB, Executor
from core.schemas import ParentOrder, OCOChildren, StopChild, TakeChild, Order


DB = Path("data/trader.db")


def iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    db = ExecutorDB(DB)
    ex = Executor(db, ib_client=None, dry_run=True)  # локальный прогон без IBKR

    # Создаём CoreOrder (как его даёт risk/assistant → executor)
    core_order = Order(
        order_id=f"demo-upd-{int(time.time())}",
        symbol="AAPL",
        parent=ParentOrder(type="LIMIT", price=225.0, tif="DAY", outside_rth=False),
        oco_children=OCOChildren(
            stop=StopChild(price=220.0),
            take=TakeChild(price=230.0),
        ),
    )

    # 1) Идемпотентная публикация
    r = ex.place_bracket(core_order, qty=2)
    print("submit:", r)

    # 2) «Пришли» статусы от брокера
    ex.on_order_status(
        core_order.order_id, status="Submitted", avg_fill_price=0.0, filled=0.0, remaining=2.0
    )

    # 3) Частичные исполнения родителя
    ex.on_execution(
        core_order.order_id, leg="parent", ts_utc=iso_utc(), price=225.10, qty=1, fee=0.35
    )
    ex.on_order_status(
        core_order.order_id, status="Submitted", avg_fill_price=225.10, filled=1.0, remaining=1.0
    )

    ex.on_execution(
        core_order.order_id, leg="parent", ts_utc=iso_utc(), price=225.05, qty=1, fee=0.35
    )
    ex.on_order_status(
        core_order.order_id, status="Filled", avg_fill_price=225.075, filled=2.0, remaining=0.0
    )

    # 4) Закрытие по тейку (пример)
    ex.on_execution(
        core_order.order_id, leg="take", ts_utc=iso_utc(), price=230.00, qty=2, fee=0.35
    )

    print("OK: updates written (orders/executions updated)")


if __name__ == "__main__":
    main()
