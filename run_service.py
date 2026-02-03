# -*- coding: utf-8 -*-
"""
run_service.py

Тонкий враппер для запуска сервиса как скрипта.
Нужен для qt_runner.py, который делает:
  python run_service.py --config <path>
"""

from app.service import main

if __name__ == "__main__":
    raise SystemExit(main())
