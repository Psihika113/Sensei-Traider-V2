from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class SignalModeClient:
    """
    Заглушка LLM-клиента для режима Signal Mode.

    Задача этого класса:
    - принять Envelope (dict);
    - залогировать вход;
    - вернуть безопасное решение в формате, приближенном к DecisionV5;
    - пока НИЧЕГО не вызывать наружу (ни OpenAI, ни Codex и т.д.).

    Позже внутренняя реализация будет заменена на реальный вызов LLM,
    с использованием prompts/sensei_signal_mode_codex.md и т.д.
    """

    def __init__(
        self,
        enabled: bool = False,
        model_name: str = "sensei-signal-mode-llm",
        codex_path: Optional[Path] = None,
    ) -> None:
        self.enabled = enabled
        self.model_name = model_name
        # Путь к КОДЕКСУ (prompt-артефакт), если нужно читать его из файла
        self.codex_path = codex_path or Path("prompts") / "sensei_signal_mode_codex.md"

    def load_codex_text(self) -> Optional[str]:
        """
        Опционально загружает текст КОДЕКСА с диска.
        Сейчас не используется в заглушке, но интерфейс уже есть.
        """
        try:
            if self.codex_path.is_file():
                text = self.codex_path.read_text(encoding="utf-8")
                logger.debug("Loaded Signal Mode CODEX from %s", self.codex_path)
                return text
            logger.warning("Signal Mode CODEX file not found at %s", self.codex_path)
        except Exception as exc:
            logger.exception("Failed to load Signal Mode CODEX: %s", exc)
        return None

    def run(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """
        Главная точка входа.

        В финальной версии:
        - сериализует Envelope;
        - подготавливает prompt (constitution + governance + codex + schema);
        - вызывает LLM;
        - парсит JSON-ответ и возвращает DecisionV5.

        Сейчас:
        - логирует Envelope;
        - возвращает безопасный stub-Decision, который НИЧЕГО не исполняет.
        """
        envelope_id = str(envelope.get("envelope_id") or envelope.get("request_id") or "UNKNOWN")

        logger.info("SignalModeClient.run called for envelope_id=%s", envelope_id)
        logger.debug("Envelope payload: %s", self._safe_dump(envelope))

        # Если LLM-движок ещё не включён — всегда безопасный отказ.
        if not self.enabled:
            decision = self._build_safe_stub_decision(envelope_id=envelope_id)
            logger.info(
                "SignalModeClient disabled, returning safe stub Decision for envelope_id=%s",
                envelope_id,
            )
            logger.debug("Decision stub: %s", self._safe_dump(decision))
            return decision

        # Здесь в будущем появится реальный вызов модели.
        # Пока даже при enabled=True возвращаем тот же безопасный stub,
        # чтобы не ломать пайплайн.
        decision = self._build_safe_stub_decision(envelope_id=envelope_id)
        logger.info(
            "SignalModeClient enabled, but LLM integration is not implemented yet; "
            "returning safe stub Decision for envelope_id=%s",
            envelope_id,
        )
        logger.debug("Decision stub: %s", self._safe_dump(decision))
        return decision

    @staticmethod
    def _build_safe_stub_decision(envelope_id: str) -> Dict[str, Any]:
        """
        Безопасный stub-ответ в формате, по смыслу совместимый с DecisionV5:
        - action_suggested: 'DENY' (ничего не исполняем);
        - reason_code: 'TECH_ERROR' (движок не готов);
        - reason_text: короткое объяснение.
        Остальные поля можно будет дополнить, когда мы привяжем фактический контракт.
        """
        return {
            "schema_version": "DecisionV5",
            "decision_id": f"STUB-{envelope_id}",
            "action_suggested": "DENY",
            "reason_code": "TECH_ERROR",
            "reason_text": (
                "Signal Mode LLM engine is not yet integrated; "
                "this is a safe stub decision that denies execution."
            ),
            # Место для дальнейшего расширения по реальному контракту DecisionV5:
            # "meta": {...}, "risk_snapshot": {...}, и т.п.
        }

    @staticmethod
    def _safe_dump(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return "<unserializable>"
