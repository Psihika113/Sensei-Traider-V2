# app/pipeline.py
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.db import Database
from app.risk import RiskConfig, RiskContext, evaluate_signal
from app.executor import OrderManager, OrderPlacementResult
from core.schemas import Signal, Approval, RiskSnapshot
from core.validator import validate_signal_basic, SignalValidationError

logger = logging.getLogger(__name__)


@dataclass
class ProcessSignalResult:
    signal: Signal
    approval: Approval
    placement: Optional[OrderPlacementResult]


class TradePipeline:
    def __init__(self, db: Database, risk_config: RiskConfig, order_manager: OrderManager) -> None:
        self._db = db
        self._risk_cfg = risk_config
        self._order_manager = order_manager

    def _submit_approved_trade_compat(
        self,
        *,
        signal: Signal,
        approval: Approval,
        snapshot: RiskSnapshot,
        now_utc: datetime,
    ) -> Optional[OrderPlacementResult]:
        """
        Совместимость по сигнатурам OrderManager.submit_approved_trade().
        В разных версиях проекта метод мог принимать:
          - (signal, approval)
          - (signal, approval, snapshot)
          - keyword-only: signal=..., approval=..., snapshot=...
          - опционально validate_signal, now_utc
        Мы передаём только то, что реально поддерживается.
        """
        fn = self._order_manager.submit_approved_trade

        # 1) Пытаемся через signature + фильтрацию kwargs
        try:
            params = inspect.signature(fn).parameters
            kwargs = {}

            if "signal" in params:
                kwargs["signal"] = signal
            if "approval" in params:
                kwargs["approval"] = approval
            if "snapshot" in params:
                kwargs["snapshot"] = snapshot
            if "validate_signal" in params:
                kwargs["validate_signal"] = False
            if "now_utc" in params:
                kwargs["now_utc"] = now_utc

            return fn(**kwargs)  # type: ignore[misc]
        except TypeError:
            # 2) Фолбэк: позиционный вызов (самый распространённый у старых версий)
            try:
                return fn(signal, approval, snapshot)  # type: ignore[misc]
            except TypeError:
                return fn(signal, approval)  # type: ignore[misc]

    def process_signal_once(
        self,
        signal: Signal,
        snapshot: RiskSnapshot,
        *,
        now_utc: Optional[datetime] = None,
        validate_signal_domain: bool = True,
    ) -> ProcessSignalResult:
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        if validate_signal_domain:
            try:
                validate_signal_basic(
                    signal,
                    allow_short=False,
                    allowed_asset_classes=None,
                    now_utc=now_utc,
                    max_age_minutes=60,
                )
            except SignalValidationError as e:
                logger.warning(
                    "TradePipeline.process_signal_once: domain validation failed for signal_id=%s: %s",
                    signal.signal_id,
                    e,
                )

                approval = Approval(
                    signal_id=signal.signal_id,
                    approved=False,
                    reason="INVALID_SIGNAL",
                    reason_detail=str(e),
                    p_win_calibrated=0.0,
                    ev_after_costs=0.0,
                    rr=1.0,  # важно: rr > 0
                    qty=0,
                    risk_usd=0.0,
                )
                return ProcessSignalResult(signal=signal, approval=approval, placement=None)

        ctx = RiskContext(snapshot=snapshot, config=self._risk_cfg, expected_slippage_per_share=0.0)
        approval = evaluate_signal(signal, ctx)

        logger.info(
            "TradePipeline.process_signal_once: RiskGate result for signal_id=%s: "
            "approved=%s, reason=%s, p_cal=%.4f, rr=%.4f, ev_after_costs=%.4f, qty=%s, risk_usd=%.2f",
            signal.signal_id,
            approval.approved,
            approval.reason,
            approval.p_win_calibrated,
            approval.rr,
            approval.ev_after_costs,
            approval.qty,
            approval.risk_usd,
        )

        if not approval.approved:
            logger.info(
                "TradePipeline.process_signal_once: signal_id=%s rejected by RiskGate (reason=%s). No order will be placed.",
                signal.signal_id,
                approval.reason,
            )
            return ProcessSignalResult(signal=signal, approval=approval, placement=None)

        try:
            placement = self._submit_approved_trade_compat(
                signal=signal,
                approval=approval,
                snapshot=snapshot,
                now_utc=now_utc,
            )
            return ProcessSignalResult(signal=signal, approval=approval, placement=placement)
        except Exception as exc:
            logger.exception(
                "TradePipeline.process_signal_once: failed to submit approved trade for signal_id=%s: %s",
                signal.signal_id,
                exc,
            )
            return ProcessSignalResult(signal=signal, approval=approval, placement=None)
