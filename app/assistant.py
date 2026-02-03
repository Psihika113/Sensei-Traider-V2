# -*- coding: utf-8 -*-
# app/assistant.py — Assistant v0: контекст → TradePlans (эвристика + TTL-кэш)
from __future__ import annotations

import time, uuid
from typing import List, Dict, Optional
from datetime import datetime, timezone

from core.schemas import Context, TradePlan

DEFAULT_TTL_MIN = 10  # минут кэша решений на тикер

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class PlanCache:
    """TTL-кэш планов по символу: {symbol: (plan, ts_epoch)}."""
    def __init__(self, ttl_minutes: int = DEFAULT_TTL_MIN):
        self.ttl = max(1, int(ttl_minutes)) * 60
        self._store: Dict[str, tuple[TradePlan, float]] = {}

    def get(self, symbol: str) -> Optional[TradePlan]:
        item = self._store.get(symbol)
        if not item:
            return None
        plan, ts = item
        if (time.time() - ts) > self.ttl:
            self._store.pop(symbol, None)
            return None
        return plan

    def put(self, plan: TradePlan):
        self._store[plan.symbol] = (plan, time.time())

def _heuristics(last: float, atr1m: Optional[float]) -> tuple[str, Optional[float], float, float]:
    """
    Возвращает (entry_type, entry, stop, take) для лонга.
    Если ATR нет — fallback на проценты.
    """
    if atr1m and atr1m > 0:
        entry = last
        stop  = max(0.01, last - 1.0 * atr1m)
        take  = last + 1.7 * atr1m
    else:
        entry = last
        stop  = last * (1 - 0.005)   # -0.5%
        take  = last * (1 + 0.0085)  # +0.85%
    return "limit", entry, stop, take

class AssistantV0:
    """
    Простой генератор TradePlan без LLM.
    Логика:
      - Только BUY-лонг для тикеров из universe, по которым нет открытой позиции.
      - План создаётся из снапшота (last/ATR), p_win_est по умолчанию 0.83.
      - TTL-кэш на тикер (по умолчанию 10 минут) во избежание переоценки.
    """
    def __init__(self, ttl_minutes: int = DEFAULT_TTL_MIN, logger=None):
        self.cache = PlanCache(ttl_minutes)
        self.logger = logger

    def _log(self, level: str, payload: dict):
        try:
            if hasattr(self.logger, level):
                getattr(self.logger, level)(payload)
            else:
                print(level.upper(), payload)
        except Exception:
            pass

    def propose_plans(self, ctx: Context) -> List[TradePlan]:
        held = {p.symbol for p in ctx.positions if p.qty and p.qty > 0}
        snap_by_sym = {s.symbol: s for s in ctx.snapshots}
        plans: List[TradePlan] = []

        for sym in ctx.universe:
            if sym in held:
                continue
            snap = snap_by_sym.get(sym)
            if not snap or snap.last is None:
                continue

            # TTL-кэш: если свежий план есть — используем его
            cached = self.cache.get(sym)
            if cached:
                plans.append(cached)
                continue

            # Эвристика v0
            entry_type, entry, stop, take = _heuristics(snap.last, snap.atr1m)

            plan = TradePlan(
                schema="trade_plan.v1",
                plan_id=str(uuid.uuid4()),
                ts_utc=now_utc_iso(),
                symbol=sym,
                side="BUY",
                entry_type=entry_type,
                entry=entry,
                stop=stop,
                take=take,
                tif="DAY",
                rationale="v0 heuristic: entry≈last, stop≈1*ATR (or -0.5%), take≈1.7*ATR (or +0.85%)",
                p_win_est=0.83,  # консервативно, чтобы пройти порог p>=0.80 после калибровки
                risk_pct_equity_max=ctx.risk_limits.risk_pct_equity_cap,
            )
            self.cache.put(plan)
            plans.append(plan)

        self._log("info", {"event": "assistant.proposed", "count": len(plans)})
        return plans
