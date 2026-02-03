# test_order_db_flow.py
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_app_config
from adapters.ibkr.client import IBKRConnectionParams, IBKRClient
from core.schemas import (
    Order as STOrder,
    OrderLeg,
    OCOChildren,
    Side,
    OrderType,
    TimeInForce,
    AssetClass,
    OrderStatus,
)

APP_CFG_PATH = Path("config/app.toml")


def _get_db_path_from_config():
    """
    Универсальный способ вытащить путь к БД из AppConfig.

    Пытаемся по очереди:
    - cfg.db_path
    - cfg.db.path
    - cfg.db
    - cfg.database_path
    """
    cfg = load_app_config(APP_CFG_PATH)

    db_path = None

    # 1) Прямое поле db_path
    if hasattr(cfg, "db_path"):
        db_path = getattr(cfg, "db_path")

    # 2) Поле db (как в текущей структуре)
    elif hasattr(cfg, "db"):
        db_obj = getattr(cfg, "db")
        if hasattr(db_obj, "path"):
            db_path = db_obj.path
        else:
            db_path = db_obj

    # 3) Альтернативное имя
    elif hasattr(cfg, "database_path"):
        db_path = getattr(cfg, "database_path")

    if db_path is None:
        raise RuntimeError(
            f"AppConfig has no db path attribute. Available attrs: {dir(cfg)}"
        )

    return str(db_path), cfg


def main() -> None:
    # === STEP 1: CONFIG / DB ===
    print("=== STEP 1: CONFIG / DB ===")
    db_path, cfg = _get_db_path_from_config()
    print(f"DB path from config: {db_path}")

    # Подключаемся к SQLite
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # === STEP 2: BUILD STOrder ===
    print("\n=== STEP 2: BUILD STOrder ===")

    now_utc = datetime.now(timezone.utc)

    signal_id = "test-signal-db-flow"
    order_id = f"test-{uuid.uuid4()}"

    symbol = "AAPL"
    qty = 1

    entry_price = 200.0
    stop_price = 190.0
    take_price = 210.0

    print(f"Building STOrder for {symbol}: qty={qty}")
    print(f"Prices: entry={entry_price}, stop={stop_price}, take={take_price}")

    parent_leg = OrderLeg(
        type=OrderType.LMT,
        price=entry_price,
        tif=TimeInForce.DAY,
        outside_rth=False,
    )
    stop_leg = OrderLeg(
        type=OrderType.STP,
        price=stop_price,
        tif=TimeInForce.DAY,
        outside_rth=False,
    )
    take_leg = OrderLeg(
        type=OrderType.LMT,
        price=take_price,
        tif=TimeInForce.DAY,
        outside_rth=False,
    )

    oco = OCOChildren(stop=stop_leg, take=take_leg)

    st_order = STOrder(
        order_id=order_id,
        symbol=symbol,
        asset_class=AssetClass.STOCK,
        side=Side.BUY,
        qty=qty,
        parent=parent_leg,
        oco_children=oco,
        time_in_force=TimeInForce.DAY,
        created_ts_utc=now_utc,
        status=OrderStatus.NEW,
        signal_id=signal_id,
        approval_id=None,
    )

    print(f"STOrder created with order_id={st_order.order_id}")

    # === STEP 3: INSERT INTO DB (orders) ===
    print("\n=== STEP 3: INSERT INTO DB (orders) ===")

    cur.execute(
        """
        INSERT INTO orders (
            order_id,
            symbol,
            side,
            qty,
            status,
            reason,
            created_ts_utc,
            entry_price,
            stop_price,
            take_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            st_order.order_id,
            st_order.symbol,
            st_order.side.value,
            st_order.qty,
            "NEW",
            "TEST_DB_FLOW",
            st_order.created_ts_utc.isoformat(),
            entry_price,
            stop_price,
            take_price,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    print(f"Inserted row into orders with id={row_id}")

    # === STEP 4: CONNECT IBKR & PLACE BRACKET ===
    print("\n=== STEP 4: CONNECT IBKR & PLACE BRACKET ===")

    ib_cfg = cfg.ibkr
    params = IBKRConnectionParams(
        host=str(ib_cfg.host),
        port=int(ib_cfg.port),
        client_id=int(ib_cfg.client_id),
        connect_timeout=10.0,
    )

    client = IBKRClient(params)
    print(
        f"Connecting to IBKR: host={params.host}, port={params.port}, client_id={params.client_id}"
    )
    client.connect()
    print("IBKR connected.")

    try:
        print(f"\nPlacing bracket order for {st_order.symbol} from DB-flow script...")
        ib_ids = client.place_bracket_order(st_order)
        print("Bracket order placed.")
        print(f"IB IDs: parent={ib_ids['parent']}, take={ib_ids['take']}, stop={ib_ids['stop']}")

        # === STEP 5: UPDATE DB ROW WITH IB IDS ===
        print("\n=== STEP 5: UPDATE DB ROW WITH IB IDS ===")

        cur = conn.cursor()
        cur.execute(
            """
            UPDATE orders
            SET status = ?,
                ib_parent = ?,
                ib_take = ?,
                ib_stop = ?,
                reason = ?
            WHERE id = ?
            """,
            (
                "SUBMITTED",
                ib_ids["parent"],
                ib_ids["take"],
                ib_ids["stop"],
                "TEST_DB_FLOW",
                row_id,
            ),
        )
        conn.commit()

        # Читаем и показываем строку после обновления
        cur.execute("SELECT * FROM orders WHERE id = ?", (row_id,))
        row = cur.fetchone()
        print(f"Updated DB row id={row_id}:")
        for key in row.keys():
            print(f"  {key}: {row[key]}")

    finally:
        print("\nDisconnecting from IBKR...")
        client.disconnect()
        print("Disconnected.")
        conn.close()
        print("DB connection closed.")

    print("\n=== DONE: test_order_db_flow finished ===")


if __name__ == "__main__":
    main()
