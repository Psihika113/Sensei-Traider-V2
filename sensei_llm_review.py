#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sensei_llm_review.py

Обёртка над sensei_daily_prompt.py:

1) Берёт готовый SENSEI_PROMPT из sensei_daily_prompt.py (через subprocess).
2) Опционально отправляет его в LLM (OpenAI) и печатает ответ.
3) Может работать без LLM (ручной режим).
4) Может сохранять отчёт в Markdown (папка reports/).

Использование (варианты):
    python sensei_llm_review.py
    python sensei_llm_review.py 2025-11-03
    python sensei_llm_review.py --date 2025-12-10 --no-llm
    python sensei_llm_review.py --save-md
    python sensei_llm_review.py --date 2025-11-03 --save-md

Переменные окружения:
    OPENAI_API_KEY      — ключ OpenAI (если нет — LLM-прослойка пропускается).
    SENSEI_MODEL        — имя модели (по умолчанию gpt-4.1-mini).
    SENSEI_TEMPERATURE  — float, по умолчанию 0.2
    SENSEI_MAX_TOKENS   — int, по умолчанию 800
    SENSEI_PROVIDER     — провайдер LLM:
                          - "openai" (по умолчанию, если есть ключ)
                          - "manual" (всегда ручной режим, без запросов в LLM)
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from typing import Optional, Tuple


PROMPT_BEGIN = "===== SENSEI_PROMPT_BEGIN ====="
PROMPT_END = "===== SENSEI_PROMPT_END ====="


# ============================================================
# 1. Получение промпта от sensei_daily_prompt.py
# ============================================================

def build_daily_prompt(date_arg: Optional[str] = None) -> str:
    """
    Запускает sensei_daily_prompt.py и вытаскивает блок между
    PROMPT_BEGIN и PROMPT_END.

    Если что-то идёт не так, выбрасывает RuntimeError с понятным текстом.
    """
    cmd = [sys.executable, "sensei_daily_prompt.py"]
    if date_arg:
        cmd.append(date_arg)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        raise RuntimeError(f"Не удалось запустить sensei_daily_prompt.py: {e!r}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"sensei_daily_prompt.py завершился с кодом {proc.returncode}.\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )

    output = proc.stdout
    start_idx = output.find(PROMPT_BEGIN)
    end_idx = output.find(PROMPT_END)

    if start_idx == -1 or end_idx == -1:
        raise RuntimeError(
            "Не удалось найти блок PROMPT_BEGIN / PROMPT_END в выводе "
            "sensei_daily_prompt.py. Проверь формат выводимого промпта."
        )

    # Берём содержимое между линиями BEGIN и END (без самих маркеров)
    start_idx = output.find("\n", start_idx)
    if start_idx == -1:
        start_idx = 0
    else:
        start_idx += 1

    prompt_body = output[start_idx:end_idx].strip()
    return prompt_body


def extract_day_from_prompt(prompt: str, fallback: str = "unknown") -> str:
    """
    Пытается вытащить дату из секции [DAY_STATS], строка формата:
        date: YYYY-MM-DD

    Если не удалось — возвращает fallback.
    """
    for line in prompt.splitlines():
        line = line.strip()
        if line.startswith("date:"):
            _, val = line.split(":", 1)
            return val.strip()
    return fallback


# ============================================================
# 2. Вызов LLM (OpenAI) — опциональный
# ============================================================

