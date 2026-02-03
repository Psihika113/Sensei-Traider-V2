# app/risk.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from core.schemas import (
    Approval,
    ApprovalReason,
    RiskSnapshot,
    Signal,
)

from core.metrics import (
    reward_and_risk_per_share,
    calc_rr,
    calc_position_size,
    calc_ev_after_costs,
)

# ==========================
#  Конфиг риска (risk_config.yaml)
# ==========================


class SlippageModel(BaseModel):
    """
    Простая модель проскальзывания.
    В v1 можем использовать только часть полей,
    остальное — задел под будущее.
    """

    tick_mult: float = Field(2.0, description="Множитель тиков для расчёта проскальзывания")
    spread_frac: float = Field(0.5, description="Доля спреда, которая теряется как проскальзывание")
    atr1m_k: float = Field(0.05, description="Множитель ATR(1m) для оценки проскальзывания")


class RiskConfig(BaseModel):
    """
    Типизированное отражение risk_config.yaml.
    """

    risk_pct_equity_cap: float = Field(..., gt=0.0)          # 0.0075 = 0.75% на сделку
    daily_loss_limit_pct: float = Field(..., gt=0.0)         # 0.02 = -2% дневной лимит
    min_rr: float = Field(..., gt=0.0)                       # 1.5 и выше
    min_p_win: float = Field(0.80, ge=0.0, le=1.0)           # порог допуска p_win

    commission_per_share: float = Field(..., ge=0.0)
    commission_min: float = Field(..., ge=0.0)

    slippage_model: SlippageModel

    outside_rth: bool = Field(False)
    exchange_tz: str = Field("America/New_York")

    equity_utilization_hard_cap: float = Field(..., ge=0.0, le=1.0)

    # Параметр "жёсткости" калибровки вероятности:
    # 1.0 = не трогаем, 0.0 = всё к 0.5.
    calibration_alpha: float = Field(0.7, ge=0.0, le=1.0)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "RiskConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(**raw)


# ==========================
#  Контекст риска для сделки
# ==========================


@dataclass
class RiskContext:
    """
    Контекст риска на момент оценки сигнала.
    Слой сервиса должен собрать это из БД и конфигов.
    """

    snapshot: RiskSnapshot          # дневное состояние риска
    config: RiskConfig              # статический risk_config

    # Доп. данные по инструменту (v1 — упрощённо):
    expected_slippage_per_share: float = 0.0   # оценка проскальзывания на 1 акцию в USD
    # В будущем сюда можно добавить: ATR, спред, tick_size и т.п.


# ==========================
#  Вспомогательные функции
# ==========================


def _calibrate_p_win(p_raw: float, cfg: RiskConfig) -> float:
    """
    Простейший калибратор: поджимает вероятности к 0.5.
    p_cal = 0.5 + alpha * (p_raw - 0.5)
    где alpha ∈ [0,1].
    """
    alpha = cfg.calibration_alpha
    p_cal = 0.5 + alpha * (p_raw - 0.5)
    # гарантируем [0,1]
    return max(0.0, min(1.0, p_cal))


# ==========================
#  Основная функция RiskGate
# ==========================


