from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

try:
    # Python 3.11+
    import tomllib  # type: ignore
except Exception:  # pragma: no cover
    # Для Python 3.10 нужен пакет tomli
    import tomli as tomllib  # type: ignore

from app.risk import RiskConfig
from app.sheets import SheetsConfig
from app.notify import TelegramNotifyConfig
from adapters.ibkr.client import IBKRConnectionParams

logger = logging.getLogger(__name__)


# ==========================
#  Dataclass-ы конфигурации
# ==========================


@dataclass
class DatabaseConfig:
    """
    Настройки подключения к SQLite.
    """
    path: Path  # путь к файлу БД (например, data/trader.db)


@dataclass
class RuntimeConfig:
    """
    Общие runtime-настройки сервиса.

    mode                             — режим работы: "offline" / "paper" / "live".
    environment                      — окружение (dev/stage/prod).
    loop_sleep_seconds               — базовый sleep главного цикла.
    sheets_sync_interval_seconds     — как часто гонять sync с Google Sheets.
    notify_flush_interval_seconds    — как часто вызывать flush_normal_batch().
    risk_snapshot_refresh_seconds    — как часто обновлять RiskSnapshot (из БД/портфеля).
    """

    mode: str = "offline"
    environment: str = "dev"
    loop_sleep_seconds: int = 5
    sheets_sync_interval_seconds: int = 60
    notify_flush_interval_seconds: int = 60
    risk_snapshot_refresh_seconds: int = 30


@dataclass
class EnvelopesConfig:
    """
    Настройки file-based ingress для Envelope v1.
    """
    inbox_path: Path
    done_path: Path
    bad_path: Path
    max_files_per_tick: int = 10


@dataclass
class AppConfig:
    """
    Главный объект конфигурации приложения.
    """

    db: DatabaseConfig
    runtime: RuntimeConfig

    # Риск и брокер
    risk: RiskConfig
    risk_config_path: Path
    ibkr: IBKRConnectionParams

    # Интеграции (опциональны)
    sheets: Optional[SheetsConfig]
    telegram: Optional[TelegramNotifyConfig]

    # Новый контур (опционально)
    envelopes: Optional[EnvelopesConfig] = None


# ==========================
#  Вспомогательные функции
# ==========================


def _load_toml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid TOML config structure in {path}")

    return data


