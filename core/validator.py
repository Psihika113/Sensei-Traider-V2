# core/validator.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from core.schemas import (
    Approval,
    Order,
    OrderLeg,
    Signal,
    Side,
    AssetClass,
    TimeInForce,
    OrderType,
)


# ==========================
#  Исключения валидации
# ==========================


class ValidationError(Exception):
    """Базовая ошибка доменной валидации (не путать с Pydantic)."""

    pass


class SignalValidationError(ValidationError):
    """Ошибка валидации торгового сигнала."""

    pass


class ApprovalValidationError(ValidationError):
    """Ошибка валидации approval."""

    pass


class OrderValidationError(ValidationError):
    """Ошибка валидации ордера."""

    pass


# ==========================
#  Валидация Signal
# ==========================


def validate_signal_basic(
    signal: Signal,
    *,
    allow_short: bool = False,
    allowed_asset_classes: Optional[Iterable[AssetClass]] = None,
    now_utc: Optional[datetime] = None,
    max_age_minutes: Optional[int] = 60,
) -> None:
    """
    Базовая доменная проверка сигнала поверх Pydantic-валидаторов.

    Проверяем:
    - long-only (если allow_short=False),
    - asset_class ∈ разрешённых (если задан),
    - сигнал не слишком старый (max_age_minutes),
    - разумные TIF для v1.
    """

    # --- long-only v1 ---
    if not allow_short and signal.side != Side.BUY:
        raise SignalValidationError(
            f"Short/SELL signals are not allowed in v1 (side={signal.side})."
        )

    # --- asset_class ---
    if allowed_asset_classes is not None:
        allowed_set = {ac for ac in allowed_asset_classes}
        if signal.asset_class not in allowed_set:
            raise SignalValidationError(
                f"Asset class {signal.asset_class} is not allowed in v1."
            )

    # --- возраст сигнала ---
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    if signal.ts_utc.tzinfo is None:
        # считаем, что ts_utc уже в UTC
        ts = signal.ts_utc.replace(tzinfo=timezone.utc)
    else:
        ts = signal.ts_utc.astimezone(timezone.utc)

    if max_age_minutes is not None:
        age = now_utc - ts
        if age > timedelta(minutes=max_age_minutes):
            raise SignalValidationError(
                f"Signal is too old: age {age.total_seconds()/60:.1f} min "
                f"(max {max_age_minutes} min)."
            )

    # --- TIF (в v1 допускаем только DAY/GTC) ---
    if signal.time_in_force not in {TimeInForce.DAY, TimeInForce.GTC}:
        raise SignalValidationError(
            f"time_in_force={signal.time_in_force} is not allowed for v1."
        )

    # Дополнительные sanity-check-и цен уже сделаны в Pydantic (stop/entry/take > 0 и правильный порядок),
    # поэтому здесь можно не дублировать.


# ==========================
#  Валидация Approval
# ==========================


def validate_approval_vs_signal(approval: Approval, signal: Signal) -> None:
    """
    Проверка согласованности approval и signal:
    - один и тот же signal_id;
    - qty > 0 при approved=True;
    - risk_usd > 0 при approved=True;
    - p_win_calibrated, rr, ev_after_costs в разумных пределах.
    """

    if approval.signal_id != signal.signal_id:
        raise ApprovalValidationError(
            f"Approval.signal_id={approval.signal_id} does not match Signal.signal_id={signal.signal_id}."
        )

    if approval.approved:
        if approval.qty <= 0:
            raise ApprovalValidationError("Approved trade must have qty > 0.")
        if approval.risk_usd <= 0:
            raise ApprovalValidationError("Approved trade must have risk_usd > 0.")
        if not (0.0 <= approval.p_win_calibrated <= 1.0):
            raise ApprovalValidationError(
                f"p_win_calibrated={approval.p_win_calibrated} is outside [0,1]."
            )
        if approval.rr <= 0:
            raise ApprovalValidationError(f"rr={approval.rr} must be > 0 for approved trade.")
    else:
        # При reject тоже желательно иметь валидные метрики, но
        # не будем слишком жёстко ограничивать.
        if not (0.0 <= approval.p_win_calibrated <= 1.0):
            raise ApprovalValidationError(
                f"p_win_calibrated={approval.p_win_calibrated} is outside [0,1] (even for rejected trade)."
            )