def evaluate_signal(signal: Signal, ctx: RiskContext) -> Approval:
    """
    Оценка сигнала по риск-политикам.
    Возвращает Approval с заполненными полями и reason/approved.
    """

    snap = ctx.snapshot
    cfg = ctx.config

    # ---- 0. Базовые проверки дневного лимита и kill-switch ----

    if snap.kill_switch_triggered:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.KILL_SWITCH_ENABLED,
            reason_detail="Kill-switch is active; new orders are blocked.",
            p_win_calibrated=_calibrate_p_win(signal.p_win_raw, cfg),
            ev_after_costs=0.0,
            rr=0.0,
            qty=0,
            risk_usd=0.0,
        )

    # дневная просадка относительно equity_start_day
    drawdown_pct = snap.daily_drawdown_pct
    if drawdown_pct >= snap.daily_loss_limit_pct:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.OVER_DAILY_LOSS_LIMIT,
            reason_detail=(
                f"Daily drawdown {drawdown_pct:.4f} exceeds daily loss limit "
                f"{snap.daily_loss_limit_pct:.4f}."
            ),
            p_win_calibrated=_calibrate_p_win(signal.p_win_raw, cfg),
            ev_after_costs=0.0,
            rr=0.0,
            qty=0,
            risk_usd=0.0,
        )

    # загрузка капитала
    if snap.equity_utilization >= cfg.equity_utilization_hard_cap:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.OVER_EQUITY_UTILIZATION_CAP,
            reason_detail=(
                f"Equity utilization {snap.equity_utilization:.4f} "
                f">= hard cap {cfg.equity_utilization_hard_cap:.4f}."
            ),
            p_win_calibrated=_calibrate_p_win(signal.p_win_raw, cfg),
            ev_after_costs=0.0,
            rr=0.0,
            qty=0,
            risk_usd=0.0,
        )

    # ---- 1. Калибровка вероятности и расчёт RR ----

    p_cal = _calibrate_p_win(signal.p_win_raw, cfg)

    reward_per_share, risk_per_share = reward_and_risk_per_share(
        side=signal.side,
        entry=signal.entry,
        stop=signal.stop,
        take=signal.take,
    )

    # если сигнал "сломанный" (нет RR) — сразу INVALID_SIGNAL
    if risk_per_share <= 0 or reward_per_share <= 0:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.INVALID_SIGNAL,
            reason_detail=(
                f"Non-positive reward/risk per share: reward={reward_per_share}, risk={risk_per_share}."
            ),
            p_win_calibrated=p_cal,
            ev_after_costs=0.0,
            rr=0.0,
            qty=0,
            risk_usd=0.0,
        )

    rr = calc_rr(reward_per_share, risk_per_share)

    # ---- 2. Лимиты на p_win и RR ----

    if p_cal < cfg.min_p_win:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.LOW_PROBABILITY,
            reason_detail=f"Calibrated p_win={p_cal:.4f} < min_p_win={cfg.min_p_win:.4f}.",
            p_win_calibrated=p_cal,
            ev_after_costs=0.0,
            rr=rr,
            qty=0,
            risk_usd=0.0,
        )

    if rr < cfg.min_rr:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.LOW_RR,
            reason_detail=f"RR={rr:.4f} < min_rr={cfg.min_rr:.4f}.",
            p_win_calibrated=p_cal,
            ev_after_costs=0.0,
            rr=rr,
            qty=0,
            risk_usd=0.0,
        )

    # ---- 3. Размер позиции по risk_pct (min(signal, config)) ----

    # эффективный лимит на сделку
    risk_pct_cap_eff = min(signal.risk_pct_equity_max, cfg.risk_pct_equity_cap)

    qty = calc_position_size(
        equity_current=snap.equity_current,
        risk_pct_cap_eff=risk_pct_cap_eff,
        risk_per_share=risk_per_share,
    )

    if qty <= 0:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.OVER_TRADE_RISK_CAP,
            reason_detail=(
                "Effective risk cap too small to open at least 1 share with given stop distance."
            ),
            p_win_calibrated=p_cal,
            ev_after_costs=0.0,
            rr=rr,
            qty=0,
            risk_usd=0.0,
        )

    # ---- 4. EV после комиссий и проскальзывания ----

    ev_after_costs, risk_usd = calc_ev_after_costs(
        p_win_cal=p_cal,
        reward_per_share=reward_per_share,
        risk_per_share=risk_per_share,
        qty=qty,
        commission_per_share=cfg.commission_per_share,
        commission_min=cfg.commission_min,
        slippage_per_share=ctx.expected_slippage_per_share,
    )

    if risk_usd <= 0:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.INTERNAL_ERROR,
            reason_detail="Computed risk_usd <= 0; check risk configuration.",
            p_win_calibrated=p_cal,
            ev_after_costs=0.0,
            rr=rr,
            qty=0,
            risk_usd=0.0,
        )

    if ev_after_costs <= 0:
        return Approval(
            signal_id=signal.signal_id,
            approved=False,
            reason=ApprovalReason.NEGATIVE_EV,
            reason_detail=f"EV_after_costs={ev_after_costs:.4f} <= 0.",
            p_win_calibrated=p_cal,
            ev_after_costs=ev_after_costs,
            rr=rr,
            qty=qty,
            risk_usd=risk_usd,
        )

    # ---- 5. Всё ок: допускаем сделку ----

    return Approval(
        signal_id=signal.signal_id,
        approved=True,
        reason=ApprovalReason.OK,
        reason_detail=None,
        p_win_calibrated=p_cal,
        ev_after_costs=ev_after_costs,
        rr=rr,
        qty=qty,
        risk_usd=risk_usd,
    )


# =============================================================================
# Backward-compat: старое имя функции, которое ожидает pipeline.py
# =============================================================================
def approve_signal(signal: Signal, ctx: RiskContext) -> Approval:
    return evaluate_signal(signal, ctx)