def _get_section(root: Dict[str, Any], name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    val = root.get(name)
    if val is None:
        return default or {}
    if not isinstance(val, dict):
        raise ValueError(f"Section [{name}] in app.toml must be a table/object.")
    return val


def _project_root_from_cfg(cfg_path: Path) -> Path:
    """
    Определяет корень проекта по пути к app.*.toml.
    Если конфиг лежит в папке 'config', то корень проекта = parent(config).
    Иначе корень = parent(cfg_path).
    """
    base_dir = cfg_path.parent
    if base_dir.name.lower() == "config":
        return base_dir.parent
    return base_dir


def _path_candidates(raw: str, base_dir: Path, project_root: Path) -> List[Path]:
    """
    Формирует список кандидатных путей для raw, чтобы корректно поддерживать:
    - raw="risk_config.yaml" (относительно base_dir=config)
    - raw="config/risk_config.yaml" (относительно project_root)
    - raw с '\' или '/'
    """
    raw_norm = raw.replace("\\", "/").lstrip()
    candidates: List[Path] = []

    # 1) Относительно base_dir (обычно config/)
    candidates.append((base_dir / raw).expanduser().resolve())

    # 2) Если указали "config/..." при том, что base_dir уже "config", пробуем убрать префикс
    if raw_norm.lower().startswith("config/"):
        stripped = raw_norm[7:]
        candidates.append((base_dir / stripped).expanduser().resolve())

    # 3) Относительно project_root (корня проекта)
    candidates.append((project_root / raw).expanduser().resolve())

    # 4) И снова stripped относительно project_root (на случай, если raw уже "config/..")
    if raw_norm.lower().startswith("config/"):
        stripped = raw_norm[7:]
        candidates.append((project_root / stripped).expanduser().resolve())

    # Удалим дубликаты, сохранив порядок
    uniq: List[Path] = []
    seen = set()
    for p in candidates:
        sp = str(p)
        if sp not in seen:
            seen.add(sp)
            uniq.append(p)
    return uniq


def _resolve_existing_path(raw: str, base_dir: Path, project_root: Path, label: str) -> Path:
    """
    Возвращает первый существующий путь из кандидатов.
    Если ничего не найдено — поднимает FileNotFoundError с перечнем попыток.
    """
    tries = _path_candidates(raw, base_dir, project_root)
    for p in tries:
        if p.exists():
            return p

    msg_lines = [f"{label} not found. raw='{raw}'. Tried:"]
    for p in tries:
        msg_lines.append(f"  - {p}")
    raise FileNotFoundError("\n".join(msg_lines))


def _parse_db_config(section: Dict[str, Any], project_root: Path) -> DatabaseConfig:
    raw_path = section.get("path", "data/trader.db")

    # DB путь лучше резолвить от project_root, чтобы cwd не влиял.
    raw = str(raw_path)
    raw_norm = raw.replace("\\", "/")
    if Path(raw).is_absolute():
        db_path = Path(raw).expanduser().resolve()
    else:
        # поддержка и "data/trader.db" и "config/../data/.."
        db_path = (project_root / raw_norm).expanduser().resolve()

    return DatabaseConfig(path=db_path)


def _parse_runtime_config(section: Dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        mode=str(section.get("mode", "offline")).lower(),
        environment=str(section.get("environment", "dev")),
        loop_sleep_seconds=int(section.get("loop_sleep_seconds", 5)),
        sheets_sync_interval_seconds=int(section.get("sheets_sync_interval_seconds", 60)),
        notify_flush_interval_seconds=int(section.get("notify_flush_interval_seconds", 60)),
        risk_snapshot_refresh_seconds=int(section.get("risk_snapshot_refresh_seconds", 30)),
    )


def _parse_risk_config(root: Dict[str, Any], base_dir: Path, project_root: Path) -> Tuple[RiskConfig, Path]:
    risk_section = _get_section(root, "risk")

    # Важно: base_dir обычно ".../config". Поэтому дефолт логичнее "risk_config.yaml",
    # но для обратной совместимости поддерживаем и "config/risk_config.yaml".
    raw_path = str(risk_section.get("config_path", "risk_config.yaml"))

    path = _resolve_existing_path(raw_path, base_dir, project_root, label="Risk config file")
    cfg = RiskConfig.from_yaml(path)
    return cfg, path


def _parse_ibkr_config(root: Dict[str, Any]) -> IBKRConnectionParams:
    sec = _get_section(root, "ibkr")
    return IBKRConnectionParams(
        host=str(sec.get("host", "127.0.0.1")),
        port=int(sec.get("port", 7497)),
        client_id=int(sec.get("client_id", 1)),
        connect_timeout=float(sec.get("connect_timeout", 10.0)),
    )


def _parse_sheets_config(root: Dict[str, Any], base_dir: Path, project_root: Path) -> Optional[SheetsConfig]:
    sec = _get_section(root, "sheets")

    # Если нет spreadsheet_id — считаем, что Sheets отключены
    spreadsheet_id = sec.get("spreadsheet_id")
    if not spreadsheet_id:
        return None

    raw_json = str(sec.get("service_account_json", "service_account.json"))
    json_path = _resolve_existing_path(raw_json, base_dir, project_root, label="Sheets service_account_json")

    trades_prefix = sec.get("trades_prefix", "Trades_")
    template_title = sec.get("template_trades_sheet")

    return SheetsConfig(
        spreadsheet_id=str(spreadsheet_id),
        service_account_json=json_path,
        trades_prefix=str(trades_prefix),
        template_trades_sheet=str(template_title) if template_title else None,
    )


def _parse_telegram_config(root: Dict[str, Any]) -> Optional[TelegramNotifyConfig]:
    sec = _get_section(root, "telegram")
    bot_token = sec.get("bot_token")
    chat_id = sec.get("chat_id")

    # Если не заданы основные поля — Telegram отключён
    if not bot_token or not chat_id:
        return None

    return TelegramNotifyConfig(
        bot_token=str(bot_token),
        chat_id=str(chat_id),
        batch_interval_seconds=int(sec.get("batch_interval_seconds", 600)),
        max_batch_notifications=int(sec.get("max_batch_notifications", 50)),
        normal_disable_notification=bool(sec.get("normal_disable_notification", True)),
    )


def _parse_envelopes_config(root: Dict[str, Any], base_dir: Path, project_root: Path) -> Optional[EnvelopesConfig]:
    sec = _get_section(root, "envelopes")

    inbox_raw = sec.get("inbox_path")
    if not inbox_raw:
        return None  # секция отсутствует или не настроена

    done_raw = sec.get("done_path", "envelopes_done")
    bad_raw = sec.get("bad_path", "envelopes_bad")

    def _resolve_dir(raw: str) -> Path:
        raw_s = str(raw).replace("\\", "/")
        p = Path(raw_s).expanduser()
        if p.is_absolute():
            return p.resolve()

        # 1) если каталог существует в base_dir/config, 2) если существует в project_root, иначе project_root
        candidates = _path_candidates(raw_s, base_dir, project_root)
        for c in candidates:
            if c.exists():
                return c.resolve()
        return (project_root / raw_s).resolve()

    inbox = _resolve_dir(str(inbox_raw))
    done = _resolve_dir(str(done_raw))
    bad = _resolve_dir(str(bad_raw))

    try:
        m = int(sec.get("max_files_per_tick", 10))
    except Exception:
        m = 10
    m = max(1, min(1000, m))

    return EnvelopesConfig(
        inbox_path=inbox,
        done_path=done,
        bad_path=bad,
        max_files_per_tick=m,
    )


# ==========================
#  Публичный API
# ==========================


def load_app_config(path: Path | str = "config/app.toml") -> AppConfig:
    """
    Загружает TOML-конфиг и возвращает AppConfig.
    """
    cfg_path = Path(path).expanduser().resolve()
    root = _load_toml(cfg_path)

    base_dir = cfg_path.parent
    project_root = _project_root_from_cfg(cfg_path)

    db_cfg = _parse_db_config(_get_section(root, "db"), project_root)
    runtime_cfg = _parse_runtime_config(_get_section(root, "runtime"))

    risk_cfg, risk_path = _parse_risk_config(root, base_dir, project_root)
    ibkr_cfg = _parse_ibkr_config(root)
    sheets_cfg = _parse_sheets_config(root, base_dir, project_root)
    tg_cfg = _parse_telegram_config(root)
    env_cfg = _parse_envelopes_config(root, base_dir, project_root)

    app_cfg = AppConfig(
        db=db_cfg,
        runtime=runtime_cfg,
        risk=risk_cfg,
        risk_config_path=risk_path,
        ibkr=ibkr_cfg,
        sheets=sheets_cfg,
        telegram=tg_cfg,
        envelopes=env_cfg,
    )

    logger.info(
        "AppConfig loaded from %s (env=%s, db=%s, ibkr=%s:%s)",
        cfg_path,
        app_cfg.runtime.environment,
        app_cfg.db.path,
        app_cfg.ibkr.host,
        app_cfg.ibkr.port,
    )

    if app_cfg.sheets:
        logger.info(
            "Google Sheets integration enabled (spreadsheet_id=%s)",
            app_cfg.sheets.spreadsheet_id,
        )
    else:
        logger.info("Google Sheets integration DISABLED (no [sheets] section or spreadsheet_id).")

    if app_cfg.telegram:
        logger.info("Telegram notifications ENABLED (chat_id=%s).", app_cfg.telegram.chat_id)
    else:
        logger.info("Telegram notifications DISABLED (no [telegram] section or bot_token/chat_id).")

    if app_cfg.envelopes:
        logger.info(
            "Envelope ingress ENABLED (inbox=%s, done=%s, bad=%s, max_files_per_tick=%s).",
            app_cfg.envelopes.inbox_path,
            app_cfg.envelopes.done_path,
            app_cfg.envelopes.bad_path,
            app_cfg.envelopes.max_files_per_tick,
        )
    else:
        logger.info("Envelope ingress DISABLED (no [envelopes] section or inbox_path).")

    return app_cfg
