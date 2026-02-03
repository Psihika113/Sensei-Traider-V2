# -*- coding: utf-8 -*-
# app/commands.py — Telegram commands poller + KillSwitch (+ LIVE arm/disarm)

from __future__ import annotations

import threading
import time
import requests
from typing import Callable, Optional, Dict, Any


class KillSwitch:
    def __init__(self):
        self._on = False
        self._lock = threading.Lock()

    def on(self):
        with self._lock:
            self._on = True

    def off(self):
        with self._lock:
            self._on = False

    def is_on(self) -> bool:
        with self._lock:
            return self._on


class CommandsPoller:
    """
    Команды:
      /status
      /pause
      /resume
      /arm     (только если передан set_live_armed)
      /disarm  (только если передан set_live_armed)
      /logs
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        logger,
        get_status: Callable[[], Dict[str, Any]],
        kill_switch: KillSwitch,
        poll_interval_sec: int = 2,
        *,
        set_live_armed: Optional[Callable[[bool], None]] = None,
        get_live_armed: Optional[Callable[[], bool]] = None,
    ):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.logger = logger
        self.get_status = get_status
        self.kill = kill_switch
        self.poll_interval = max(1, int(poll_interval_sec))

        self.set_live_armed = set_live_armed
        self.get_live_armed = get_live_armed

        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None
        self._offset = 0

    def start(self):
        if self._th and self._th.is_alive():
            return
        self._th = threading.Thread(target=self._loop, name="tg-commands", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()
        if self._th and self._th.is_alive():
            self._th.join(timeout=3.0)

    def _loop(self):
        while not self._stop.is_set():
            try:
                updates = self._get_updates(timeout=self.poll_interval + 1)
                for upd in updates:
                    self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
                    msg = upd.get("message") or {}
                    chat = msg.get("chat", {})
                    if str(chat.get("id")) != self.chat_id:
                        continue
                    text = (msg.get("text") or "").strip()
                    if not text.startswith("/"):
                        continue
                    self._handle_command(text)
            except Exception as e:
                self.logger.error({"event": "tg.poller_error", "err": str(e)})
                time.sleep(1.0)

    def _get_updates(self, timeout: int):
        params = {"timeout": timeout, "offset": self._offset}
        r = requests.get(self.base + "/getUpdates", params=params, timeout=timeout + 2)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])

    def _send(self, text: str, disable_notification: bool = True):
        try:
            r = requests.post(
                self.base + "/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "disable_notification": disable_notification},
                timeout=5,
            )
            r.raise_for_status()
        except Exception as e:
            self.logger.error({"event": "tg.send_error", "err": str(e)})

    def _handle_command(self, text: str):
        cmd = text.split()[0].lower().strip()

        if cmd == "/status":
            st = self.get_status() or {}
            live_line = ""
            if "live_armed" in st:
                live_line = f"• LIVE armed: {st.get('live_armed')}\n"

            pretty = (
                "🧠 SenseiTrader — status\n"
                f"• mode: {st.get('mode')}\n"
                f"• IBKR connected: {st.get('ib_ready')}\n"
                f"• Sheets ready: {st.get('sheets_ready')}\n"
                f"• TG enabled: {st.get('tg_enabled')}\n"
                f"• Queue size: {st.get('queue_size')}\n"
                f"• Kill-switch: {st.get('kill_switch')}\n"
                + live_line +
                f"• Time(UTC): {st.get('time_utc')}\n"
            )
            self._send(pretty, disable_notification=True)
            return

        if cmd == "/pause":
            self.kill.on()
            self._send("⏸ Trading paused (kill-switch ON).", disable_notification=False)
            return

        if cmd == "/resume":
            self.kill.off()
            self._send("▶️ Trading resumed (kill-switch OFF).", disable_notification=False)
            return

        if cmd == "/arm":
            if self.set_live_armed is None:
                self._send("ARM is not configured in this build.", True)
                return
            try:
                self.set_live_armed(True)
                self._send("✅ LIVE armed = ON. Trading allowed.", disable_notification=False)
            except Exception as e:
                self._send(f"ARM failed: {e}", disable_notification=False)
            return

        if cmd == "/disarm":
            if self.set_live_armed is None:
                self._send("DISARM is not configured in this build.", True)
                return
            try:
                self.set_live_armed(False)
                self._send("🛑 LIVE armed = OFF. Trading blocked.", disable_notification=False)
            except Exception as e:
                self._send(f"DISARM failed: {e}", disable_notification=False)
            return

        if cmd == "/logs":
            self._send("ℹ️ Logs: смотри локальные файлы логов (папка logs/).", True)
            return

        self._send("Unknown command. Available: /status /pause /resume /arm /disarm /logs", True)
