# scripts/ib_connect_and_qualify.py
from ib_insync import IB
import sys, traceback

HOST = '127.0.0.1'
PORTS = [7497, 4002]  # TWS Paper, IBG Paper
CID   = 321

for p in PORTS:
    ib = IB()
    print(f"\n=== Trying {HOST}:{p} clientId={CID} ===")
    try:
        ib.connect(HOST, p, clientId=CID, timeout=30)
        print("Connected:", ib.isConnected(), "ServerVersion:", ib.client.serverVersion())
        acct = ib.managedAccounts()  # триггер базовой квалификации
        print("Accounts:", acct)
    except Exception as e:
        print("FAILED:", repr(e))
        traceback.print_exc(limit=1, file=sys.stdout)
    finally:
        try:
            ib.disconnect()
        except:
            pass
