# -*- coding: utf-8 -*-
# app/risk_config.py — v1: простые риск-профили из TOML

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger("sensei")

try:
    import tomllib as toml  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10 и ниже
    import tomli as toml


@dataclass
class RiskProfile:
    """
    Описывает один риск-профиль:
      - equity_usd: с какой условной базой капитала считаемся;
      - daily_loss_limit_pct: дневной лимит просадки в процентах.
    """
    name: str
    equity_usd: float
    daily_loss_limit_pct: float


@dataclass
class RiskConfig:
    """
    Все профили + имя профиля по умолчанию.
    """
    profiles: Dict[str, RiskProfile]
    default_profile: str


def load_risk_config(
    path: str | Path,
    default_equity: float,
    default_daily_loss_pct: float,
) -> RiskConfig:
    """
    Загружает риск-профили из config/risk.toml.

    Формат файла:

        [general]
        default_profile = "demo_safe"

        [profile.demo_safe]
        equity_usd = 100000
        daily_loss_limit_pct = 2.0

        [profile.demo_aggressive]
        equity_usd = 100000
        daily_loss_limit_pct = 8.0

    Если файл отсутствует / битый / секция пустая —
    строится один профиль "default" с заданными default_*.
    """
    path = Path(path)
    profiles: Dict[str, RiskProfile] = {}

    if not path.exists():
        name = "default"
        profiles[name] = RiskProfile(
            name=name,
            equity_usd=float(default_equity),
            daily_loss_limit_pct=float(default_daily_loss_pct),
        )
        logger.info(
            {
                "event": "risk.config_missing",
                "path": str(path),
                "fallback_profile": name,
                "equity_usd": float(default_equity),
                "daily_loss_limit_pct": float(default_daily_loss_pct),
            }
        )
        return RiskConfig(profiles=profiles, default_profile=name)

    try:
        with path.open("rb") as f:
            raw_cfg: Dict[str, Any] = toml.load(f)
    except Exception as e:
        name = "default"
        profiles[name] = RiskProfile(
            name=name,
            equity_usd=float(default_equity),
            daily_loss_limit_pct=float(default_daily_loss_pct),
        )
        logger.error(
            {
                "event": "risk.config_parse_error",
                "path": str(path),
                "err": str(e),
            }
        )
        return RiskConfig(profiles=profiles, default_profile=name)

    general = raw_cfg.get("general", {}) or {}
    default_name = str(general.get("default_profile", "default"))

    prof_section = raw_cfg.get("profile", {}) or {}
    if not isinstance(prof_section, dict) or not prof_section:
        name = default_name
        profiles[name] = RiskProfile(
            name=name,
            equity_usd=float(default_equity),
            daily_loss_limit_pct=float(default_daily_loss_pct),
        )
        logger.info(
            {
                "event": "risk.config_empty_profiles",
                "path": str(path),
                "fallback_profile": name,
            }
        )
        return RiskConfig(profiles=profiles, default_profile=name)

    for name, data in prof_section.items():
        if not isinstance(data, dict):
            continue
        eq = float(data.get("equity_usd", default_equity))
        dll = float(data.get("daily_loss_limit_pct", default_daily_loss_pct))
        profiles[name] = RiskProfile(
            name=name,
            equity_usd=eq,
            daily_loss_limit_pct=dll,
        )

    if default_name not in profiles:
        default_name = next(iter(profiles.keys()))

    logger.info(
        {
            "event": "risk.config_loaded",
            "path": str(path),
            "profiles": list(profiles.keys()),
            "default_profile": default_name,
        }
    )
    return RiskConfig(profiles=profiles, default_profile=default_name)


def select_profile(cfg: RiskConfig, name: str | None) -> RiskProfile:
    """
    Выбор активного профиля:
      - если name None → берём cfg.default_profile;
      - если профиля нет → логируем и откатываемся на default_profile.
    """
    if name:
        requested = str(name)
    else:
        requested = cfg.default_profile

    prof = cfg.profiles.get(requested)
    if prof is not None:
        return prof

    logger.warning(
        {
            "event": "risk.profile_fallback",
            "requested": requested,
            "fallback": cfg.default_profile,
        }
    )
    return cfg.profiles[cfg.default_profile]
