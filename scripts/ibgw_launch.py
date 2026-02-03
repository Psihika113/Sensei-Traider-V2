# -*- coding: utf-8 -*-
# scripts/ibgw_launch.py — минимальный лаунчер IB Gateway (IBC-lite)
from __future__ import annotations
import os, sys, time, socket, subprocess, platform
from pathlib import Path

IBGW_HOST = os.environ.get("IB_HOST", "127.0.0.1")
IBGW_PORT = int(os.environ.get("IB_PORT", "7497"))
CHECK_TIMEOUT = 1.0

def port_open(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CHECK_TIMEOUT):
            return True
    except Exception:
        return False

def start_ibgw():
    """
    Укажи переменную IBGW_CMD или скорректируй пути ниже под свою установку:
    - Windows: "C:\\Jts\\ibgateway\\<ver>\\ibgateway.exe" /SettingsPath=c:\\Jts\\ibgateway
    - Linux: "/opt/ibgateway/ibgateway" & конфиги в ~/.ibc или ~/.TraderWorkstation
    """
    cmd = os.environ.get("IBGW_CMD")
    if not cmd:
        if platform.system() == "Windows":
            cmd = r"C:\Jts\ibgateway\1012\ibgateway.exe"
        else:
            cmd = "/opt/ibgateway/ibgateway"
    args = [cmd]
    print(f"[ibgw] starting: {cmd}")
    try:
        if platform.system() == "Windows":
            # DETACHED_PROCESS
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(args, creationflags=DETACHED_PROCESS)
        else:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return True
    except Exception as e:
        print(f"[ibgw] start failed: {e}")
        return False

def main():
    backoff = 2
    while True:
        ok = port_open(IBGW_HOST, IBGW_PORT)
        if ok:
            time.sleep(5)
            continue
        # не доступен — пробуем поднять
        started = start_ibgw()
        if not started:
            time.sleep(min(backoff, 60))
            backoff *= 2
        else:
            backoff = 2
        time.sleep(5)

if __name__ == "__main__":
    main()
