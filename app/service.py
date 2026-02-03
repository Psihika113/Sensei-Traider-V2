# -*- coding: utf-8 -*-
"""
app/service.py

Запуск контура:
  Signal (из ./signals или пусто) → RiskGate → Executor → IBKR (offline/paper/live)

Ключевые правила:
  - LIVE запрещён без ARM (флаг live_arm_until_utc в БД)
  - PAPER/LIVE НЕ пишут фейковые executions
  - OFFLINE пишет виртуальный fill в executions (для тестов)

Запуск:
  set SENSEI_MODE=offline|paper|live
  python -m app.service --config config/app.toml
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

import app.dao as dao
from adapters.ibkr.client import IBKRClient
from app.commands import CommandsPoller, KillSwitch as TgKillSwitch
from app.config import load_app_config
from app.db import Database
from app.executor import OrderManager
from app.health import Health
from app.ibkr_fills_sync import sync_ibkr_fills_once
from app.logger import build_logger
from app.migrations import ensure_aux_tables, ensure_v1b_schema
from app.notify import OfflineNotifier, Notifier
from app.pipeline import TradePipeline
from app.sheets import OfflineSheetsClient, SheetsClient
from core.schemas import DecisionActionV5, DecisionV5, EnvelopeV1, RiskSnapshot, Signal


logger = logging.getLogger("sensei")


# =============================================================================
#  LIVE ARM (флаг в БД)
# =============================================================================

FLAG_LIVE_ARM_UNTIL_UTC = "live_arm_until_utc"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso_dt(s: str) -> dt.datetime | None:
    try:
        x = dt.datetime.fromisoformat(s)
        if x.tzinfo is None:
            x = x.replace(tzinfo=dt.timezone.utc)
        return x.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _get_live_arm_until(db: Database) -> dt.datetime | None:
    try:
        v = dao.get_flag(db, FLAG_LIVE_ARM_UNTIL_UTC)
    except Exception:
        return None
    if not v:
        return None
    return _parse_iso_dt(v)


def _is_live_armed(db: Database) -> tuple[bool, str | None]:
    until = _get_live_arm_until(db)
    if until is None:
        return (False, None)
    now = _now_utc()
    if until <= now:
        return (False, until.isoformat())
    return (True, until.isoformat())


def _arm_from_env_if_requested(db: Database, *, log: logging.Logger) -> None:
    """
    Временный ARM через env (пока нет команды /arm).

    Пример:
      set SENSEI_LIVE_ARM=1
      set SENSEI_LIVE_ARM_MINUTES=30
    """
    if os.getenv("SENSEI_LIVE_ARM", "").strip() != "1":
        return
    try:
        minutes = int(os.getenv("SENSEI_LIVE_ARM_MINUTES", "15").strip())
    except Exception:
        minutes = 15
    minutes = max(1, min(minutes, 180))
    until = _now_utc() + dt.timedelta(minutes=minutes)
    try:
        dao.set_flag(db, FLAG_LIVE_ARM_UNTIL_UTC, until.isoformat())
        log.warning({"event": "live.armed", "until_utc": until.isoformat(), "via": "env"})
    except Exception as exc:
        log.error({"event": "live.arm_failed", "err": str(exc)})


# =============================================================================
#  JSON-safe logging helpers
# =============================================================================

def _to_jsonable(obj) -> object:
    """
    Приводит pydantic-модель/объект к JSON-совместимому dict/primitive.
    Приоритет: model_dump_json() -> json.loads().
    """
    try:
        dump_json = getattr(obj, "model_dump_json", None)
        if callable(dump_json):
            return json.loads(dump_json())
    except Exception:
        pass

    try:
        dump = getattr(obj, "model_dump", None)
        if callable(dump):
            try:
                return dump(mode="json")
            except Exception:
                return dump()
    except Exception:
        pass

    return obj


# =============================================================================
#  Source: signals from file(s)
# =============================================================================

class _EmptySignalSource:
    def poll(self) -> Optional[tuple[Signal, Path]]:
        time.sleep(0.5)
        return None

    def ack(self, file_path: Path, outcome: str) -> None:
        return


class _FileSignalSourceV2:
    """
    Источник, который "потребляет" json-файлы сигналов:
      - успешно обработанные (submitted/duplicate/rejected) → signals/_processed/
      - ошибки чтения/формата/валидации → signals/_failed/

    Поддерживает:
      - один файл (dict или list)
      - директорию *.json
    """

    def __init__(self, path: str | Path, *, log: logging.Logger) -> None:
        self._log = log
        self._queue: list[tuple[Signal, Path]] = []
        self._i = 0

        # чтобы не перемещать файл раньше времени (если list сигналов в одном файле)
        self._remaining: dict[str, int] = {}
        self._worst_outcome: dict[str, str] = {}  # "processed" | "rejected" | "failed"

        self._load(Path(path))

    def _base_dir_for(self, path: Path) -> Path:
        return path if path.is_dir() else path.parent

    def _processed_dir(self, base: Path) -> Path:
        return base / "_processed"

    def _failed_dir(self, base: Path) -> Path:
        return base / "_failed"

    def _move_file(self, src: Path, dst_dir: Path) -> None:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name

            # не перезатирать: если имя уже есть — суффикс времени
            if dst.exists():
                stem = src.stem
                suffix = src.suffix
                ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dst = dst_dir / f"{stem}__{ts}{suffix}"

            shutil.move(str(src), str(dst))
        except Exception as exc:
            self._log.error({"event": "signals.move_error", "file": str(src), "err": str(exc)})

    def _severity(self, outcome: str) -> int:
        # чем выше — тем хуже
        if outcome == "failed":
            return 3
        if outcome == "rejected":
            return 2
        return 1  # processed/duplicate/submitted

    def _merge_outcome(self, key: str, new_outcome: str) -> None:
        cur = self._worst_outcome.get(key, "processed")
        if self._severity(new_outcome) > self._severity(cur):
            self._worst_outcome[key] = new_outcome

    def _load(self, path: Path) -> None:
        if not path.exists():
            self._log.warning({"event": "signals.path_not_found", "path": str(path)})
            return

        files = [path] if path.is_file() else sorted(path.glob("*.json"))
        loaded_signals = 0
        loaded_files = 0

        for f in files:
            base = self._base_dir_for(path)

            try:
                raw = json.loads(f.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                self._log.error({"event": "signals.read_error", "file": str(f), "err": str(exc)})
                self._move_file(f, self._failed_dir(base))
                continue

            if isinstance(raw, dict):
                raw = [raw]
            if not isinstance(raw, list):
                self._log.error({"event": "signals.bad_format", "file": str(f), "type": type(raw).__name__})
                self._move_file(f, self._failed_dir(base))
                continue

            # валидируем весь файл целиком: если хоть что-то невалидно — файл в failed
            signals_in_file: list[Signal] = []
            ok = True
            for item in raw:
                try:
                    signals_in_file.append(Signal(**item))
                except Exception as exc:
                    ok = False
                    self._log.error({"event": "signals.validation_error", "file": str(f), "err": str(exc), "raw": item})

            if not ok or not signals_in_file:
                self._move_file(f, self._failed_dir(base))
                continue

            key = str(f.resolve())
            self._remaining[key] = len(signals_in_file)
            self._worst_outcome[key] = "processed"

            for sig in signals_in_file:
                self._queue.append((sig, f))

            loaded_signals += len(signals_in_file)
            loaded_files += 1

        self._log.info({"event": "signals.loaded", "path": str(path), "files": loaded_files, "signals": loaded_signals})

    def poll(self) -> Optional[tuple[Signal, Path]]:
        if self._i >= len(self._queue):
            time.sleep(0.5)
            return None
        item = self._queue[self._i]
        self._i += 1
        return item

    def ack(self, file_path: Path, outcome: str) -> None:
        """
        outcome:
          - "submitted" | "duplicate" | "processed" → _processed
          - "rejected" → _processed (но как "хуже", если в файле всё rejected)
          - "failed" → _failed
        """
        key = str(file_path.resolve())

        if key not in self._remaining:
            return

        self._remaining[key] -= 1
        self._merge_outcome(key, outcome)

        if self._remaining[key] > 0:
            return

        base = file_path.parent
        final = self._worst_outcome.get(key, "processed")

        if final == "failed":
            self._move_file(file_path, self._failed_dir(base))
            self._log.info({"event": "signals.archived_failed", "file": str(file_path)})
        else:
            self._move_file(file_path, self._processed_dir(base))
            self._log.info({"event": "signals.archived_processed", "file": str(file_path), "final": final})

        self._remaining.pop(key, None)
        self._worst_outcome.pop(key, None)


# =============================================================================
#  Source: envelopes from file(s)  (Envelope v1)
# =============================================================================

SENSEI_ENVELOPE_MAX_AGE_MINUTES_DEFAULT = 60
SENSEI_ENVELOPE_MAX_SPREAD_DEFAULT = 0.05  # USD


def _policy_version_from_config_path(cfg_path: Path) -> str:
    # стабильная строка (без хеша), чтобы не зависеть от окружения
    try:
        return f"risk:{Path(cfg_path).name}"
    except Exception:
        return "risk:unknown"


def _build_decision_v5_for_envelope(
    env: EnvelopeV1,
    *,
    now_utc: dt.datetime,
    policy_version: str,
    strategy_id: str,
    max_spread: float,
) -> DecisionV5:
    guards: list[str] = []

    # spread guard
    try:
        if env.market_snapshot.spread > float(max_spread):
            guards.append("SPREAD_TOO_WIDE")
    except Exception:
        guards.append("SPREAD_INVALID")

    # liquidity guard
    try:
        flags = env.market_snapshot.liquidity_flags or []
        flags_norm = {str(x).strip().upper() for x in flags if str(x).strip()}
        if "OK" not in flags_norm:
            guards.append("LIQUIDITY_NOT_OK")
    except Exception:
        guards.append("LIQUIDITY_FLAGS_INVALID")

    # action mapping (детерминированно)
    if not guards:
        action = DecisionActionV5.ALLOW
        reason_code = "OK"
        reason_text = "Envelope checks passed."
        confidence = 0.50
    else:
        # на этапе SHADOW разумнее WAIT, а не DENY
        action = DecisionActionV5.WAIT
        reason_code = "GUARDS"
        reason_text = "Envelope requires additional conditions."
        confidence = 0.30

    return DecisionV5(
        action=action,
        reason_code=reason_code,
        reason_text=reason_text,
        confidence=confidence,
        guards=guards,
        policy_version=policy_version,
        strategy_id=strategy_id,
        ts_utc=now_utc,
    )


class _EmptyEnvelopeSource:
    def poll(self) -> Optional[tuple[EnvelopeV1, Path]]:
        time.sleep(0.5)
        return None

    def ack(self, file_path: Path, outcome: str) -> None:
        return


class _FileEnvelopeSourceV1:
    """
    Envelope inbox source:
      - читает *.json из inbox
      - валидирует через EnvelopeV1
      - outcome:
          "done" -> done_path
          "bad"  -> bad_path
    """

    def __init__(self, *, inbox: Path, done: Path, bad: Path, max_files_per_tick: int, log: logging.Logger) -> None:
        self._log = log
        self._inbox = inbox
        self._done = done
        self._bad = bad
        self._max = max(1, int(max_files_per_tick))

        self._inbox.mkdir(parents=True, exist_ok=True)
        self._done.mkdir(parents=True, exist_ok=True)
        self._bad.mkdir(parents=True, exist_ok=True)

        n = len(list(self._inbox.glob("*.json")))
        self._log.info(
            {
                "event": "envelopes.loaded",
                "inbox": str(self._inbox),
                "done": str(self._done),
                "bad": str(self._bad),
                "files_in_inbox": n,
                "max_files_per_tick": self._max,
            }
        )

    def _move_file(self, src: Path, dst_dir: Path) -> None:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name

            if dst.exists():
                stem = src.stem
                suffix = src.suffix
                ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dst = dst_dir / f"{stem}__{ts}{suffix}"

            shutil.move(str(src), str(dst))
        except Exception as exc:
            self._log.error({"event": "envelopes.move_error", "file": str(src), "err": str(exc)})

    def poll(self) -> Optional[tuple[EnvelopeV1, Path]]:
        files = sorted(self._inbox.glob("*.json"))[: self._max]
        if not files:
            time.sleep(0.2)
            return None

        f = files[0]
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig"))
            env = EnvelopeV1.model_validate(raw)
            return (env, f)
        except Exception as exc:
            self._log.error({"event": "envelope.read_or_validate_error", "file": str(f), "err": str(exc)})
            self._move_file(f, self._bad)
            return None

    def ack(self, file_path: Path, outcome: str) -> None:
        if outcome == "done":
            self._move_file(file_path, self._done)
            self._log.info({"event": "envelope.archived_done", "file": str(file_path)})
            return

        self._move_file(file_path, self._bad)
        self._log.info({"event": "envelope.archived_bad", "file": str(file_path), "outcome": outcome})


# =============================================================================
#  RiskSnapshot (v1: минимальный, без расчётов PnL)
# =============================================================================

def _guess_equity_usd() -> float:
    raw = os.getenv("SENSEI_EQUITY_USD", "100000")
    try:
        v = float(raw)
        return v if v > 0 else 100000.0
    except Exception:
        return 100000.0


def _build_snapshot(*, equity_usd: float, daily_loss_limit_pct: float, kill_switch: bool) -> RiskSnapshot:
    now = _now_utc()
    as_of = dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc)
    return RiskSnapshot(
        as_of_date=as_of,
        equity_start_day=float(equity_usd),
        equity_current=float(equity_usd),
        realized_pnl_day=0.0,
        unrealized_pnl_day=0.0,
        daily_loss_limit_pct=float(daily_loss_limit_pct),
        kill_switch_triggered=bool(kill_switch),
        equity_utilization=0.0,
    )


# =============================================================================
#  Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/app.toml", help="Путь к app.toml")
    args = parser.parse_args()

    cfg = load_app_config(args.config)

    # mode: config → env override
    mode = (cfg.runtime.mode or "offline").strip().lower()
    env_mode = os.getenv("SENSEI_MODE", "").strip().lower()
    if env_mode in ("offline", "paper", "live"):
        mode = env_mode
    if mode not in ("offline", "paper", "live"):
        mode = "offline"

    global logger
    logger = build_logger("sensei")
    logger.info({"event": "service.start", "env": cfg.runtime.environment, "mode": mode, "db_path": str(cfg.db.path)})

    # db + migrations
    cfg.db.path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(cfg.db.path)
    db.connect()
    ensure_v1b_schema(db.conn)
    ensure_aux_tables(db.conn)

    # LIVE: запрещаем старт без ARM
    if mode == "live":
        _arm_from_env_if_requested(db, log=logger)
        armed, until = _is_live_armed(db)
        if not armed:
            logger.error(
                {
                    "event": "live.not_armed",
                    "live_arm_until_utc": until,
                    "how": "Для временного ARM: set SENSEI_LIVE_ARM=1 & set SENSEI_LIVE_ARM_MINUTES=15",
                }
            )
            return 2

    # health
    health = Health(db)

    # clients
    sheets_client: Optional[SheetsClient] = None
    notifier: Optional[Notifier] = None
    ib_client: Optional[IBKRClient] = None

    if mode == "offline":
        sheets_client = OfflineSheetsClient()
        notifier = OfflineNotifier()
    else:
        if cfg.sheets is not None:
            try:
                sheets_client = SheetsClient(cfg.sheets)
            except Exception as exc:
                logger.error({"event": "sheets.init_error", "err": str(exc)})
                sheets_client = None

        if cfg.telegram is not None:
            try:
                notifier = Notifier(cfg.telegram)
            except Exception as exc:
                logger.error({"event": "tg.init_error", "err": str(exc)})
                notifier = None

        ib_client = IBKRClient(cfg.ibkr)
        try:
            ib_client.connect()
        except Exception as exc:
            logger.error({"event": "ib.connect_failed", "err": str(exc)})

    # order manager + pipeline
    order_manager = OrderManager(db=db, ib_client=ib_client, risk_config=cfg.risk, mode=mode)
    pipeline = TradePipeline(db=db, risk_config=cfg.risk, order_manager=order_manager)

    # TG commands (killswitch + status)
    ks = TgKillSwitch()
    commands_poller: Optional[CommandsPoller] = None

    if cfg.telegram is not None and mode != "offline":

        def _get_status_snapshot() -> dict:
            armed, until = _is_live_armed(db) if mode == "live" else (False, None)
            return {
                "mode": mode,
                "live_armed": armed,
                "live_arm_until_utc": until,
                "ib_ready": bool(ib_client is not None and getattr(ib_client, "is_connected", False)),
                "sheets_ready": bool(sheets_client is not None),
                "tg_enabled": True,
                "kill_switch": ks.is_on(),
                "queue_size": 0,
                "time_utc": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        try:
            commands_poller = CommandsPoller(
                token=cfg.telegram.bot_token,
                chat_id=cfg.telegram.chat_id,
                logger=logger,
                get_status=_get_status_snapshot,
                kill_switch=ks,
                poll_interval_sec=max(2, cfg.runtime.loop_sleep_seconds),
            )
            commands_poller.start()
        except Exception as exc:
            logger.error({"event": "tg.commands_init_error", "err": str(exc)})
            commands_poller = None

    # signals source
    if mode == "offline" or os.getenv("SENSEI_SIGNALS_ENABLE", "").strip() == "1":
        source = _FileSignalSourceV2(os.getenv("SENSEI_SIGNALS_PATH", "signals"), log=logger)
    else:
        source = _EmptySignalSource()

    # envelopes source (optional)
    env_source = _EmptyEnvelopeSource()
    if getattr(cfg, "envelopes", None) is not None:
        try:
            env_source = _FileEnvelopeSourceV1(
                inbox=cfg.envelopes.inbox_path,
                done=cfg.envelopes.done_path,
                bad=cfg.envelopes.bad_path,
                max_files_per_tick=cfg.envelopes.max_files_per_tick,
                log=logger,
            )
        except Exception as exc:
            logger.error({"event": "envelopes.init_error", "err": str(exc)})
            env_source = _EmptyEnvelopeSource()

    try:
        env_max_age_min = int(
            os.getenv("SENSEI_ENVELOPE_MAX_AGE_MINUTES", str(SENSEI_ENVELOPE_MAX_AGE_MINUTES_DEFAULT))
        )
    except Exception:
        env_max_age_min = SENSEI_ENVELOPE_MAX_AGE_MINUTES_DEFAULT
    env_max_age_min = max(1, min(env_max_age_min, 1440))

    try:
        env_max_spread = float(os.getenv("SENSEI_ENVELOPE_MAX_SPREAD", str(SENSEI_ENVELOPE_MAX_SPREAD_DEFAULT)))
    except Exception:
        env_max_spread = SENSEI_ENVELOPE_MAX_SPREAD_DEFAULT
    env_max_spread = max(0.0, env_max_spread)

    strategy_id = os.getenv("SENSEI_STRATEGY_ID", "envelope-shadow-1").strip() or "envelope-shadow-1"

    # NOTE: cfg.risk.config_path — каноничный путь в вашем config/app.offline.toml
    risk_cfg_path = Path(getattr(cfg.risk, "config_path", "risk_config.yaml"))
    policy_version = _policy_version_from_config_path(risk_cfg_path)

    # risk base
    equity_usd = _guess_equity_usd()
    daily_loss_limit_pct = float(getattr(cfg.risk, "daily_loss_limit_pct", 0.02))

    # loop timings
    loop_sleep = max(0.2, float(cfg.runtime.loop_sleep_seconds))
    hb_every = max(2.0, float(cfg.runtime.loop_sleep_seconds))
    last_hb = 0.0

    # -------------------------------------------------------------------------
    # IBKR fills sync settings (PAPER/LIVE)
    # -------------------------------------------------------------------------
    ib_sync_enable = os.getenv("SENSEI_IB_SYNC_ENABLE", "").strip() == "1"
    try:
        ib_sync_interval = int(os.getenv("SENSEI_IB_SYNC_INTERVAL_SECONDS", "30"))
    except Exception:
        ib_sync_interval = 30
    ib_sync_interval = max(5, ib_sync_interval)

    try:
        ib_sync_lookback = int(os.getenv("SENSEI_IB_SYNC_LOOKBACK_MINUTES", "240"))
    except Exception:
        ib_sync_lookback = 240

    last_ib_sync = 0.0

    try:
        while True:
            now_ts = time.time()

            # heartbeat
            if now_ts - last_hb >= hb_every:
                try:
                    health.beat(
                        ibkr_ok=bool(ib_client is not None and getattr(ib_client, "is_connected", False)),
                        sheets_ok=bool(sheets_client is not None),
                        tg_ok=bool(notifier is not None),
                        queue_depth=0,
                    )
                except Exception as exc:
                    logger.error({"event": "health.beat_error", "err": str(exc)})
                last_hb = now_ts

            # -----------------------------------------------------------------
            # IBKR fills sync (PAPER/LIVE)
            # -----------------------------------------------------------------
            if ib_sync_enable and ib_client is not None and mode in ("paper", "live"):
                if now_ts - last_ib_sync >= ib_sync_interval:
                    try:
                        stats = sync_ibkr_fills_once(
                            db=db,
                            ib_client=ib_client,
                            log=logger,
                            lookback_minutes=ib_sync_lookback,
                        )
                        logger.info({"event": "ibkr.fills_sync", **stats})
                    except Exception as exc:
                        logger.error({"event": "ibkr.fills_sync_error", "err": str(exc)})
                    last_ib_sync = now_ts

            # -----------------------------------------------------------------
            # envelopes tick (ingestion smoke + Decision v5)
            # -----------------------------------------------------------------
            env_item = env_source.poll()
            if env_item is not None:
                env, env_path = env_item
                now_utc = _now_utc()

                ts = env.ts_utc
                if getattr(ts, "tzinfo", None) is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
                ts = ts.astimezone(dt.timezone.utc)

                age_min = (now_utc - ts).total_seconds() / 60.0
                if age_min > float(env_max_age_min):
                    logger.info(
                        {
                            "event": "envelope.stale",
                            "file": str(env_path),
                            "symbol": env.symbol,
                            "age_min": round(age_min, 3),
                            "max_age_min": env_max_age_min,
                        }
                    )

                    try:
                        dao.try_insert_envelope_v1_return_id(
                            db,
                            source_file=str(env_path),
                            symbol=env.symbol,
                            ts_utc=ts,
                            session=getattr(env, "session", None),
                            payload=_to_jsonable(env),
                            ingested_ts_utc=now_utc,
                            outcome="stale",
                            err=None,
                        )
                    except Exception as exc:
                        logger.error({"event": "db.envelope_insert_error", "file": str(env_path), "err": str(exc)})

                    try:
                        env_source.ack(env_path, "bad")
                    except Exception:
                        pass

                else:
                    logger.info(
                        {
                            "event": "envelope.accepted",
                            "file": str(env_path),
                            "symbol": env.symbol,
                            "ts_utc": ts.isoformat().replace("+00:00", "Z"),
                        }
                    )

                    decision = _build_decision_v5_for_envelope(
                        env,
                        now_utc=now_utc,
                        policy_version=policy_version,
                        strategy_id=strategy_id,
                        max_spread=env_max_spread,
                    )

                    envelope_id = None
                    try:
                        envelope_id = dao.try_insert_envelope_v1_return_id(
                            db,
                            source_file=str(env_path),
                            symbol=env.symbol,
                            ts_utc=ts,
                            session=getattr(env, "session", None),
                            payload=_to_jsonable(env),
                            ingested_ts_utc=now_utc,
                            outcome="done",
                            err=None,
                        )
                    except Exception as exc:
                        logger.error({"event": "db.envelope_insert_error", "file": str(env_path), "err": str(exc)})

                    try:
                        dao.try_insert_decision_v5(
                            db,
                            envelope_id=envelope_id,
                            source_file=str(env_path),
                            ts_utc=now_utc,
                            action=str(decision.action),
                            reason_code=decision.reason_code,
                            reason_text=decision.reason_text,
                            confidence=decision.confidence,
                            guards=list(decision.guards or []),
                            policy_version=decision.policy_version,
                            strategy_id=decision.strategy_id,
                            payload=_to_jsonable(decision),
                        )
                    except Exception as exc:
                        logger.error({"event": "db.decision_insert_error", "file": str(env_path), "err": str(exc)})

                    logger.info({"event": "decision.created", "decision": _to_jsonable(decision)})

                    try:
                        env_source.ack(env_path, "done")
                    except Exception:
                        pass

            # -----------------------------------------------------------------
            # signals tick (legacy)
            # -----------------------------------------------------------------
            item = source.poll()
            if item is None:
                time.sleep(loop_sleep)
                continue

            sig, sig_path = item

            snapshot = _build_snapshot(
                equity_usd=equity_usd,
                daily_loss_limit_pct=daily_loss_limit_pct,
                kill_switch=ks.is_on(),
            )

            res = pipeline.process_signal_once(signal=sig, snapshot=snapshot, now_utc=_now_utc())

            if not res.approval.approved:
                # decision переменной здесь нет. Логируем approval (json-safe).
                logger.info({"event": "risk.reject", "signal_id": sig.signal_id, "reason": str(res.approval.reason)})
                logger.info({"event": "decision.created", "decision": _to_jsonable(res.approval)})
                try:
                    source.ack(sig_path, "rejected")
                except Exception:
                    pass
                continue

            if res.placement is None:
                logger.error({"event": "trade.not_placed", "signal_id": sig.signal_id, "symbol": sig.symbol})
                try:
                    source.ack(sig_path, "failed")
                except Exception:
                    pass
                continue

            # Идемпотентный дубликат — НЕ ошибка
            if getattr(res.placement, "status", "OK") == "DUPLICATE":
                logger.info(
                    {
                        "event": "trade.duplicate",
                        "signal_id": sig.signal_id,
                        "symbol": sig.symbol,
                        "order_id": res.placement.order.order_id,
                    }
                )
                try:
                    source.ack(sig_path, "duplicate")
                except Exception:
                    pass
                continue

            # В paper/live duplicate_order_skip_broker возвращает placement с ib_order_ids=None
            if mode != "offline" and res.placement.ib_order_ids is None:
                logger.info(
                    {
                        "event": "trade.duplicate_skipped",
                        "signal_id": sig.signal_id,
                        "symbol": sig.symbol,
                        "order_id": res.placement.order.order_id,
                    }
                )
                try:
                    source.ack(sig_path, "duplicate")
                except Exception:
                    pass
                continue

            logger.info(
                {
                    "event": "trade.submitted",
                    "signal_id": sig.signal_id,
                    "symbol": sig.symbol,
                    "order_id": res.placement.order.order_id,
                    "ib_ids": res.placement.ib_order_ids,
                }
            )
            try:
                source.ack(sig_path, "submitted")
            except Exception:
                pass

    except KeyboardInterrupt:
        logger.warning({"event": "service.stop", "reason": "keyboard_interrupt"})
        return 0
    finally:
        if commands_poller is not None:
            try:
                commands_poller.stop()
            except Exception:
                pass
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
