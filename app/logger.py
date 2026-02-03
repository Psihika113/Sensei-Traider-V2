# app/logger.py
import json, logging, logging.handlers, os, sys, time
from typing import Any, Dict

LOG_DIR = os.getenv("ST_LOG_DIR", "logs")
LOG_FILE = os.getenv("ST_LOG_FILE", "sensei.log")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, LOG_FILE)

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # спец-поле для «критики» без отдельного файла
        if getattr(record, "critical_now", False):
            payload["critical_now"] = True
        return json.dumps(payload, ensure_ascii=False)

def build_logger(name: str = "sensei", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)

    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    # дублирование в stdout для контейнеров/консолей
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(JsonFormatter())
    sh.setLevel(level)
    logger.addHandler(sh)

    logger.debug(json.dumps({"init": "logger", "path": LOG_PATH}))
    return logger

# удобные функции
_log = build_logger()

def info(msg: str, **kw): _log.info(msg, extra=kw)
def warn(msg: str, **kw): _log.warning(msg, extra=kw)
def error(msg: str, **kw): _log.error(msg, extra=kw)
def critical(msg: str, notify: bool = True, **kw):
    kw.setdefault("critical_now", True)
    _log.critical(msg, extra=kw)
    return notify  # вызывающий код может отправить TG-алерт, если True
