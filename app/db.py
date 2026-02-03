# app/db.py
from __future__ import annotations

import sqlite3
import threading
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable, Optional


class DatabaseError(RuntimeError):
    """Обёртка для ошибок работы с БД."""
    pass


class Database:
    """
    Обёртка над sqlite3 с:
    - включённым WAL;
    - foreign_keys=ON;
    - row_factory=sqlite3.Row;
    - примитивной блокировкой на время транзакции.

    ВАЖНО (совместимость):
    В проекте встречаются старые вызовы db.fetch_one/db.fetch_all.
    Эти методы добавлены как алиасы к query_one/query_all, но с поддержкой
    sqlite-параметров как tuple/list ИЛИ dict (named placeholders).
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """
        Открывает соединение, если ещё не открыто.
        Можно вызывать повторно — повторные вызовы ничего не делают.
        """
        if self._conn is not None:
            return

        # Убедимся, что каталог для БД существует
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            self._db_path.as_posix(),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            isolation_level=None,    # будем явно управлять транзакциями (BEGIN/COMMIT)
            check_same_thread=False  # допускаем использование из разных потоков под нашим lock
        )
        conn.row_factory = sqlite3.Row

        # Базовые PRAGMA
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Контекстный менеджер транзакции:
        - берёт lock, чтобы один писатель;
        - делает BEGIN IMMEDIATE (блокирует на запись);
        - COMMIT при успехе, ROLLBACK при исключении.
        """
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE;")
                yield cursor
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                raise DatabaseError(f"Database transaction error: {exc}") from exc
            finally:
                cursor.close()

    def execute(self, sql: str, params: Any = None):
        """
        Выполнить запрос и вернуть cursor.

        Важно: возвращаем именно cursor, а не rowcount, потому что:
        - миграции/DAO-слой часто ожидают, что можно будет вызвать fetchall();
        - Health/DAO-слой тоже часто итерируется по cursor.
        """
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")

        if params is None:
            cur = self._conn.execute(sql)
        else:
            cur = self._conn.execute(sql, params)

        self._conn.commit()
        return cur

    def query_one(
        self,
        sql: str,
        params: Iterable[Any] | None = None,
    ) -> Optional[sqlite3.Row]:
        """
        Выполнить SELECT и вернуть одну строку (или None).
        tuple/list параметры (позиционные).
        """
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")

        cursor = self._conn.cursor()
        try:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, tuple(params))
            row = cursor.fetchone()
            return row
        except Exception as exc:
            raise DatabaseError(f"Database query_one error: {exc}") from exc
        finally:
            cursor.close()

    def query_all(
        self,
        sql: str,
        params: Iterable[Any] | None = None,
    ) -> list[sqlite3.Row]:
        """
        Выполнить SELECT и вернуть список строк.
        tuple/list параметры (позиционные).
        """
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")

        cursor = self._conn.cursor()
        try:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return list(rows)
        except Exception as exc:
            raise DatabaseError(f"Database query_all error: {exc}") from exc
        finally:
            cursor.close()

    # ---------------------------------------------------------------------
    # Compatibility layer (старые вызовы в кодовой базе)
    # ---------------------------------------------------------------------

    def fetch_one(self, sql: str, params: Any = None) -> Optional[sqlite3.Row]:
        """
        Совместимость со старым кодом.
        Поддерживает params как tuple/list (позиционные) или dict (именованные).
        """
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")

        cursor = self._conn.cursor()
        try:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            return cursor.fetchone()
        except Exception as exc:
            raise DatabaseError(f"Database fetch_one error: {exc}") from exc
        finally:
            cursor.close()

    def fetch_all(self, sql: str, params: Any = None) -> list[sqlite3.Row]:
        """
        Совместимость со старым кодом.
        Поддерживает params как tuple/list (позиционные) или dict (именованные).
        """
        if self._conn is None:
            raise DatabaseError("Database is not connected. Call db.connect() first.")

        cursor = self._conn.cursor()
        try:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            return list(cursor.fetchall())
        except Exception as exc:
            raise DatabaseError(f"Database fetch_all error: {exc}") from exc
        finally:
            cursor.close()


def init_schema(db: Database, schema_path: str) -> None:
    """
    Apply schema.sql safely.
    - Supports multi-line statements (VIEW, TRIGGER, etc.)
    - Ignores BEGIN/COMMIT/END TRANSACTION if present in the file
    """
    path = Path(schema_path)
    if not path.exists():
        raise DatabaseError(f"Schema file not found: {schema_path}")

    # Read UTF-8 (with BOM support)
    sql_text = path.read_text(encoding="utf-8-sig")

    # Strip explicit transaction control lines (we control commits from Python side)
    sql_text = re.sub(r"(?im)^\s*BEGIN\s+TRANSACTION\s*;\s*$", "", sql_text)
    sql_text = re.sub(r"(?im)^\s*END\s+TRANSACTION\s*;\s*$", "", sql_text)
    sql_text = re.sub(r"(?im)^\s*COMMIT\s*;\s*$", "", sql_text)
    sql_text = re.sub(r"(?im)^\s*BEGIN\s*;\s*$", "", sql_text)

    # Execute as a script (SQLite will handle statement boundaries correctly)
    with db._lock:
        try:
            db.conn.executescript(sql_text)
        except Exception as exc:
            raise DatabaseError(f"Failed to apply schema: {exc}") from exc
