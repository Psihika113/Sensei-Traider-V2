# app/ids.py
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Final


# Можно при необходимости менять длину хэшей,
# главное — не трогать это без миграции данных.
ORDER_ID_HASH_LEN: Final[int] = 32      # 32 hex-символа (128 бит)
TRADE_ID_HASH_LEN: Final[int] = 24      # 24 hex-символа
NOTIF_ID_HASH_LEN: Final[int] = 24      # 24 hex-символа


def _to_utc_iso_truncated(ts_utc: datetime) -> str:
    """
    Приводит datetime к UTC и обрезает микросекунды.
    Возвращает ISO8601-строку.

    Если tzinfo отсутствует — считаем, что это уже UTC.
    """
    if ts_utc.tzinfo is None:
        dt_utc = ts_utc
    else:
        dt_utc = ts_utc.astimezone(timezone.utc)

    return dt_utc.replace(microsecond=0).isoformat(timespec="seconds")


def make_signal_id() -> str:
    """
    Генерация ID для Signal.
    В ТЗ указан uuid-v7 или аналог — здесь используем uuid4,
    что даёт достаточно уникальный и удобный идентификатор.
    При необходимости позднее можно заменить на uuid6/7/ulid.
    """
    return str(uuid.uuid4())


def make_order_id(signal_id: str, symbol: str, ts_utc: datetime) -> str:
    """
    Детерминированный ID ордера:
    order_id = sha256(signal_id | symbol | ts_iso_utc)[:ORDER_ID_HASH_LEN]

    Таким образом:
    - повторная попытка построить ордер по тому же сигналу
      даёт тот же order_id (идемпотентность);
    - при необходимости длину можно менять через ORDER_ID_HASH_LEN,
      но это потребует миграции существующих данных.
    """
    symbol_norm = symbol.strip().upper()
    ts_str = _to_utc_iso_truncated(ts_utc)

    canonical = f"{signal_id}|{symbol_norm}|{ts_str}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:ORDER_ID_HASH_LEN]


def make_trade_id(order_id: str) -> str:
    """
    Логический ID сделки, который можно использовать в Sheets и отчётах.
    Для v1 считаем, что одна сделка = один ордер (parent+OCO).
    Поэтому trade_id детерминированно зависит только от order_id.
    """
    canonical = f"TRADE|{order_id}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:TRADE_ID_HASH_LEN]


def make_notification_id() -> str:
    """
    ID уведомления в Telegram.
    Для уведомлений нам не нужна детерминированность по данным события,
    достаточно уникальности (для идемпотентности отправки).
    Используем uuid4 с опциональным укорочением.
    """
    raw = uuid.uuid4().hex  # 32 hex-символа
    return raw[:NOTIF_ID_HASH_LEN]
