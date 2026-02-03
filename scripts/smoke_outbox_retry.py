# scripts/smoke_outbox_retry.py
import time
from app.config import load_app_config
from app.notify import Notifier
from app.outbox import Outbox
from app.dao import Dao

cfg = load_app_config("config/app.paper.toml")
dao = Dao(cfg.paths.db)
out = Outbox(dao)

# нетворк «падает»: заглушки возвращают False
handlers = {
    "telegram": lambda p: False,
    "sheets":   lambda p: False,
}

out.enqueue("telegram", {"text": "hello from outbox"})
out.enqueue("sheets", {"type":"order", "row":["TST", "BUY", 1]})

for i in range(5):
    out.process(handlers)
    print("tick", i)
    time.sleep(1)

print("network restored, telegram OK:")
handlers["telegram"] = lambda p: True
for i in range(5):
    out.process(handlers)
    time.sleep(1)

print("sheets restored:")
handlers["sheets"] = lambda p: True
for i in range(5):
    out.process(handlers)
    time.sleep(1)
