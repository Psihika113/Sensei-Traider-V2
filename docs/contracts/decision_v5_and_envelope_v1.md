# SenseiTrader Contracts (Canonical)

## Decision v5 (LLM output, NO numeric prices)
Fields:
- schema_version: "sensei.decision.v5"
- action: ALLOW | DENY | WAIT | PAUSE
- reason_code: string (enum-like, stable)
- reason_text: string (short)
- confidence: float (0..1)
- guards: array of strings (e.g. ["STALE_SNAPSHOT", "SPREAD_TOO_WIDE"])
- policy_version: string
- strategy_id: string
- ts_utc: ISO8601 UTC timestamp

Rules:
- LLM MUST NOT output any numeric trading parameters (no entry/stop/take/qty).
- Any numeric parameters belong ONLY to OrderPlanBuilder (deterministic code).

## Envelope v1 (input to pipeline)
Fields:
- schema_version: "sensei.envelope.v1"
- symbol: string
- ts_utc: ISO8601 UTC timestamp
- session: string (e.g. "RTH", "ETH")
- market_snapshot:
  - bid: float
  - ask: float
  - last: float (optional)
  - mid: float
  - spread: float
  - vol_proxy: float (optional)
  - liquidity_flags: array of strings (optional)

Rules:
- Envelope is produced deterministically (MarketDataProvider), not by LLM.
- Staleness policy is enforced before Decision/Plan execution.
