# Evaluation result notes

- Baseline: `20261110T065136Z-baseline.json` — **15/17 passed** with the LLM disabled. Both failures were the new injection phrasings (`ignore all previous instructions` and `disregard the rules above`), which were refunded instead of escalated.
- After: `20261110T065144Z-after.json` — **17/17 passed** with the LLM disabled.
- Targeted change: added bounded `ignore ... instructions` and `disregard ... rules/instructions/policy` detection to `src/normalise.py`; no outcome, amount, or authority rules changed.
- Cost: $0.00000000 per request in both runs (LLM disabled). Median latency: 8.626 ms baseline, 10.111 ms after.
