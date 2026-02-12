import json
import sys
from pathlib import Path
from typing import Any, Dict

# === ВАЖНО: добавить корень проекта в sys.path, чтобы работал импорт "app...." ===
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm.signal_client import SignalModeClient


def load_any_envelope() -> Dict[str, Any]:
    """
    Берём любой envelope из envelopes_inbox, если есть.
    Если пусто — возвращаем минимальный stub-envelope.
    """
    inbox = Path("envelopes_inbox")
    if inbox.is_dir():
        for p in inbox.glob("*.json"):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue

    # Fallback: минимальный envelope для теста клиента
    return {
        "envelope_id": "stub-envelope-001",
        "symbol": "TEST",
        "context": "manual-test",
    }


def main() -> None:
    envelope = load_any_envelope()
    client = SignalModeClient(enabled=False)

    decision = client.run(envelope)

    print("Envelope:")
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    print("\nDecision (stub):")
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
