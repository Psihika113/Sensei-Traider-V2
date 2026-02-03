# -*- coding: utf-8 -*-
# app/executor.py — OrderManager: OFFLINE + IBKR (paper/live)
#
# Правило:
#   - если ib_client None ИЛИ mode == "offline" → только пишем в БД + offline execution
#   - если есть ib_client → пробуем отправить bracket в IBKR
#
# Важно:
#   - поддерживаем ДВА варианта сигнатуры place_bracket_order:
#       A) place_bracket_order(st_order)
#       B) place_bracket_order(symbol, parent_leg, take_leg, stop_leg)
#   - идемпотентность:
#       1) если signal_id уже есть в БД → НЕ шлём в брокер и не создаём новый ордер
#       2) если order_id уже есть в БД → НЕ шлём в брокер повторно
#
# Требование схемы БД (поддерживается деградация):
#   - orders.signal_id (TEXT, nullable) — если есть, используем как основной ключ идемпотентности
#   - orders.order_ref (TEXT, nullable) — резерв/совместимость
#
# Поведение order_ref:
#   - для стабильности привязки используем order_ref = signal.signal_id (если доступно)

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from app.db import Database
from core.schemas import (
    Approval,
    EntryType,
    OCOChildren,
    Order as STOrder,
    OrderLeg,
    OrderStatus,
    OrderType,
    RiskSnapshot,
    Signal,
)

logger = logging.getLogger("sensei")


@dataclass
class PlacementResult:
    status: str  # "OK" | "DUPLICATE" | "ERROR"
    order_id: str
    reason: str = ""
    ib_parent: Optional[int] = None
    ib_take: Optional[int] = None
    ib_stop: Optional[int] = None


@dataclass
class OrderPlacementResult:
    order: STOrder
    ib_order_ids: Optional[Dict[str, int]] = None
    status: str = "OK"  # "OK" | "DUPLICATE"


