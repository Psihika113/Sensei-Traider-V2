# scripts/smoke_tg_batching.py
import time
from app.config import load_app_config
from app.notify import Notifier

cfg = load_app_config("config/app.paper.toml")
n = Notifier(cfg.telegram.token, cfg.telegram.chat_id, cfg.telegram.batch_interval_sec)

for i in range(5):
    n.enqueue(f"TEST batch message #{i+1}")
    time.sleep(1)

print("sending CRITICAL now")
n.critical("CRITICAL: should arrive immediately")
print("waiting for batch flush...")
time.sleep(cfg.telegram.batch_interval_sec + 1)
n.flush(force=True)
print("done")