# ==========================
#  Валидация Order относительно Signal/Approval
# ==========================


def _validate_order_leg_price(leg: OrderLeg, name: str) -> None:
    """
    Базовая проверка цен/типов для ноги ордера.
    """
    if leg.type in {OrderType.LMT, OrderType.STP, OrderType.STP_LMT}:
        if leg.price is None or leg.price <= 0:
            raise OrderValidationError(
                f"{name} leg of order must have positive price for type={leg.type}."
            )


def validate_order_basic(order: Order) -> None:
    """
    Самостоятельная проверка ордера (без привязки к сигналу).
    Смотрим на:
    - корректность типов/цен ног,
    - TIF (по возможности DAY/GTC),
    - наличие OCO-детей.
    """

    if order.parent is None or order.oco_children is None:
        raise OrderValidationError("Order must have parent and OCO children (stop & take).")

    # Проверяем цены для ног
    _validate_order_leg_price(order.parent, "parent")
    _validate_order_leg_price(order.oco_children.stop, "stop child")
    _validate_order_leg_price(order.oco_children.take, "take child")

    # TIF — допускаем пустое или DAY/GTC
    for leg, name in (
        (order.parent, "parent"),
        (order.oco_children.stop, "stop child"),
        (order.oco_children.take, "take child"),
    ):
        if leg.tif is not None and leg.tif not in {TimeInForce.DAY, TimeInForce.GTC}:
            raise OrderValidationError(
                f"{name} leg has unsupported TIF={leg.tif} for v1."
            )


def validate_order_vs_signal(order: Order, signal: Signal) -> None:
    """
    Проверка, что Order соответствует Signal:
    - symbol и side совпадают,
    - TIF совместим,
    - цены ног согласованы с entry/stop/take сигнала.
    """

    if order.signal_id != signal.signal_id:
        raise OrderValidationError(
            f"Order.signal_id={order.signal_id} does not match Signal.signal_id={signal.signal_id}."
        )

    if order.symbol.upper() != signal.symbol.upper():
        raise OrderValidationError(
            f"Order.symbol={order.symbol} does not match Signal.symbol={signal.symbol}."
        )

    if order.side != signal.side:
        raise OrderValidationError(
            f"Order.side={order.side} does not match Signal.side={signal.side}."
        )

    # TIF — желательно совпадение с сигналом (если задан)
    if order.time_in_force != signal.time_in_force:
        raise OrderValidationError(
            f"Order.time_in_force={order.time_in_force} "
            f"does not match Signal.time_in_force={signal.time_in_force}."
        )

    # цены: допускаем небольшие отклонения (из-за округления)
    # но в целом parent.price ≈ entry, stop/take legs ≈ stop/take сигнала.
    tol = 1e-6

    def _close(a: Optional[float], b: Optional[float]) -> bool:
        if a is None or b is None:
            return True  # если не задано, не валим, дальше обработает Executor/Adapter
        return abs(a - b) <= tol * max(1.0, abs(b))

    if not _close(order.parent.price, signal.entry):
        raise OrderValidationError(
            f"Parent leg price {order.parent.price} does not match Signal.entry={signal.entry} (tol={tol})."
        )

    if not _close(order.oco_children.stop.price, signal.stop):
        raise OrderValidationError(
            f"Stop leg price {order.oco_children.stop.price} does not match Signal.stop={signal.stop}."
        )

    if not _close(order.oco_children.take.price, signal.take):
        raise OrderValidationError(
            f"Take leg price {order.oco_children.take.price} does not match Signal.take={signal.take}."
        )
