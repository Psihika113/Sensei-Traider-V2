# -*- coding: utf-8 -*-
# app/health.py — минимальная реализация для service.py

import time
from typing import Any, Dict, Optional

class Health:
    def __init__(self, dao: Any):
        self.dao = dao
        self._last_beat_ts = 0.0
        self._last_metrics: Dict[str, Any] = {}

    def beat(self, **metrics) -> None:
        """Принимает любые метрики: ibkr_ok=..., sheets_ok=..., tg_ok=..., queue_depth=..., place_latency_ms=..."""
        self._last_beat_ts = time.time()
        self._last_metrics.update(metrics)

    def last_metrics(self) -> Dict[str, Any]:
        return dict(self._last_metrics)

    def seconds_since_last_beat(self) -> float:
        if self._last_beat_ts == 0.0:
            return float("inf")
        return max(0.0, time.time() - self._last_beat_ts)

    def alert_if_silent(self, seconds: int, notifier: Optional[Any] = None) -> None:
        """Если давно не было beat — уведомим критикой (используется в service.py)."""
        if self.seconds_since_last_beat() > float(seconds):
            if notifier and hasattr(notifier, "critical"):
                try:
                    notifier.critical({"event": "health.silent", "silent_sec": round(self.seconds_since_last_beat(), 2)})
                except Exception:
                    pass
            # сбросим таймер, чтобы не спамить каждую итерацию
            self._last_beat_ts = time.time()