def call_openai_llm(prompt: str) -> Optional[str]:
    """
    Пытается отправить промпт в OpenAI.
    Возвращает текст ответа или None, если:
      - нет OPENAI_API_KEY,
      - или библиотека openai не установлена,
      - или запрос завершился ошибкой.

    ВНИМАНИЕ: если нужен другой провайдер (Gemini, локальная LLM и т.п.),
    можно сделать аналогичную функцию под него и вызывать вместо этой.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[sensei_llm_review] OPENAI_API_KEY не найден, LLM-запрос пропускаем.")
        return None

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print(
            "[sensei_llm_review] Библиотека 'openai' не установлена.\n"
            "Установи её в venv: pip install openai"
        )
        return None

    model = os.getenv("SENSEI_MODEL", "gpt-4.1-mini")
    temperature_str = os.getenv("SENSEI_TEMPERATURE", "0.2")
    max_tokens_str = os.getenv("SENSEI_MAX_TOKENS", "800")

    try:
        temperature = float(temperature_str)
    except ValueError:
        temperature = 0.2

    try:
        max_tokens = int(max_tokens_str)
    except ValueError:
        max_tokens = 800

    client = OpenAI(api_key=api_key)

    system_msg = (
        "Ты — строгий, но поддерживающий трейдинговый наставник (SenseiTrader Coach). "
        "Тебе дают сводку дня в структурированном виде. "
        "Твоя задача — кратко и по делу разобрать торговлю:\n"
        "- оценить управление риском, размер позиций и дисциплину;\n"
        "- отметить сильные стороны и слабые места;\n"
        "- дать 3–7 конкретных рекомендаций на следующий день.\n"
        "Говори короткими пунктами, без воды, без мотивационных фраз, только практика."
    )

    user_msg = prompt

    print(
        f"[sensei_llm_review] Отправляем промпт в OpenAI:\n"
        f"  модель: {model}\n"
        f"  temperature: {temperature}\n"
        f"  max_tokens: {max_tokens}\n"
    )

    try:
        # Новое API Responses
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    except Exception as e:
        print(f"[sensei_llm_review] Ошибка при запросе к OpenAI: {e!r}")
        return None

    try:
        # Структура: response.output[0].content[0].text
        first_output = response.output[0]
        first_content = first_output.content[0]
        text = getattr(first_content, "text", None)
        if text is None:
            # fallback: вдруг структура немного другая
            text = str(first_content)
    except Exception:
        text = str(response)

    return str(text).strip()


# ============================================================
# 3. Сохранение в Markdown
# ============================================================

def save_markdown_report(
    date_str: str,
    prompt_body: str,
    review_text: Optional[str],
    reports_dir: str = "reports",
) -> Path:
    """
    Сохраняет промпт и (опционально) ответ LLM в Markdown-файл.

    Формат имени файла:
        reports/sensei_review_<date_str>.md

    Если date_str неизвестна, используется 'unknown'.

    Возвращает Path к созданному файлу.
    """
    Path(reports_dir).mkdir(parents=True, exist_ok=True)

    safe_date = date_str if date_str else "unknown"
    filename = f"sensei_review_{safe_date}.md"
    filepath = Path(reports_dir) / filename

    lines = []
    lines.append(f"# SenseiTrader Daily Review — {safe_date}\n")
    lines.append("## Входные данные (SENSEI_PROMPT)\n")
    lines.append("```text")
    lines.append(prompt_body)
    lines.append("```\n")

    if review_text is not None:
        lines.append("## Ответ Sensei (LLM)\n")
        lines.append(review_text)
        lines.append("\n")
    else:
        lines.append("## Ответ Sensei (LLM)\n")
        lines.append("_Ответ LLM не был получен (ручной режим или ошибка запроса)._")
        lines.append("\n")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ============================================================
# 4. CLI и основная логика
# ============================================================

def parse_args(argv=None) -> argparse.Namespace:
    """
    Разбор аргументов командной строки.
    """
    parser = argparse.ArgumentParser(
        description="Ежедневный разбор торгов от Sensei (LLM-коуч)."
    )

    parser.add_argument(
        "date",
        nargs="?",
        default=None,
        help="Дата торгового дня (YYYY-MM-DD). Если не указана — auto через sensei_daily_prompt.py.",
    )

    parser.add_argument(
        "--date",
        dest="date_opt",
        default=None,
        help="Альтернативный способ задать дату (YYYY-MM-DD). Если указано и позиционный аргумент, приоритет у этого.",
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Не вызывать LLM, только показать готовый промпт.",
    )

    parser.add_argument(
        "--save-md",
        action="store_true",
        help="Сохранить промпт и ответ (если есть) в Markdown (папка reports/).",
    )

    parser.add_argument(
        "--provider",
        dest="provider",
        choices=["openai", "manual"],
        default=None,
        help="Провайдер LLM: 'openai' или 'manual' (ручной режим). "
             "Если не указано, берётся из SENSEI_PROVIDER или auto.",
    )

    return parser.parse_args(argv)


def resolve_provider(no_llm_flag: bool, provider_arg: Optional[str]) -> str:
    """
    Решает, каким провайдером пользоваться:
      - если передан --no-llm, всегда 'manual';
      - иначе если есть provider_arg, использует его;
      - иначе смотрит на SENSEI_PROVIDER;
      - по умолчанию — 'openai'.
    """
    if no_llm_flag:
        return "manual"

    if provider_arg:
        return provider_arg

    env_provider = os.getenv("SENSEI_PROVIDER")
    if env_provider in ("openai", "manual"):
        return env_provider

    return "openai"


def maybe_call_llm(provider: str, prompt_body: str) -> Optional[str]:
    """
    В зависимости от провайдера решает, вызывать ли LLM.
    Сейчас поддерживаются:
      - 'manual' — ничего не вызывает, возвращает None
      - 'openai' — вызывает OpenAI, если есть ключ и библиотека
    """
    if provider == "manual":
        print("[sensei_llm_review] Провайдер 'manual' — LLM не вызывается.")
        return None

    if provider == "openai":
        return call_openai_llm(prompt_body)

    # На будущее — другие провайдеры.
    print(f"[sensei_llm_review] Неизвестный провайдер '{provider}', работаем в manual.")
    return None


def main() -> None:
    args = parse_args()

    # Определяем дату: приоритет у --date
    date_arg = args.date_opt if args.date_opt is not None else args.date

    provider = resolve_provider(args.no_llm, args.provider)
    print(f"[sensei_llm_review] Провайдер: {provider}")

    # 1) Получаем промпт от sensei_daily_prompt.py
    try:
        prompt_body = build_daily_prompt(date_arg)
    except RuntimeError as e:
        print("[sensei_llm_review] Ошибка при подготовке промпта:")
        print(str(e))
        sys.exit(1)

    # 2) Пытаемся вытащить дату из промпта (для имени файла и логики)
    day_str = extract_day_from_prompt(prompt_body, fallback=date_arg or "unknown")

    # 3) Показываем готовый промпт
    print("========================================")
    print("=== SENSEI DAILY PROMPT (готовый ввод) ===")
    print("========================================\n")
    print(prompt_body)
    print("\n========================================\n")

    # 4) Опциональный вызов LLM
    review = maybe_call_llm(provider, prompt_body)

    if review is None:
        print(
            "LLM-ответ не получен (режим manual / нет ключа / нет библиотеки / ошибка запроса).\n"
            "Ты можешь скопировать блок промпта выше и вручную вставить его в ChatGPT "
            "или другой LLM."
        )
    else:
        print("=== ОТВЕТ SENSEI (LLM) ===\n")
        print(review)
        print("\n=== КОНЕЦ ОТВЕТА SENSEI ===")

    # 5) При необходимости сохраняем в Markdown
    if args.save_md:
        try:
            out_path = save_markdown_report(day_str, prompt_body, review)
            print(f"[sensei_llm_review] Отчёт сохранён: {out_path}")
        except Exception as e:
            print(f"[sensei_llm_review] Не удалось сохранить Markdown-отчёт: {e!r}")


if __name__ == "__main__":
    main()
