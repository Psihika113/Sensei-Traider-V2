# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sqlite3, threading, time, random, contextlib
from typing import Callable, Dict, List, Tuple, Optional

# ---------- вспомогалки ----------
def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def next_delay_sec(attempts: int) -> int:
    # экспоненциальный backoff: 5, 15, 60, 180, 600, 900... (cap 900)
    base = [5, 15, 60, 180, 600][min(attempts, 4)]
    # джиттер ±20%
    jitter = int(base * (0.8 + 0.4 * random.random()))
    return min(jitter, 900)

# ---------- Outbox (работает из любого потока) ----------
class Outbox:
    """
    Outbox на SQLite с плановыми повторами.
    Таблица 'outbox' должна иметь поля:
      id, channel TEXT, payload TEXT, created_ts_utc TEXT, attempts INTEGER,
      next_try_utc TEXT, last_error TEXT, max_attempts INTEGER
    """
    def __init__(self,
                 conn: Optional[sqlite3.Connection] = None,
                 db_path: Optional[str] = None,
                 logger: Optional[object] = None):
        self._external_conn = conn is not None
        if conn is None:
            if not db_path:
                raise ValueError("Outbox requires either conn or db_path")
            # отдельное соединение для потока воркера
            conn = sqlite3.connect(db_path, timeout=10, isolation_level=None, check_same_thread=False)
        self.conn = conn
        self.logger = logger
        self._lock = threading.RLock()  # защищаем соединение, если оно расшарено

        # включим WAL и busy_timeout
        with self.conn:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA busy_timeout=10000;")

    def _log(self, level: str, msg: str, **fields):
        if not self.logger:
            return
        text = f"{msg} | {json.dumps(fields, ensure_ascii=False)}" if fields else msg
        getattr(self.logger, level, self.logger.info)(text)

    def enqueue(self, channel: str, payload: dict, max_attempts: int = 12) -> None:
        rec = (
            channel,
            json.dumps(payload, ensure_ascii=False),
            utc_now_iso(),
            0,
            utc_now_iso(),
            None,
            max_attempts
        )
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO outbox(channel,payload,created_ts_utc,attempts,next_try_utc,last_error,max_attempts)"
                " VALUES(?,?,?,?,?,?,?)",
                rec
            )
        self._log("info", "outbox.enqueue", channel=channel)

    def fetch_due_batch(self, limit: int = 50) -> List[Tuple[int, str, dict, int, int]]:
        with self._lock, contextlib.closing(self.conn.cursor()) as cur:
            cur.execute(
                "SELECT id, channel, payload, attempts, max_attempts "
                "FROM outbox WHERE next_try_utc<=? ORDER BY id LIMIT ?",
                (utc_now_iso(), limit)
            )
            rows = cur.fetchall()
        out: List[Tuple[int, str, dict, int, int]] = []
        for rid, ch, pl, att, max_att in rows:
            try:
                out.append((rid, ch, json.loads(pl), att, max_att))
            except Exception:
                out.append((rid, ch, {"raw": pl}, att, max_att))
        return out

    def delete_ids(self, ids: List[int]) -> None:
        if not ids: return
        placeholders = ",".join("?" * len(ids))
        with self._lock, self.conn:
            self.conn.execute(f"DELETE FROM outbox WHERE id IN ({placeholders})", ids)

    def reschedule_ids(self, ids: List[int], errors: Dict[int, str]) -> None:
        if not ids: return
        now = utc_now_iso()
        with self._lock, self.conn:
            for oid in ids:
                # получаем текущие попытки и max_attempts
                row = self.conn.execute("SELECT attempts, max_attempts FROM outbox WHERE id=?", (oid,)).fetchone()
                if not row:
                    continue
                attempts, max_attempts = row
                attempts += 1
                if attempts >= max_attempts:
                    # dead-letter: удалим запись; эскалация будет сделана выше по стеку
                    self.conn.execute("DELETE FROM outbox WHERE id=?", (oid,))
                else:
                    delay = next_delay_sec(attempts)
                    next_ts = time.gmtime(time.time() + delay)
                    next_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", next_ts)
                    self.conn.execute(
                        "UPDATE outbox SET attempts=?, next_try_utc=?, last_error=? WHERE id=?",
                        (attempts, next_iso, errors.get(oid), oid)
                    )

# ---------- OutboxWorker ----------
class OutboxWorker:
    """
    Фоновый воркер: вытягивает due-сообщения и доставляет через callbacks:
      callbacks = {"tg": callable(dict)->bool, "sheets": callable(dict)->bool}
    Эскалация: on_dead_letter(channel, payload, attempts) — опционально.
    """
    def __init__(self,
                 outbox: Outbox,
                 callbacks: Dict[str, Callable[[dict], bool]],
                 logger: Optional[object] = None,
                 interval_idle_sec: int = 5,
                 max_batch: int = 50,
                 on_dead_letter: Optional[Callable[[str, dict, int], None]] = None):
        self.outbox = outbox
        self.callbacks = callbacks
        self.logger = logger
        self.interval_idle_sec = interval_idle_sec
        self.max_batch = max_batch
        self.on_dead_letter = on_dead_letter

        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._loop, daemon=True)

    def start(self): self._thr.start()
    def stop(self, join: bool = True):
        self._stop.set()
        if join and self._thr.is_alive():
            self._thr.join(timeout=self.interval_idle_sec + 1)

    def _log(self, level: str, msg: str, **fields):
        if not self.logger:
            return
        text = f"{msg} | {json.dumps(fields, ensure_ascii=False)}" if fields else msg
        getattr(self.logger, level, self.logger.info)(text)

    def _loop(self):
        while not self._stop.is_set():
            batch = self.outbox.fetch_due_batch(self.max_batch)
            if not batch:
                self._stop.wait(self.interval_idle_sec)
                continue

            ok_ids: List[int] = []
            fail_ids: List[int] = []
            errors: Dict[int, str] = {}
            dead_letters: List[Tuple[str, dict, int]] = []

            for rid, channel, payload, attempts, max_attempts in batch:
                cb = self.callbacks.get(channel)
                if not cb:
                    # нет обработчика — считаем доставленным (или можно эскалировать)
                    ok_ids.append(rid)
                    self._log("warning", "outbox.no_handler", id=rid, channel=channel)
                    continue
                try:
                    delivered = cb(payload)
                except Exception as e:
                    delivered = False
                    errors[rid] = f"cb_exc:{e}"
                    self._log("error", "outbox.cb_exception", id=rid, channel=channel, err=str(e))

                if delivered:
                    ok_ids.append(rid)
                else:
                    # если следующая попытка превысит лимит — dead-letter
                    if attempts + 1 >= max_attempts:
                        dead_letters.append((channel, payload, attempts + 1))
                        ok_ids.append(rid)  # удаляем из очереди
                    else:
                        fail_ids.append(rid)
                        errors.setdefault(rid, "deliver_failed")

            if ok_ids:
                self.outbox.delete_ids(ok_ids)
            if fail_ids:
                self.outbox.reschedule_ids(fail_ids, errors)

            # эскалация dead-letter
            for ch, payload, att in dead_letters:
                self._log("critical", "outbox.dead_letter", channel=ch, attempts=att)
                if self.on_dead_letter:
                    try:
                        self.on_dead_letter(ch, payload, att)
                    except Exception as e:
                        self._log("error", "outbox.dead_letter_cb_exc", err=str(e))
