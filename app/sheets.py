# app/sheets.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.oauth2 import service_account  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from app.db import Database
from app import dao

logger = logging.getLogger(__name__)


# ==========================
#  Конфиг и клиент Sheets
# ==========================


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@dataclass
class SheetsConfig:
    """
    Конфигурация для работы с Google Sheets.

    spreadsheet_id         — ID таблицы (из URL).
    service_account_json   — путь к JSON-файлу сервисного аккаунта.
    trades_prefix          — префикс для листов сделок (по ТЗ: "Trades_YYYYMM").
    template_trades_sheet  — опционально: имя листа-шаблона для копирования шапки в новые месяцы.
    """

    spreadsheet_id: str
    service_account_json: Path
    trades_prefix: str = "Trades_"
    template_trades_sheet: Optional[str] = None


class SheetsError(RuntimeError):
    """Ошибки слоя Google Sheets."""
    pass


class SheetsClient:
    """
    Обёртка над Google Sheets API.

    В v1 отвечает за:
    - подключение;
    - создание нового листа Trades_YYYYMM (1-го числа месяца, с копированием шапки);
    - запись/апдейт строк (через payload из sheets_sync_queue);
    - обработку очереди (sheets_sync_queue в SQLite).
    """

    def __init__(self, config: SheetsConfig) -> None:
        self._cfg = config
        self._service = self._build_service()

    # ----------------------
    #  Подключение
    # ----------------------

    def _build_service(self):
        try:
            credentials = service_account.Credentials.from_service_account_file(
                self._cfg.service_account_json.as_posix(),
                scopes=SCOPES,
            )
            service = build("sheets", "v4", credentials=credentials)
            return service
        except Exception as exc:
            logger.exception("SheetsClient._build_service: failed to build Sheets service: %s", exc)
            raise SheetsError(f"Failed to build Sheets service: {exc}") from exc

    @property
    def service(self):
        return self._service

    @property
    def spreadsheet_id(self) -> str:
        return self._cfg.spreadsheet_id

    # ----------------------
    #  Вспомогательные методы
    # ----------------------

    def _execute(self, request, desc: str) -> Any:
        """
        Обёртка над request.execute() с логированием и обработкой HttpError.
        """
        try:
            logger.debug("SheetsClient._execute: %s", desc)
            return request.execute()
        except HttpError as exc:
            logger.exception("SheetsClient._execute: HttpError in %s: %s", desc, exc)
            raise SheetsError(f"Sheets API error during {desc}: {exc}") from exc
        except Exception as exc:
            logger.exception("SheetsClient._execute: unexpected error in %s: %s", desc, exc)
            raise SheetsError(f"Unexpected Sheets error during {desc}: {exc}") from exc

    # ----------------------
    #  Работа с листами
    # ----------------------

    def _get_spreadsheet_metadata(self) -> Dict[str, Any]:
        request = self._service.spreadsheets().get(spreadsheetId=self.spreadsheet_id)
        return self._execute(request, "get spreadsheet metadata")

    def _find_sheet_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        meta = self._get_spreadsheet_metadata()
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == title:
                return sheet
        return None

    def _create_sheet(self, title: str) -> int:
        """
        Создаёт новый пустой лист и возвращает sheetId.
        """
        logger.info("SheetsClient._create_sheet: creating new sheet '%s'", title)
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": title,
                        }
                    }
                }
            ]
        }
        request = self._service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body=body,
        )
        response = self._execute(request, f"addSheet '{title}'")
        replies = response.get("replies", [])
        if not replies:
            raise SheetsError(f"Failed to create sheet '{title}': no replies")

        sheet_id = replies[0]["addSheet"]["properties"]["sheetId"]
        return int(sheet_id)

    def _copy_header_from_template(
        self,
        source_title: str,
        target_title: str,
    ) -> None:
        """
        Копирует первую строку (или несколько) с заголовками из листа-шаблона
        в новый лист. В v1 предполагаем, что шапка — первая строка.
        """
        logger.info(
            "SheetsClient._copy_header_from_template: copying header from '%s' to '%s'",
            source_title,
            target_title,
        )

        # Читаем первую строку из шаблона
        range_src = f"'{source_title}'!1:1"
        request = self._service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_src,
        )
        values_resp = self._execute(request, f"read header from '{source_title}'")
        values = values_resp.get("values", [])
        if not values:
            logger.warning(
                "SheetsClient._copy_header_from_template: source sheet '%s' has no header row.",
                source_title,
            )
            return

        # Записываем в новый лист
        range_dst = f"'{target_title}'!1:1"
        body = {"values": values}
        request = self._service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_dst,
            valueInputOption="RAW",
            body=body,
        )
        self._execute(request, f"write header to '{target_title}'")

    # ----------------------
    #  Trades_YYYYMM листы
    # ----------------------

    def get_trades_sheet_title_for_date(self, d: date) -> str:
        """
        Возвращает имя листа Trades_YYYYMM для заданной даты.
        По ТЗ формат: 'Trades_YYYYMM' (например, 'Trades_202509').
        """
        return f"{self._cfg.trades_prefix}{d.year:04d}{d.month:02d}"

    def ensure_trades_sheet_for_month(self, d: date) -> str:
        """
        Гарантирует, что лист Trades_YYYYMM существует.
        Если нет — создаёт, опционально копирует шапку из шаблона.

        Возвращает title листа.
        """
        title = self.get_trades_sheet_title_for_date(d)
        existing = self._find_sheet_by_title(title)
        if existing is not None:
            return title

        # создаём новый лист
        self._create_sheet(title)

        # если указан шаблон — копируем шапку
        if self._cfg.template_trades_sheet:
            try:
                self._copy_header_from_template(self._cfg.template_trades_sheet, title)
            except SheetsError:
                # не валим весь процесс, просто логируем
                logger.exception(
                    "SheetsClient.ensure_trades_sheet_for_month: failed to copy header from template '%s'",
                    self._cfg.template_trades_sheet,
                )

        return title

    # ----------------------
    #  Запись сделок / общие операции
    # ----------------------

    def append_rows(
        self,
        sheet_title: str,
        rows: List[List[Any]],
    ) -> None:
        """
        Добавляет строки (append) в конец указанного листа.
        """
        if not rows:
            return

        rng = f"'{sheet_title}'!A:Z"  # диапазон "на вырост"
        body = {"values": rows}
        request = self._service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=rng,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        self._execute(request, f"append rows to '{sheet_title}'")

    def batch_update_values(
        self,
        data: List[Dict[str, Any]],
    ) -> None:
        """
        Универсальный батч-апдейт:
        data — список объектов вида:
            {
                "range": "'Trades_202509'!A2:N2",
                "values": [[...]],
            }
        """
        if not data:
            return

        body = {
            "valueInputOption": "RAW",
            "data": data,
        }
        request = self._service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body=body,
        )
        self._execute(request, "batchUpdate values")

    # ----------------------
    #  Обработка очереди sheets_sync_queue
    # ----------------------

    def process_sync_queue(
        self,
        db: Database,
        *,
        limit: int = 100,
    ) -> None:
        """
        Обрабатывает до `limit` записей из таблицы sheets_sync_queue.

        Формат payload_json в очереди (рекомендуемый v1):

        {
          "sheet_title": "Trades_202509",
          "mode": "append",  # или "batchUpdate"
          "rows": [
            ["trade_id", "symbol", ...],
            ...
          ]
        }

        либо для batchUpdate:

        {
          "mode": "batchUpdate",
          "entries": [
            {
              "range": "'Trades_202509'!A2:N2",
              "values": [[...]]
            },
            ...
          ]
        }

        Возможны и другие режимы, главное — чтобы _apply_payload их понимал.
        """
        pending = dao.list_sheets_sync_pending(db, limit=limit)
        if not pending:
            return

        for row_id, entity_type, entity_id, operation, payload_json in pending:
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError as exc:
                logger.exception(
                    "SheetsClient.process_sync_queue: invalid JSON in queue id=%s: %s",
                    row_id,
                    exc,
                )
                dao.mark_sheets_sync_attempt(db, row_id, success=False)
                continue

            try:
                self._apply_payload(payload)
            except Exception as exc:
                logger.exception(
                    "SheetsClient.process_sync_queue: failed to apply payload for queue id=%s: %s",
                    row_id,
                    exc,
                )
                dao.mark_sheets_sync_attempt(db, row_id, success=False)
                continue

            # успех — удаляем из очереди
            dao.mark_sheets_sync_attempt(db, row_id, success=True)

    def _apply_payload(self, payload: Dict[str, Any]) -> None:
        """
        Интерпретирует payload из очереди и вызывает нужные методы.
        """
        mode = payload.get("mode")
        if mode == "append":
            sheet_title = payload.get("sheet_title")
            rows = payload.get("rows")
            if not sheet_title or not isinstance(rows, list):
                raise SheetsError(f"Invalid append payload: {payload}")
            self.append_rows(sheet_title, rows)

        elif mode == "batchUpdate":
            entries = payload.get("entries")
            if not isinstance(entries, list):
                raise SheetsError(f"Invalid batchUpdate payload: {payload}")
            # entries должны быть совместимы с batch_update_values
            self.batch_update_values(entries)

        else:
            raise SheetsError(f"Unsupported payload mode: {mode}")

# ==============================================
# OfflineSheetsClient — заглушка для режима offline
# ==============================================

import logging

class OfflineSheetsClient:
    """
    Offline-версия клиента Google Sheets.
    Не выполняет никаких сетевых вызовов, только логирует факт,
    что в этом месте в нормальном режиме происходила бы синхронизация.
    """

    def __init__(self) -> None:
        self._log = logging.getLogger("sensei.offline_sheets")

    def process_sync_queue(self, db, limit: int = 100) -> None:
        """
        В обычном SheetsClient: чтение очереди sheets_sync_queue и upsert в Google Sheets.
        Здесь — только запись в лог.
        """
        self._log.info(
            {
                "event": "offline_sheets.process_sync_queue",
                "limit": limit,
            }
        )
