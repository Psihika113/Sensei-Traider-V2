# -*- coding: utf-8 -*-
# adapters/ibkr/client.py — IBKR adapter via ib_insync
#
# Цели:
# 1) Стабильное подключение к TWS/IBG.
# 2) Умение ставить bracket (parent + take + stop) для paper/live.
# 3) НЕ использовать OrderType.MARKET (у тебя его нет) — работаем строками "MKT"/"LMT".
# 4) Поддержать ДВА вызова:
#    A) place_bracket_order(st_order)
#    B) place_bracket_order(symbol, parent_leg, take_leg, stop_leg)
#
# Важно:
# - orderRef проставляем всем ногам одинаковый → удобно матчить fills по orderRef.
# - parentId и transmit выставляем корректно: parent transmit=False, take transmit=False, stop transmit=True.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder  # type: ignore

logger = logging.getLogger("sensei")


@dataclass(frozen=True)
class IBKRConnectionParams:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    readonly: bool = False
    connect_timeout: float = 10.0


class IBKRClient:
    """
    Тонкий клиент вокруг ib_insync.IB.
    """

    def __init__(self, params: IBKRConnectionParams) -> None:
        self.params = params
        self.ib: IB = IB()

    def connect(self) -> None:
        """
        Подключение к TWS/IBG.
        """
        if self.ib.isConnected():
            return

        self.ib.connect(
            host=self.params.host,
            port=int(self.params.port),
            clientId=int(self.params.client_id),
            timeout=float(self.params.connect_timeout),
            readonly=bool(self.params.readonly),
        )

    def ensure_connected(self) -> None:
        """Идемпотентно гарантирует подключение к TWS/IBG."""
        if not self.ib.isConnected():
            self.connect()

    @property
    def is_connected(self) -> bool:
        """True, если сейчас есть активное соединение."""
        try:
            return bool(self.ib.isConnected())
        except Exception:
            return False

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    # ----------------------------
    # Public API
    # ----------------------------
    def place_bracket_order(self, *args: Any) -> Dict[str, int]:
        """
        Возвращает {'parent': int, 'take': int, 'stop': int}
        """
        symbol, parent_leg, take_leg, stop_leg, order_ref = self._normalize_place_args(*args)

        contract = Stock(symbol, "SMART", "USD")

        # Подтверждаем контракт (полезно для стабильности conId)
        self.ib.qualifyContracts(contract)

        action, qty = self._extract_action_qty(parent_leg)

        # 1) Создаём parent и отправляем первым (чтобы получить orderId)
        parent_order = self._build_parent_order(parent_leg, action, qty, order_ref)
        parent_trade = self.ib.placeOrder(contract, parent_order)
        self.ib.sleep(0.2)  # даём IB присвоить orderId

        parent_id = int(parent_trade.order.orderId)

        # 2) Создаём детей: take + stop, оба привязаны к parent_id
        take_order = self._build_take_order(take_leg, action, qty, parent_id, order_ref)
        stop_order = self._build_stop_order(stop_leg, action, qty, parent_id, order_ref)

        # OCA группа (на всякий случай, чтобы дети взаимоисключались)
        oca_group = f"{order_ref}-OCA"
        take_order.ocaGroup = oca_group
        take_order.ocaType = 1
        stop_order.ocaGroup = oca_group
        stop_order.ocaType = 1

        take_trade = self.ib.placeOrder(contract, take_order)
        stop_trade = self.ib.placeOrder(contract, stop_order)

        self.ib.sleep(0.2)

        take_id = int(take_trade.order.orderId)
        stop_id = int(stop_trade.order.orderId)

        logger.info(
            {
                "event": "ibkr.bracket.sent",
                "symbol": symbol,
                "action": action,
                "qty": float(qty),
                "order_ref": order_ref,
                "ib_ids": {"parent": parent_id, "take": take_id, "stop": stop_id},
            }
        )

        return {"parent": parent_id, "take": take_id, "stop": stop_id}

    # ----------------------------
    # Internals
    # ----------------------------
    def _normalize_place_args(self, *args: Any) -> Tuple[str, Any, Any, Any, str]:
        """
        Возвращает: symbol, parent_leg, take_leg, stop_leg, order_ref
        """
        if len(args) == 1:
            st_order = args[0]
            symbol = getattr(st_order, "symbol", None)
            if not symbol:
                raise ValueError("st_order.symbol is required")

            parent_leg = getattr(st_order, "parent", None)
            oco = getattr(st_order, "oco_children", None) or getattr(st_order, "ocoChildren", None)
            take_leg = getattr(oco, "take", None) if oco else None
            stop_leg = getattr(oco, "stop", None) if oco else None

            if parent_leg is None or take_leg is None or stop_leg is None:
                raise ValueError("st_order must have parent + oco_children.take + oco_children.stop")

            order_ref = (
                getattr(st_order, "order_id", None)
                or getattr(st_order, "orderId", None)
                or getattr(st_order, "order_ref", None)
                or getattr(st_order, "orderRef", None)
            )
            if not order_ref:
                order_ref = f"st-{symbol}"
            return str(symbol), parent_leg, take_leg, stop_leg, str(order_ref)

        if len(args) == 4:
            symbol, parent_leg, take_leg, stop_leg = args
            order_ref = (
                getattr(parent_leg, "order_ref", None)
                or getattr(parent_leg, "orderRef", None)
                or getattr(parent_leg, "ref", None)
                or f"st-{symbol}"
            )
            return str(symbol), parent_leg, take_leg, stop_leg, str(order_ref)

        raise TypeError("place_bracket_order expects either (st_order) OR (symbol, parent_leg, take_leg, stop_leg)")

    def _extract_action_qty(self, parent_leg: Any) -> Tuple[str, float]:
        side = getattr(parent_leg, "side", None) or getattr(parent_leg, "action", None) or "BUY"
        side = str(side).upper()
        action = "BUY" if side in ("BUY", "B") else "SELL"

        qty = (
            getattr(parent_leg, "qty", None)
            or getattr(parent_leg, "quantity", None)
            or getattr(parent_leg, "q", None)
            or 1.0
        )
        return action, float(qty)

    def _norm_order_type(self, leg: Any) -> str:
        """
        Приводим тип ордера к 'MKT' или 'LMT' (и т.п.).
        """
        t = getattr(leg, "order_type", None) or getattr(leg, "type", None) or getattr(leg, "orderType", None)
        if t is None:
            return "LMT"
        v = getattr(t, "value", None)
        s = str(v if v is not None else t).upper()

        if "MKT" in s or "MARKET" in s:
            return "MKT"
        if "LMT" in s or "LIMIT" in s:
            return "LMT"
        if "STP" in s or "STOP" in s:
            return "STP"
        return s

    def _extract_tif_outside(self, leg: Any) -> Tuple[str, bool]:
        tif = getattr(leg, "time_in_force", None) or getattr(leg, "tif", None) or "DAY"
        outside = getattr(leg, "outside_rth", None)
        if outside is None:
            outside = getattr(leg, "outsideRth", None)
        return str(tif).upper(), bool(outside) if outside is not None else False

    def _build_parent_order(self, parent_leg: Any, action: str, qty: float, order_ref: str) -> Any:
        t = self._norm_order_type(parent_leg)
        tif, outside = self._extract_tif_outside(parent_leg)

        if t == "MKT":
            order = MarketOrder(action, qty)
        else:
            lp = (
                getattr(parent_leg, "limit_price", None)
                or getattr(parent_leg, "lmt_price", None)
                or getattr(parent_leg, "price", None)
                or getattr(parent_leg, "limitPrice", None)
            )
            if lp is None:
                raise ValueError("Limit parent order requires limit price")
            order = LimitOrder(action, qty, float(lp))

        order.tif = tif
        order.outsideRth = outside
        order.orderRef = order_ref

        # bracket: parent transmit=False
        order.transmit = False
        return order

    def _build_take_order(self, take_leg: Any, parent_action: str, qty: float, parent_id: int, order_ref: str) -> Any:
        tif, outside = self._extract_tif_outside(take_leg)
        exit_action = "SELL" if parent_action == "BUY" else "BUY"

        tp = (
            getattr(take_leg, "limit_price", None)
            or getattr(take_leg, "lmt_price", None)
            or getattr(take_leg, "price", None)
            or getattr(take_leg, "limitPrice", None)
        )
        if tp is None:
            raise ValueError("Take leg requires take (limit) price")

        order = LimitOrder(exit_action, qty, float(tp))
        order.tif = tif
        order.outsideRth = outside
        order.orderRef = order_ref

        order.parentId = int(parent_id)
        order.transmit = False
        return order

    def _build_stop_order(self, stop_leg: Any, parent_action: str, qty: float, parent_id: int, order_ref: str) -> Any:
        tif, outside = self._extract_tif_outside(stop_leg)
        exit_action = "SELL" if parent_action == "BUY" else "BUY"

        sp = (
            getattr(stop_leg, "stop_price", None)
            or getattr(stop_leg, "aux_price", None)
            or getattr(stop_leg, "price", None)
            or getattr(stop_leg, "auxPrice", None)
        )
        if sp is None:
            raise ValueError("Stop leg requires stop price")

        order = StopOrder(exit_action, qty, float(sp))
        order.tif = tif
        order.outsideRth = outside
        order.orderRef = order_ref

        order.parentId = int(parent_id)

        # последний ребёнок transmit=True
        order.transmit = True
        return order
