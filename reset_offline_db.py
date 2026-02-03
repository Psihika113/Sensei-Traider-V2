# reset_offline_db.py
"""
Утилита для оффлайн-режима SenseiTrader:
- если существует data/trader.db — переименовывает его в архив с таймстампом;
- новая БД не создаётся специально: её создаст сам app.service при следующем запуске.
"""

from datetime import datetime
from pathlib import Path
import shutil
import sys


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    db_path = data_dir / "trader.db"
    archive_dir = data_dir / "offline_archive"

    print(f"[reset_offline_db] BASE_DIR   = {base_dir}")
    print(f"[reset_offline_db] DATA_DIR   = {data_dir}")
    print(f"[reset_offline_db] DB_PATH    = {db_path}")

    if not data_dir.exists():
        print("[reset_offline_db] Папка data не найдена. Нечего сбрасывать.")
        return 0

    # создаём папку для архивов
    archive_dir.mkdir(exist_ok=True)
    print(f"[reset_offline_db] ARCHIVE_DIR= {archive_dir}")

    if not db_path.exists():
        print("[reset_offline_db] trader.db не найден — возможно, уже сброшен. ОК.")
        return 0

    # имя архива с таймстампом
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"trader_offline_archive_{ts}.db"
    archive_path = archive_dir / archive_name

    print(f"[reset_offline_db] Архивируем: {db_path.name} -> {archive_path.name}")
    shutil.move(str(db_path), str(archive_path))

    print("[reset_offline_db] Готово. Следующий запуск app.service создаст новую БД.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
