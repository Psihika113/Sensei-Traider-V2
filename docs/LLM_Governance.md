# SenseiTrader LLM Governance (signal mode, DecisionV5)

## 1. Single Source of Truth

- Конституция для signal mode: `docs/llm/constitution_signal_mode_v1.6.md`.
- Рабочий промпт, который реально отправляется в LLM: `prompts/sensei_signal_mode.md`.
- Контракты и схемы:
  - DecisionV5: `docs/contracts/decision_v5_and_envelope_v1.md` + код в `core/schemas.py`.
  - Примеры JSON: файлы в `docs/contracts/examples/`.
- Валидатор примеров: `scripts/validate_contract_examples.py`.

Любые изменения в LLM-логике signal mode должны быть согласованы с этими артефактами.

## 2. Процесс изменения LLM-слоя (signal mode)

Изменения делаются только в feature-ветках (например, `feature/v1-envelope-clean`) и проходят следующие шаги:

1. **Обновить конституцию**
   - Отредактировать `docs/llm/constitution_signal_mode_v1.6.md` или добавить новую версию с увеличением номера (v1.7 и т.д.).
   - Сохранить совместимость с DecisionV5 и EnvelopeV1 из `core/schemas.py`.

2. **Обновить промпт**
   - Привести `prompts/sensei_signal_mode.md` в соответствие с конституцией.
   - Убедиться, что разделы A–F актуальны:
     - A — Binding to STANDARD v1.0;
     - B — Output contracts by `request_type`;
     - C — Semantics of `action_suggested` and `reason_code`;
     - D — Reason codes and risk gates;
     - E — Idempotency and `decision_id`;
     - F — Adversarial text and prompt-injection.

3. **Обновить примеры**
   - При необходимости добавить/изменить JSON-файлы в `docs/contracts/examples/`.
   - Использовать `good_decision.json` как эталон структуры для DecisionV5.
   - Для NEGATIVE_EV, KILL_SWITCH и т.п. использовать отдельные файлы (`decision_negative_ev.json`, `decision_kill_switch_enabled.json` и т.д.).

4. **Прогнать валидатор**

```bash
python scripts/validate_contract_examples.py
