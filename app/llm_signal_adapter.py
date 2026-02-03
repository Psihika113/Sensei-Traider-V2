# -*- coding: utf-8 -*-
# app/llm_signal_adapter.py
#
# Адаптер между LLM/ручным JSON и offline-источником сигналов для app.service.
#
# Назначение:
#   - принять JSON с одним или несколькими сигналами;
#   - привести к core.schemas.Signal (валидация контракта);
#   - сохранить в папку `signals/` в формате, который читает _FileSignalSource.
#
# Пример использования:
#   1) Из файла:
#       .venv\Scripts\python.exe -m app.llm_signal_adapter --input tmp_signal.json
#
#   2) Из stdin (можно вставить JSON руками):
#       .venv\Scripts\python.exe -m app.llm_signal_adapter --out-dir signals_llm
#       { "signal_id": "...", "ts_utc": "...", ... }
#       <Ctrl+Z> + Enter  (в Windows, чтобы завершить ввод)
#
# После этого app.service в offline-режиме подхватит созданный файл
# и прогонит сигналы через RiskGate → OrderManager.

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from core.schemas import Signal  # Pydantic-модель сигнала


def _read_json_from_file(path: Path) -> Any:
    """Прочитать JSON из файла."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_json_from_stdin() -> Any:
    """Прочитать JSON из stdin (до EOF)."""
    data = sys.stdin.read()
    if not data.strip():
        raise ValueError("stdin пуст — нет данных для парсинга JSON.")
    return json.loads(data)


def _normalize_to_signals(obj: Any) -> List[Signal]:
    """
    Привести произвольный JSON к списку Signal.

    Поддерживаем варианты:
      1) Один сигнал: { "signal_id": "...", ... }
      2) Список сигналов: [ {...}, {...} ]
      3) Обёртка: { "signals": [ {...}, {...} ] }
    """
    # 1) Уже список — считаем, что это список сигналов
    if isinstance(obj, list):
        return [Signal(**item) for item in obj]

    # 2) Словарь
    if isinstance(obj, dict):
        # Вариант 3: обёртка {"signals": [ ... ]}
        if "signals" in obj and isinstance(obj["signals"], list):
            return [Signal(**item) for item in obj["signals"]]

        # Вариант 1: один сигнал (проверяем наличие базовых полей)
        if "signal_id" in obj and "symbol" in obj and "side" in obj:
            return [Signal(**obj)]

        raise ValueError(
            "JSON-объект не похож ни на одиночный Signal, ни на обёртку {'signals': [...]}"
        )

    raise TypeError("Ожидался JSON-объект или массив, а не примитивный тип.")


def _write_signals_file(signals: List[Signal], out_dir: Path) -> Path:
    """
    Сохранить список Signal в файл в директории out_dir.

    Формат:
      - filename: llm_signals_YYYYMMDDTHHMMSSZ.json
      - содержимое: массив JSON-объектов (уже после валидации pydantic).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"llm_signals_{ts}.json"
    out_path = out_dir / filename

    # model_dump(mode="json") вернёт нормализованный словарь
    payload = [sig.model_dump(mode="json") for sig in signals]

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Адаптер LLM/ручного JSON → offline-источник сигналов для app.service.\n"
            "Читает JSON из файла или stdin, валидирует как core.schemas.Signal "
            "и сохраняет в директорию (по умолчанию: signals/)."
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        type=str,
        default=None,
        help=(
            "Путь к JSON-файлу с сигналом/сигналами. "
            "Если не указан — читаем JSON из stdin."
        ),
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        type=str,
        default="signals",
        help=(
            "Директория, куда будет записан файл с сигналами. "
            "По умолчанию: 'signals' (совпадает с источником для app.service в offline-режиме)."
        ),
    )

    args = parser.parse_args(argv)

    try:
        if args.input:
            src_path = Path(args.input)
            raw = _read_json_from_file(src_path)
        else:
            raw = _read_json_from_stdin()
    except Exception as e:
        print(f"[ERROR] Не удалось прочитать JSON: {e}", file=sys.stderr)
        return 1

    try:
        signals = _normalize_to_signals(raw)
    except Exception as e:
        print(f"[ERROR] Ошибка приведения к Signal: {e}", file=sys.stderr)
        return 2

    if not signals:
        print("[WARN] После нормализации нет ни одного сигнала — файл не создаём.", file=sys.stderr)
        return 0

    try:
        out_path = _write_signals_file(signals, Path(args.out_dir))
    except Exception as e:
        print(f"[ERROR] Не удалось записать файл с сигналами: {e}", file=sys.stderr)
        return 3

    print(f"[OK] Записано сигналов: {len(signals)}")
    print(f"[OK] Файл: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
