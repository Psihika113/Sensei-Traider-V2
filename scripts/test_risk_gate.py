# -*- coding: utf-8 -*-
# scripts/test_risk_gate.py
from core.schemas import CashState, MarketSnapshot, RiskLimits, Context, TradePlan
from app.risk import RiskGate, DEFAULT_RISK_PCT_CAP

def mk_ctx(equity=100_000, used=0.10):
    cash = CashState(equity_usd=equity, equity_used_pct=used)
    limits = RiskLimits(min_rr=1.5, risk_pct_equity_cap=0.0075, equity_utilization_hard_cap=0.75, daily_loss_limit_pct=0.02, outside_rth=False)
    snap = [MarketSnapshot(symbol="AAPL", last=100.0, atr1m=1.0, ts_utc="2025-01-01T00:00:00Z")]
    return Context(schema="context.v1", ts_utc="2025-01-01T00:00:00Z",
                   cash=cash, positions=[], snapshots=snap, risk_limits=limits, universe=["AAPL"])

def test_reject_p_low():
    ctx = mk_ctx()
    plan = TradePlan(schema="trade_plan.v1", plan_id="p1", ts_utc="...", symbol="AAPL",
                     side="BUY", entry_type="limit", entry=100.0, stop=99.0, take=101.5, tif="DAY",
                     p_win_est=0.79, risk_pct_equity_max=DEFAULT_RISK_PCT_CAP)
    appr = RiskGate().approve(ctx, plan)
    assert not appr.approved and appr.reason == "p_win<0.80"

def test_reject_rr_low():
    ctx = mk_ctx()
    plan = TradePlan(schema="trade_plan.v1", plan_id="p2", ts_utc="...", symbol="AAPL",
                     side="BUY", entry_type="limit", entry=100.0, stop=99.5, take=101.0, tif="DAY",
                     p_win_est=0.90, risk_pct_equity_max=DEFAULT_RISK_PCT_CAP)
    appr = RiskGate().approve(ctx, plan)
    assert not appr.approved and appr.reason == "RR<1.5"

def test_reject_hard_cap():
    ctx = mk_ctx(used=0.80)
    plan = TradePlan(schema="trade_plan.v1", plan_id="p3", ts_utc="...", symbol="AAPL",
                     side="BUY", entry_type="limit", entry=100.0, stop=99.0, take=102.0, tif="DAY",
                     p_win_est=0.90, risk_pct_equity_max=DEFAULT_RISK_PCT_CAP)
    appr = RiskGate().approve(ctx, plan)
    assert not appr.approved and appr.reason == "HardCap reached"

def test_accept_ok():
    ctx = mk_ctx()
    plan = TradePlan(schema="trade_plan.v1", plan_id="p4", ts_utc="...", symbol="AAPL",
                     side="BUY", entry_type="limit", entry=100.0, stop=99.0, take=102.0, tif="DAY",
                     p_win_est=0.85, risk_pct_equity_max=DEFAULT_RISK_PCT_CAP)
    appr = RiskGate().approve(ctx, plan)
    assert appr.approved and appr.qty is not None and appr.rr >= 1.5 and appr.ev_after_costs > 0
