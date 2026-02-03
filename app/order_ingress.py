# app/order_ingress.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from app.config import load_app_config


APP_CFG_PATH = Path("config/app.toml")


def _get_db_path_from_config() -> str:
    """
    Универсально достаём путь к БД из AppConfig.
    Логика такая же, как в test_order_db_flow.py.
    """
    cfg = load_app_config(APP_CFG_PATH)

    db_path = None

    if hasattr(cfg, "db_path"):
        db_path = getattr(cfg, "db_path")
    elif hasattr(cfg, "db"):
        db_obj = getattr(cfg, "db")
        if hasattr(db_obj, "path"):
            db_path = db_obj.path
        else:
            db_path = db_obj
    elif hasattr(cfg, "database_path"):
        db_path = getattr(cfg, "database_path")

    if db_path is None:
        raise RuntimeError(
            f"AppConfig has no db path attribute. Available attrs: {dir(cfg)}"
        )

    return str(db_path)


@dataclass
class SenseiOrderRequest:
    """
    То, что будет выдавать Sensei (или любой внешний агент)
    для постановки ОДНОГО брекет-ордера в очередь.

    Это намеренно простой формат: symbol / side / qty / цены.
    """
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int

    entry_price: float
    stop_price: float
    take_price: float

    reason: str = "SENSEI"
    # Можно будет расширить (signal_id, стратегия и т.п.)

    def normalize(self) -> None:
        """Лёгкая нормализация: символ в upper, reason триммим."""
        self.symbol = self.symbol.strip().upper()
        self.reason = self.reason.strip() or "SENSEI"

    def validate(self) -> None:
        """
        Базовая валидация — без фанатизма, но убираем откровенный мусор.
        """
        if not self.symbol:
            raise ValueError("symbol must be non-empty")

        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side!r}")

        if self.qty <= 0:
            raise ValueError(f"qty must be > 0, got {self.qty}")

        # Простейшая логика цен:
        # для BUY: stop < entry < take
        # для SELL (шорт): stop > entry > take
        if self.side == "BUY":
            if not (self.stop_price < self.entry_price < self.take_price):
                raise ValueError(
                    f"for BUY expected stop < entry < take, got "
                    f"stop={self.stop_price}, entry={self.entry_price}, take={self.take_price}"
                )
        else:  # SELL
            if not (self.stop_price > self.entry_price > self.take_price):
                raise ValueError(
                    f"for SELL expected stop > entry > take, got "
                    f"stop={self.stop_price}, entry={self.entry_price}, take={self.take_price}"
                )


def insert_sensei_order(
    req: SenseiOrderRequest,
    *,
    created_ts_utc: Optional[datetime] = None,
) -> int:
    """
    Принимает SenseiOrderRequest, валидирует и
    вставляет строку в таблицу orders со статусом NEW.

    Возвращает id вставленной строки (PRIMARY KEY).
    """
    req.normalize()
    req.validate()

    if created_ts_utc is None:
        created_ts_utc = datetime.now(timezone.utc)

    db_path = _get_db_path_from_config()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Минимальный набор полей + наши новые цены
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
            # order_id делаем понятным, но уникальным
            f"sensei-{int(created_ts_utc.timestamp())}",
            req.symbol,
            req.side,
            req.qty,
            "NEW",               # ключевой момент: очередь на исполнение
            req.reason,
            created_ts_utc.isoformat(),
            req.entry_price,
            req.stop_price,
            req.take_price,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()

    return row_id


def main_demo() -> None:
    """
    Демонстрационный запуск из командной строки:
    создаёт один NEW-ордер в БД.
    """
    print("=== SENSEI INGRESS DEMO ===")
    sample = SenseiOrderRequest(
        symbol="AAPL",
        side="BUY",
        qty=1,
        entry_price=200.0,
        stop_price=190.0,
        take_price=210.0,
        reason="SENSEI_DEMO",
    )

    row_id = insert_sensei_order(sample)
    print(f"Inserted NEW order into 'orders' with id={row_id}")


if __name__ == "__main__":
    main_demo()
