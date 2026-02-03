# app/notify.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests  # type: ignore

from app.db import Database
from app import dao
from app.ids import make_notification_id

from core.schemas import (
    NotificationSeverity,
    NotificationType,
    TelegramNotification,
)

logger = logging.getLogger(__name__)


@dataclass
class TelegramNotifyConfig:
    """
    Конфиг для Telegram-уведомлений.

    bot_token    — токен бота.
    chat_id      — ID чата (или @username/канал, но лучше numeric ID).
    batch_interval_seconds — минимальный интервал между отправкой
                             НЕкритических батчей (по ТЗ: ≤ 1 раз / 10 минут).
    max_batch_notifications — максимум уведомлений за один батч.
    normal_disable_notification — отправлять ли обычные батчи «без звука».
    """

    bot_token: str
    chat_id: str
    batch_interval_seconds: int = 600
    max_batch_notifications: int = 50
    normal_disable_notification: bool = True


class NotifyError(RuntimeError):
    """Ошибки слоя уведомлений."""
    pass


class Notifier:
    """
    Слой Telegram-уведомлений.

    Умеет:
    - записывать уведомления в БД (telegram_notifications),
    - немедленно отправлять критические (CRITICAL),
    - батчить не-критические (INFO/WARNING) не чаще, чем раз в N секунд,
      собирая несколько записей в один message.

    Внешний код:
        notifier = Notifier(cfg)
        notifier.send_critical(...)
        notifier.enqueue_normal(...)
        notifier.flush_normal_batch(db)   # вызывать периодически в сервисе
    """

    FLAG_LAST_BATCH_SENT = "tg_last_batch_sent_utc"

    def __init__(self, config: TelegramNotifyConfig) -> None:
        self._cfg = config

    # ----------------------
    #  Вспомогательные методы
    # ----------------------

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _send_text(
        self,
        text: str,
        *,
        disable_notification: bool,
    ) -> None:
        """
        Низкоуровневая отправка сообщения в Telegram.
        """
        url = f"https://api.telegram.org/bot{self._cfg.bot_token}/sendMessage"
        payload = {
            "chat_id": self._cfg.chat_id,
            "text": text,
            "disable_notification": disable_notification,
            "parse_mode": "Markdown",  # чуть-чуть форматирования
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
        except Exception as exc:
            logger.exception("Notifier._send_text: request error: %s", exc)
            raise NotifyError(f"Telegram request error: {exc}") from exc

        if resp.status_code != 200:
            logger.error(
                "Notifier._send_text: HTTP %s from Telegram: %s",
                resp.status_code,
                resp.text[:500],
            )
            raise NotifyError(f"Telegram HTTP error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        if not data.get("ok"):
            logger.error("Notifier._send_text: Telegram API error: %s", data)
            raise NotifyError(f"Telegram API error: {data}")

    def _format_single_notification(self, notif: TelegramNotification) -> str:
        """
        Формат для одиночного (критического) уведомления.
        """
        parts: list[str] = []

        prefix = {
            NotificationSeverity.CRITICAL: "🚨 *CRITICAL*",
            NotificationSeverity.WARNING: "⚠️ *WARNING*",
            NotificationSeverity.INFO: "ℹ️ *INFO*",
        }.get(notif.severity, "ℹ️")

        parts.append(f"{prefix} [{notif.type.value}]")

        if notif.symbol:
            parts.append(f" *{notif.symbol}*")

        parts.append("\n")
        parts.append(notif.message)

        # немножко контекста
        ctx_lines: list[str] = []
        if notif.signal_id:
            ctx_lines.append(f"`signal_id={notif.signal_id}`")
        if notif.order_id:
            ctx_lines.append(f"`order_id={notif.order_id}`")
        if notif.trade_id:
            ctx_lines.append(f"`trade_id={notif.trade_id}`")

        if ctx_lines:
            parts.append("\n\n")
            parts.append(" / ".join(ctx_lines))

        return "".join(parts)

    def _format_batch(self, notifs: List[TelegramNotification]) -> str:
        """
        Формат батч-сообщения для не-критических уведомлений.
        """
        if not notifs:
            return ""

        header = "📊 *SenseiTrader — батч обновлений*\n"
        lines: list[str] = [header, ""]

        for n in notifs:
            emoji = {
                NotificationSeverity.CRITICAL: "🚨",
                NotificationSeverity.WARNING: "⚠️",
                NotificationSeverity.INFO: "•",
            }.get(n.severity, "•")

            base = f"{emoji} [{n.type.value}]"
            if n.symbol:
                base += f" *{n.symbol}*"
            base += f": {n.message}"

            lines.append(base)

        return "\n".join(lines)

    # ----------------------
    #  Создание доменного уведомления
    # ----------------------

    def _build_notification(
        self,
        notif_type: NotificationType,
        severity: NotificationSeverity,
        message: str,
        *,
        symbol: Optional[str] = None,
        signal_id: Optional[str] = None,
        order_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> TelegramNotification:
        now = self._now_utc()
        notification_id = make_notification_id()
        return TelegramNotification(
            notification_id=notification_id,
            ts_utc=now,
            type=notif_type,
            severity=severity,
            message=message,
            symbol=symbol,
            signal_id=signal_id,
            order_id=order_id,
            trade_id=trade_id,
            extra=extra or {},
        )

    # ----------------------
    #  Публичное API
    # ----------------------

    def send_critical(
        self,
        db: Database,
        notif_type: NotificationType,
        message: str,
        *,
        symbol: Optional[str] = None,
        signal_id: Optional[str] = None,
        order_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> TelegramNotification:
        """
        Создаёт CRITICAL-уведомление:
        - сохраняет в БД,
        - немедленно отправляет в Telegram,
        - помечает как отправленное или с ошибкой.
        """

        notif = self._build_notification(
            notif_type=notif_type,
            severity=NotificationSeverity.CRITICAL,
            message=message,
            symbol=symbol,
            signal_id=signal_id,
            order_id=order_id,
            trade_id=trade_id,
            extra=extra,
        )
        dao.save_notification(db, notif)

        text = self._format_single_notification(notif)

        try:
            self._send_text(text, disable_notification=False)
        except NotifyError as exc:
            logger.error(
                "Notifier.send_critical: failed to send critical notification_id=%s: %s",
                notif.notification_id,
                exc,
            )
            dao.mark_notification_error(db, notif.notification_id, str(exc))
            return notif

        dao.mark_notification_sent(db, notif.notification_id, self._now_utc())
        return notif

    def enqueue_normal(
        self,
        db: Database,
        notif_type: NotificationType,
        severity: NotificationSeverity,
        message: str,
        *,
        symbol: Optional[str] = None,
        signal_id: Optional[str] = None,
        order_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> TelegramNotification:
        """
        Создаёт не-критическое уведомление (INFO/WARNING) и только сохраняет его в БД.
        Отправка в Telegram произойдёт при вызове flush_normal_batch().
        """

        if severity == NotificationSeverity.CRITICAL:
            raise ValueError("enqueue_normal cannot be used with CRITICAL severity")

        notif = self._build_notification(
            notif_type=notif_type,
            severity=severity,
            message=message,
            symbol=symbol,
            signal_id=signal_id,
            order_id=order_id,
            trade_id=trade_id,
            extra=extra,
        )
        dao.save_notification(db, notif)
        return notif

    def flush_normal_batch(
        self,
        db: Database,
        *,
        now_utc: Optional[datetime] = None,
    ) -> int:
        """
        Отправляет батч не-критических уведомлений (INFO/WARNING), если:
        - с последнего батча прошло >= batch_interval_seconds,
        - в очереди есть неотправленные записи.

        Возвращает количество уведомлений, попавших в батч.
        """
        if now_utc is None:
            now_utc = self._now_utc()

        # Проверяем интервал по runtime_flags
        last_sent_str = dao.get_flag(db, self.FLAG_LAST_BATCH_SENT)
        if last_sent_str:
            try:
                last_sent = datetime.fromisoformat(last_sent_str)
                # считаем, что в флаге хранится UTC без tzinfo либо с tz → приводим
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                else:
                    last_sent = last_sent.astimezone(timezone.utc)

                delta = now_utc - last_sent
                if delta < timedelta(seconds=self._cfg.batch_interval_seconds):
                    logger.debug(
                        "Notifier.flush_normal_batch: last batch sent %s ago (< %ss), skipping.",
                        delta,
                        self._cfg.batch_interval_seconds,
                    )
                    return 0
            except Exception:
                # если флаг кривой — считаем, что батча не было
                logger.warning(
                    "Notifier.flush_normal_batch: invalid FLAG_LAST_BATCH_SENT value '%s', ignoring.",
                    last_sent_str,
                )

        # Забираем несообщённые не-критические уведомления
        notifs = dao.list_unsent_notifications(
            db,
            severity_filter="NONCRITICAL",
            limit=self._cfg.max_batch_notifications,
        )
        if not notifs:
            return 0

        text = self._format_batch(notifs)
        if not text.strip():
            return 0

        try:
            self._send_text(
                text,
                disable_notification=self._cfg.normal_disable_notification,
            )
        except NotifyError as exc:
            logger.error(
                "Notifier.flush_normal_batch: failed to send batch of %s notifications: %s",
                len(notifs),
                exc,
            )
            # помечаем всем ошибку, но не удаляем
            for n in notifs:
                dao.mark_notification_error(db, n.notification_id, str(exc))
            return 0

        # Успех: помечаем все уведомления как отправленные
        sent_ts = now_utc
        for n in notifs:
            dao.mark_notification_sent(db, n.notification_id, sent_ts)

        # Обновляем флаг времени последнего батча
        dao.set_flag(db, self.FLAG_LAST_BATCH_SENT, sent_ts.replace(tzinfo=None).isoformat(timespec="seconds"))

        logger.info(
            "Notifier.flush_normal_batch: sent batch of %s notifications.",
            len(notifs),
        )
        return len(notifs)

# ============================================
# OfflineNotifier — заглушка для режима offline
# ============================================

import logging
from core.schemas import NotificationType, NotificationSeverity

class OfflineNotifier:
    """
    Offline-версия уведомителя:
    - не делает HTTP-запросов в Telegram
    - просто пишет события в лог.
    Интерфейс совместим с Notifier, чтобы service.py мог работать одинаково.
    """

    def __init__(self) -> None:
        self._log = logging.getLogger("sensei.offline_notifier")

    def enqueue_normal(
        self,
        db,
        notif_type: NotificationType,
        severity: NotificationSeverity,
        message: str,
        **kwargs,
    ) -> None:
        """
        В обычном режиме Notifier складывает уведомления в БД и потом отправляет их батчем.
        В offline-режиме просто логируем факт.
        """
        self._log.info(
            {
                "event": "offline_notifier.enqueue_normal",
                "type": notif_type.value if hasattr(notif_type, "value") else str(notif_type),
                "severity": severity.value if hasattr(severity, "value") else str(severity),
                "message": message,
                "extra": kwargs,
            }
        )

    def flush_normal_batch(self, db) -> None:
        """
        В реальном Notifier здесь бы отправлялся батч в Telegram.
        В offline — ничего не делаем.
        """
        self._log.debug({"event": "offline_notifier.flush_normal_batch"})

    def send_critical(
        self,
        db,
        notif_type: NotificationType,
        message: str,
        **kwargs,
    ) -> None:
        """
        Критические уведомления в offline-режиме тоже только логируются.
        """
        self._log.warning(
            {
                "event": "offline_notifier.send_critical",
                "type": notif_type.value if hasattr(notif_type, "value") else str(notif_type),
                "message": message,
                "extra": kwargs,
            }
        )
