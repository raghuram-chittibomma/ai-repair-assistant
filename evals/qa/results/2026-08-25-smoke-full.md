# Q&A smoke test log — 2026-08-25

All five scenarios from `evals/qa/smoke-scenarios.yaml` executed live against
Postgres on LAN host + OpenAI (`gpt-4o-mini`).

| Scenario | Result | Notes |
| --- | --- | --- |
| f5e2-meaning | **PASS** | Door lock failure; cited W11169652, W11156989, W11320651 |
| f5e2-door-locks-wont-start | **PASS** | Turn 1 grounded F5E2 door-lock; turn 2 narrowed to TEST #4; no W11395614 |
| acu-led-step-10 | **PASS** | Cited W11375982; slow blink = functioning correctly, not a fault |
| door-locks-wont-run-no-wrong-bulletin | **PASS** | Cited W11169652, W11156989, W11320651 only; W11395614 excluded |
| unknown-error-abstain | **PASS** | Abstained — evidence lacks ZZ99 |

## Commands used

```powershell
python -m repair_assistant.corpus.cli ask "What does F5E2 mean?" --model WFW5620HW0
python -m repair_assistant.corpus.cli ask "On a WFW5620HW0, what should the ACU diagnostic LED do during the ACU power check?" --model WFW5620HW0
python -m repair_assistant.corpus.cli ask "My Whirlpool front load washer locks the door but won't start." --model WFW5620HW0
python -m repair_assistant.corpus.cli ask "What does error code ZZ99 mean?" --model WFW5620HW0
# Multi-turn diagnose via DiagnosticSession (two turns)
```

## Highlights

- **acu-led-step-10:** Answer correctly states slow blink means ACU likely fine; cites bulletin W11375982.
- **door-locks-wont-run:** Applicability filter kept 24in-only W11395614 out of citations.
- **unknown-error-abstain:** Model abstained despite retrieving 8 chunks (no ZZ99 in corpus).
