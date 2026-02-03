from pathlib import Path

from app.config import load_app_config
from app.db import Database, init_schema


def main() -> None:
    cfg = load_app_config("config/app.toml")
    db_path = Path(cfg.db.path)

    print(f"Инициализирую БД по пути: {db_path}")

    db = Database(db_path)
    db.connect()
    init_schema(db, "schema.sql")

    print("Готово: схема применена.")


if __name__ == "__main__":
    main()
