# _patch_show_db_path.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ensure_import_os(text: str) -> str:
    """Если в файле нет 'import os' — аккуратно добавляем его после блока импортов."""
    if "import os" in text:
        return text

    lines = text.splitlines()
    insert_idx = 0

    # Ищем блок import/from import в начале файла
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_idx = i + 1

    lines.insert(insert_idx, "import os")
    return "\n".join(lines)


def patch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    # Если в файле нет "data/trader.db" — ничего не делаем
    if "data/trader.db" not in text:
        return

    original = text

    # Добавляем import os при необходимости
    text = ensure_import_os(text)

    # Меняем все вхождения строки на env-вариант
    # Работает и в случаях типа:
    #   "data/trader.db"
    #   Path("data/trader.db")
    #   DB = "data/trader.db"
    text = text.replace(
        '"data/trader.db"',
        'os.getenv("SENSEI_DB_PATH", "data/trader.db")',
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"Patched: {path.name}")


def main() -> None:
    for path in ROOT.glob("show_*.py"):
        patch_file(path)


if __name__ == "__main__":
    main()
