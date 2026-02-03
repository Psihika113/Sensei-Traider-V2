# scripts/smoke_exec_and_watch.py
# -*- coding: utf-8 -*-
import time, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# КЛЮЧЕВОЕ: добавим проект в sys.path и сменим cwd
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# лёгкий логгер на stdout
class _Logger:
    def info(self, obj): print("INFO:", obj)
    def warning(self, obj): print("WARN:", obj)
    def error(self, obj): print("ERR:", obj)

from adapters.ibkr.client import IBKRClient

def main():
    logger = _Logger()
    ib = IBKRClient("127.0.0.1", 7497, 1, logger)

    if not ib.connect():
        print("IB connect failed")
        return

    def on_exec(p):
        print("EXEC:", p)

    def on_status(p):
        print("STATUS:", p)

    ok = ib.start_watch(on_exec=on_exec, on_status=on_status)
    print("watch started:", ok)

    # Ставим рыночный ордер, чтобы получить fill
    ok, msg = ib.place_bracket(
        symbol="AAPL",
        parent_type="MKT",
        parent_price=None,
        stop_price=0.01,
        take_price=9999,
        qty=1,
        tif="DAY",
        outside_rth=False
    )
    print("place_bracket:", ok, msg)

    time.sleep(8)

if __name__ == "__main__":
    main()
