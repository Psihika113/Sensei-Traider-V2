# -*- coding: utf-8 -*-
import socket
for port in (7497, 7496):
    s=socket.socket(); s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        print(f"OK: port {port} is reachable")
    except Exception:
        print(f"FAIL: port {port} is not reachable")
    finally:
        s.close()
