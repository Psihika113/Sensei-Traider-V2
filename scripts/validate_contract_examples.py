import json
import sys
from pathlib import Path

EXAMPLES_DIR = Path("docs/contracts/examples")

DECISION_ALLOWED_ACTIONS = {"ALLOW", "DENY", "WAIT", "PAUSE"}

def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"cannot read json: {path} :: {e}")

def validate_decision(obj: dict, path: Path) -> None:
    if obj.get("schema_version") != "sensei.decision.v5":
        fail(f"{path}: schema_version mismatch")

    action = obj.get("action")
    if action not in DECISION_ALLOWED_ACTIONS:
        fail(f"{path}: invalid action={action}")

    # LLM must not output numeric trade params
    forbidden_keys = {"entry", "stop", "take", "qty", "price"}
    for k in forbidden_keys:
        if k in obj:
            fail(f"{path}: forbidden key present: {k}")

    # no extra numeric parameters allowed in top-level
    for k, v in obj.items():
        if isinstance(v, (int, float)) and k not in {"confidence"}:
            # confidence is allowed numeric
            fail(f"{path}: illegal numeric field {k}={v}")

def validate_envelope(obj: dict, path: Path) -> None:
    if obj.get("schema_version") != "sensei.envelope.v1":
        fail(f"{path}: schema_version mismatch")

    if not obj.get("symbol"):
        fail(f"{path}: missing symbol")
    if not obj.get("ts_utc"):
        fail(f"{path}: missing ts_utc")
    if not obj.get("session"):
        fail(f"{path}: missing session")

    snap = obj.get("market_snapshot")
    if not isinstance(snap, dict):
        fail(f"{path}: missing market_snapshot")
    for key in ("bid", "ask", "mid", "spread"):
        if key not in snap:
            fail(f"{path}: market_snapshot missing {key}")
        if not isinstance(snap[key], (int, float)):
            fail(f"{path}: market_snapshot {key} must be numeric")

def main() -> None:
    if not EXAMPLES_DIR.exists():
        fail(f"examples dir not found: {EXAMPLES_DIR}")

    ok = 0
    for p in sorted(EXAMPLES_DIR.glob("*.json")):
        obj = load_json(p)
        sv = obj.get("schema_version", "")
        try:
            if sv.startswith("sensei.decision."):
                validate_decision(obj, p)
            elif sv.startswith("sensei.envelope."):
                validate_envelope(obj, p)
            else:
                fail(f"{p}: unknown schema_version: {sv}")
            print(f"OK: {p}")
            ok += 1
        except SystemExit:
            raise
        except Exception as e:
            fail(f"{p}: unexpected error: {e}")

    print(f"DONE: validated={ok}")

if __name__ == "__main__":
    main()
