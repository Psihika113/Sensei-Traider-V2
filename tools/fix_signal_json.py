import json
import sys
import datetime as dt
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/fix_signal_json.py <path_to_json>")
        return 2

    p = Path(sys.argv[1])
    if not p.exists():
        print(f"File not found: {p}")
        return 2

    raw_bytes = p.read_bytes()
    # remove UTF-8 BOM if present
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]

    txt = raw_bytes.decode("utf-8", errors="strict").strip()
    if not txt:
        print("File is empty after stripping.")
        return 2

    obj = json.loads(txt)
    arr = obj if isinstance(obj, list) else [obj]

    now = dt.datetime.now(dt.timezone.utc)

    for i, s in enumerate(arr):
        # ts_utc fresh
        s["ts_utc"] = (now + dt.timedelta(seconds=30 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # normalize enums expected by pydantic model
        ac = s.get("asset_class")
        if ac == "STK":
            s["asset_class"] = "stock"
        elif ac == "ETF":
            s["asset_class"] = "etf"

        et = s.get("entry_type")
        if et == "LIMIT":
            s["entry_type"] = "limit"
        elif et == "MARKET":
            s["entry_type"] = "market"
        elif et == "STOP":
            s["entry_type"] = "stop"
        elif et == "STOP_LIMIT":
            s["entry_type"] = "stop_limit"

        side = s.get("side")
        if isinstance(side, str):
            if side.lower() == "buy":
                s["side"] = "BUY"
            elif side.lower() == "sell":
                s["side"] = "SELL"

        tif = s.get("time_in_force")
        if isinstance(tif, str):
            if tif.lower() == "day":
                s["time_in_force"] = "DAY"
            elif tif.lower() == "gtc":
                s["time_in_force"] = "GTC"
            elif tif.lower() == "ioc":
                s["time_in_force"] = "IOC"
            elif tif.lower() == "fok":
                s["time_in_force"] = "FOK"

    out = json.dumps(arr, ensure_ascii=False, indent=2)
    p.write_text(out, encoding="utf-8", newline="\n")
    print(f"OK: wrote {p} ({p.stat().st_size} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
