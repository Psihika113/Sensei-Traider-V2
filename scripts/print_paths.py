# scripts/print_paths.py
import sys, os
print("CWD:", os.getcwd())
print("sys.path[0:5]:", sys.path[0:5])
try:
    import adapters, app, core
    print("OK: imported adapters, app, core")
except Exception as e:
    print("IMPORT ERROR:", e)
