# -*- coding: utf-8 -*-
from ib_insync import IB
import sys

HOST = "127.0.0.1"; PORT = 7497; CLIENT_ID = 101

if __name__ == "__main__":
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, readonly=False, timeout=10)
        print("OK connected:", ib.isConnected())
        print("Accounts:", ib.managedAccounts())
        print("Server time:", ib.reqCurrentTime())
        ib.disconnect()
        sys.exit(0)
    except Exception as e:
        print("ERROR:", repr(e))
        sys.exit(1)
