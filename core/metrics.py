# core/metrics.py
from __future__ import annotations

import math
from typing import Tuple

from core.schemas import Side, PositionSide


# ==========================
#  RR, риск/профит на акцию
# ==========================


def reward_and_risk_per_share(
    side: Side,
    entry: float,
    stop: float,
    take: float,
) -> Tuple[float, float]:
    """
    Возвращает (reward_per_share, risk_per_share) в ценовых единицах.
    Для BUY:
        reward = take - entry
        risk   = entry - stop
    Для SELL:
        reward = entry - take
        risk   = stop - entry
    """
    if side == Side.BUY:
        reward = take - entry
        risk = entry - stop
    else:  # Side.SELL — на будущее, но сразу поддерживаем
        reward = entry - take
        risk = stop - entry

    return reward, risk


def calc_rr(reward_per_share: float, risk_per_share: float) -> float:
    """
    Простое отношение reward/risk.
    Если risk_per_share <= 0 — возвращаем 0.0.
    """
    if risk_per_share <= 0:
        return 0.0
    return reward_per_share / risk_per_share


# ==========================
#  Размер позиции
# ==========================


def calc_position_size(
    equity_current: float,
    risk_pct_cap_eff: float,
    risk_per_share: float,
) -> int:
    """
    Возвращает целочисленный размер позиции в штуках.

    equity_current      — текущий эквити (USD).
    risk_pct_cap_eff    — эффективный лимит доли equity на сделку
                          (например, min(signal.risk_pct_equity_max, cfg.risk_pct_equity_cap)).
    risk_per_share      — ценовой риск на 1 акцию (entry-stop в долларах).

    Алгоритм:
        risk_cap_usd = equity_current * risk_pct_cap_eff
        qty_float    = risk_cap_usd / risk_per_share
        qty          = floor(qty_float)
    """
    if equity_current <= 0 or risk_pct_cap_eff <= 0 or risk_per_share <= 0:
        return 0

    risk_cap_usd = equity_current * risk_pct_cap_eff
    if risk_cap_usd <= 0:
        return 0

    qty_float = risk_cap_usd / risk_per_share
    qty = math.floor(qty_float)

    return max(qty, 0)


# ==========================
#  EV после комиссий и проскальзывания
# ==========================


def calc_ev_after_costs(
    p_win_cal: float,
    reward_per_share: float,
    risk_per_share: float,
    qty: int,
    commission_per_share: float,
    commission_min: float,
    slippage_per_share: float,
) -> Tuple[float, float]:
    """
    Возвращает (ev_after_costs, risk_usd), где:

    ev_after_costs — ожидаемое значение в долях от риск-доллара (безразмерная величина).
    risk_usd       — денежный риск сделки (risk_per_share * qty + комиссии).

    Модель:
        commissions_one_side   = max(commission_min, commission_per_share * qty)
        commissions_round_trip = 2 * commissions_one_side

        EV_per_share = p_win_cal * reward
                        - (1 - p_win_cal) * risk
                        - slippage_per_share

        EV_usd   = EV_per_share * qty - commissions_round_trip
        risk_usd = risk_per_share * qty + commissions_round_trip

        ev_after_costs = EV_usd / risk_usd
    """
    if qty <= 0 or risk_per_share <= 0:
        return 0.0, 0.0

    commissions_one_side = max(commission_min, commission_per_share * qty)
    commissions_round_trip = commissions_one_side * 2.0

    ev_per_share = (
        p_win_cal * reward_per_share
        - (1.0 - p_win_cal) * risk_per_share
        - slippage_per_share
    )

    ev_usd = ev_per_share * qty - commissions_round_trip
    risk_usd = risk_per_share * qty + commissions_round_trip

    if risk_usd <= 0:
        return 0.0, 0.0

    ev_after_costs = ev_usd / risk_usd
    return ev_after_costs, risk_usd


# ==========================
#  PnL (может пригодиться позже)
# ==========================


def calc_unrealized_pnl(
    side: PositionSide,
    qty: int,
    avg_price: float,
    current_price: float,
) -> float:
    """
    Нереализованный PnL позиции.

    LONG:  (current_price - avg_price) * qty
    SHORT: (avg_price - current_price) * qty
    """
    if qty == 0:
        return 0.0

    if side == PositionSide.LONG:
        return (current_price - avg_price) * qty
    else:
        return (avg_price - current_price) * qty
