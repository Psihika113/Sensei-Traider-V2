# run_service.py
import logging
from pathlib import Path

from app.config import load_app_config
from app.executor import OrderExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

def main(config_path: str) -> None:
    cfg = load_app_config(Path(config_path))
    # Логи "✅ Конфиг загружен, БД доступна, ядро собрано." идут из load_app_config

    executor = OrderExecutor(cfg)
    # Можно настроить период опроса, 2 секунды — комфортно для dev
    executor.run_forever(poll_interval=2.0)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/app.toml")
    args = parser.parse_args()

    main(args.config)