class OrderManager:
    def __init__(
        self,
        db: Database,
        ib_client: object | None,
        risk_config: object,
        mode: str | None = None,
    ) -> None:
        self.db = db
        self.ib_client = ib_client
        self.risk_config = risk_config
        self.mode = mode or "offline"

        # кеш схемы
        self._orders_cols_cache: Optional[set[str]] = None

    # --------------------------
    # PUBLIC
    # --------------------------
    def submit_approved_trade(
        self,
        *,
        signal: Signal,
        approval: Approval,
        snapshot: RiskSnapshot | None = None,
    ) -> Optional[OrderPlacementResult]:
        """
        Создаём детерминированный order_id, пишем orders,
        и в зависимости от режима:
          - offline: пишем виртуальное исполнение
          - paper/live: отправляем bracket в IBKR
        """
        now_utc = dt.datetime.now(dt.timezone.utc)

        # Основной ключ идемпотентности — signal_id
        signal_id = getattr(signal, "signal_id", None)
        order_ref = signal_id  # стабильно и прозрачно

        # 1) Идемпотентность по сигналу: если signal_id уже есть — это DUPLICATE
        if signal_id:
            existing = self._fetch_existing_order_id_by_signal(signal_id=signal_id)
            if existing:
                logger.info(
                    {
                        "event": "ordermanager.duplicate_order_skip_broker",
                        "order_id": existing,
                        "signal_id": signal_id,
                        "symbol": signal.symbol,
                        "by": "signal_id",
                    }
                )
                st_order = self._build_st_order(
                    order_id=existing,
                    signal=signal,
                    approval=approval,
                    now_utc=now_utc,
                )
                return OrderPlacementResult(order=st_order, ib_order_ids=None, status="DUPLICATE")

        # 2) Детерминированный order_id
        order_id = self._make_order_id(signal)

        # 3) Вторичная защита: если order_id уже в БД — DUPLICATE
        existing_by_id = self.db.fetch_one(
            "SELECT order_id FROM orders WHERE order_id = ? LIMIT 1",
            (order_id,),
        )
        if existing_by_id:
            logger.info(
                {
                    "event": "ordermanager.duplicate_order_skip_broker",
                    "order_id": order_id,
                    "signal_id": getattr(signal, "signal_id", None),
                    "symbol": signal.symbol,
                    "by": "order_id",
                }
            )
            st_order = self._build_st_order(
                order_id=order_id,
                signal=signal,
                approval=approval,
                now_utc=now_utc,
            )
            return OrderPlacementResult(order=st_order, ib_order_ids=None, status="DUPLICATE")

        st_order = self._build_st_order(
            order_id=order_id,
            signal=signal,
            approval=approval,
            now_utc=now_utc,
        )

        # Пишем в orders (включая signal_id и order_ref, если колонки существуют)
        self._insert_order_row(
            order=st_order,
            approval=approval,
            snapshot=snapshot,
            order_ref=order_ref,
            signal_id=signal_id,
        )

        # OFFLINE: виртуальное исполнение
        if self.mode == "offline" or self.ib_client is None:
            self._offline_fill(order=st_order)
            return OrderPlacementResult(order=st_order, ib_order_ids=None, status="OK")

        # PAPER/LIVE: отправка в IBKR
        try:
            # Вариант A: брокерный адаптер принимает st_order целиком
            return_ids = self.ib_client.place_bracket_order(st_order)  # type: ignore[attr-defined]
        except Exception as e:
            msg = str(e)

            # Вариант B: сигнатура (symbol, parent, take, stop)
            if isinstance(e, TypeError) or "positional call expects" in msg or "expects: (symbol, parent, take, stop)" in msg:
                try:
                    return_ids = self.ib_client.place_bracket_order(  # type: ignore[attr-defined]
                        st_order.symbol,
                        st_order.parent,
                        st_order.oco_children.take,
                        st_order.oco_children.stop,
                    )
                except Exception as e2:
                    logger.error(
                        {
                            "event": "ordermanager.ibkr_submit_failed",
                            "order_id": st_order.order_id,
                            "err": str(e2),
                        }
                    )
                    return None
            else:
                logger.error(
                    {
                        "event": "ordermanager.ibkr_submit_failed",
                        "order_id": st_order.order_id,
                        "err": msg,
                    }
                )
                return None

        # Нормализуем return_ids
        ib_ids: Dict[str, int] = {}
        if isinstance(return_ids, dict):
            try:
                ib_ids = {str(k): int(v) for k, v in return_ids.items()}
            except Exception:
                ib_ids = {}
        elif isinstance(return_ids, (tuple, list)) and len(return_ids) >= 3:
            try:
                ib_ids = {"parent": int(return_ids[0]), "take": int(return_ids[1]), "stop": int(return_ids[2])}
            except Exception:
                ib_ids = {}

        if ib_ids:
            self._try_update_order_broker_ids(order_id=st_order.order_id, ib_ids=ib_ids)

        self._try_update_order_status(order_id=st_order.order_id, status=OrderStatus.SUBMITTED.value)

        logger.info(
            {
                "event": "ordermanager.ibkr_bracket_submitted",
                "order_id": st_order.order_id,
                "symbol": st_order.symbol,
                "ib_ids": ib_ids,
            }
        )
        return OrderPlacementResult(order=st_order, ib_order_ids=ib_ids, status="OK")

    # --------------------------
    # INTERNAL: idempotency helpers
    # --------------------------
    def _orders_columns(self) -> set[str]:
        if self._orders_cols_cache is not None:
            return self._orders_cols_cache

        cols: set[str] = set()
        try:
            rows = self.db.fetch_all("PRAGMA table_info(orders)", ())
            for r in rows:
                # r может быть dict/Row/tuple
                if isinstance(r, dict):
                    cols.add(str(r.get("name")))
                elif hasattr(r, "__getitem__"):
                    # PRAGMA: (cid, name, type, notnull, dflt_value, pk)
                    cols.add(str(r[1]))
        except Exception:
            cols = set()

        self._orders_cols_cache = cols
        return cols

    def _fetch_existing_order_id_by_signal(self, *, signal_id: str) -> Optional[str]:
        cols = self._orders_columns()

        # основной путь: orders.signal_id
        if "signal_id" in cols:
            row = self.db.fetch_one("SELECT order_id FROM orders WHERE signal_id = ? LIMIT 1", (signal_id,))
            oid = self._extract_first_value(row, key="order_id")
            if oid:
                return str(oid)

        # резерв: orders.order_ref
        if "order_ref" in cols:
            row = self.db.fetch_one("SELECT order_id FROM orders WHERE order_ref = ? LIMIT 1", (signal_id,))
            oid = self._extract_first_value(row, key="order_id")
            if oid:
                return str(oid)

        return None

    @staticmethod
    def _extract_first_value(row: object, *, key: str) -> Optional[object]:
        if row is None:
            return None
        try:
            if isinstance(row, dict):
                return row.get(key)
            if hasattr(row, "keys") and key in row.keys():  # sqlite3.Row
                return row[key]
        except Exception:
            pass
        try:
            # fallback на первый элемент
            if hasattr(row, "__getitem__"):
                return row[0]
        except Exception:
            return None
        return None

    # --------------------------
    # INTERNAL: order build
    # --------------------------
    def _make_order_id(self, signal: Signal) -> str:
        base = (
            f"{signal.signal_id}|{signal.symbol}|{signal.ts_utc.isoformat()}|{signal.side}|"
            f"{getattr(signal, 'entry_type', None)}|{signal.entry}|{signal.stop}|{signal.take}"
        )
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]
        return f"sensei-{digest}"

    def _build_st_order(
        self,
        *,
        order_id: str,
        signal: Signal,
        approval: Approval,
        now_utc: datetime,
    ) -> STOrder:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=dt.timezone.utc)

        qty = int(getattr(approval, "qty", 0))
        et = getattr(signal, "entry_type", None)

        if et == EntryType.MARKET:
            parent_type = OrderType.MKT
            parent_price = None
        elif et == EntryType.LIMIT:
            parent_type = OrderType.LMT
            parent_price = float(signal.entry)
        elif et == EntryType.STOP:
            parent_type = OrderType.STP
            parent_price = float(signal.entry)
        elif et == EntryType.STOP_LIMIT:
            # деградация в STP
            logger.warning(
                {
                    "event": "executor.stop_limit_degraded_to_stp",
                    "signal_id": getattr(signal, "signal_id", None),
                    "symbol": signal.symbol,
                }
            )
            parent_type = OrderType.STP
            parent_price = float(signal.entry)
        else:
            parent_type = OrderType.MKT
            parent_price = None

        outside_rth_flag = os.getenv("SENSEI_OUTSIDE_RTH", "").strip() == "1"

        parent_leg = OrderLeg(
            type=parent_type,
            price=parent_price,
            tif=signal.time_in_force,
            outside_rth=outside_rth_flag,
        )
        stop_leg = OrderLeg(
            type=OrderType.STP,
            price=float(signal.stop),
            tif=signal.time_in_force,
            outside_rth=outside_rth_flag,
        )
        take_leg = OrderLeg(
            type=OrderType.LMT,
            price=float(signal.take),
            tif=signal.time_in_force,
            outside_rth=outside_rth_flag,
        )

        children = OCOChildren(stop=stop_leg, take=take_leg)

        return STOrder(
            order_id=order_id,
            symbol=signal.symbol,
            asset_class=signal.asset_class,
            side=signal.side,
            qty=qty,
            parent=parent_leg,
            oco_children=children,
            time_in_force=signal.time_in_force,
            created_ts_utc=now_utc,
            status=OrderStatus.NEW,
            signal_id=getattr(signal, "signal_id", None),
            approval_id=None,
        )

    # --------------------------
    # INTERNAL: DB writes
    # --------------------------
    def _try_update_order_broker_ids(self, *, order_id: str, ib_ids: Dict[str, int]) -> None:
        sql = """
        UPDATE orders
           SET ib_parent = ?, ib_take = ?, ib_stop = ?
         WHERE order_id = ?
        """
        params = (
            int(ib_ids.get("parent")) if ib_ids.get("parent") is not None else None,
            int(ib_ids.get("take")) if ib_ids.get("take") is not None else None,
            int(ib_ids.get("stop")) if ib_ids.get("stop") is not None else None,
            order_id,
        )
        try:
            self.db.execute(sql, params)
        except Exception as e:
            msg = str(e)
            if "no such column: ib_parent" in msg or "no column named ib_parent" in msg:
                logger.info({"event": "orders.schema_no_ib_columns", "order_id": order_id})
                return
            logger.error({"event": "orders.update_ib_ids_failed", "order_id": order_id, "err": msg})

    def _try_update_order_status(self, *, order_id: str, status: str) -> None:
        try:
            self.db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))
        except Exception as e:
            logger.error({"event": "orders.update_status_failed", "order_id": order_id, "err": str(e)})

    def _insert_order_row(
        self,
        *,
        order: STOrder,
        approval: Approval,
        snapshot: RiskSnapshot | None,
        order_ref: Optional[str],
        signal_id: Optional[str],
    ) -> None:
        cols = self._orders_columns()

        # Базовый набор
        insert_cols = ["order_id", "symbol", "side", "qty", "status", "reason", "created_ts"]
        insert_vals = [
            order.order_id,
            order.symbol,
            order.side.value if hasattr(order.side, "value") else str(order.side),
            int(order.qty),
            order.status.value if hasattr(order.status, "value") else str(order.status),
            getattr(approval, "reason", "OK"),
            order.created_ts_utc.isoformat(),
        ]

        # Доп. поля, если есть в схеме
        if "order_ref" in cols:
            insert_cols.append("order_ref")
            insert_vals.append(order_ref)

        if "signal_id" in cols:
            insert_cols.append("signal_id")
            insert_vals.append(signal_id)

        cols_sql = ",".join(insert_cols)
        qmarks_sql = ",".join(["?"] * len(insert_cols))

        sql = f"INSERT INTO orders({cols_sql}) VALUES({qmarks_sql})"
        self.db.execute(sql, tuple(insert_vals))

    def _offline_fill(self, *, order: STOrder) -> None:
        """
        OFFLINE: пишем виртуальное исполнение (для тестов).
        PAPER/LIVE не должны писать фейковые fills.
        """
        try:
            self.db.execute(
                """
                INSERT INTO executions(order_id, leg, ts_utc, price, qty, fee)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    "PARENT",
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                    0.0,
                    float(order.qty),
                    0.0,
                ),
            )
        except Exception as e:
            logger.error({"event": "executor.offline_fill_failed", "order_id": order.order_id, "err": str(e)})
