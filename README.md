# Larkfield Home support agent

Deterministic support-ticket resolver for refunds, returns, delivery issues and order-status questions. `RP-3.2` is authoritative; the stale FAQ and warehouse document do not change customer decisions. The optional LLM layer only extracts facts and phrases replies; it never chooses an outcome, amount or approver.

## Prepare data

The data room is committed under `data/` and the policy files under `policies/`. Run the read-only preparation report:

```bash
python3 scripts/prepare_data.py
```

It reports row counts, mixed date/amount formats, duplicate order rows, unavailable carrier statuses and duplicate/forwarded tickets without modifying the CSVs.

## Configure

Copy `.env.example` to `.env` or export the variables directly:

| Variable | Purpose |
|---|---|
| `PORT` | HTTP port; defaults to `8000`. `src/solution.py` reads it at startup. |
| `RUN_DB_PATH` | Writable SQLite path. Defaults to `/tmp/larkfield/runs.db`; `runs.db` and `*.db` are gitignored. |
| `LLM_API_KEY` | Optional LLM API key. Never commit it. |
| `LLM_MODEL` | Optional model id recorded in the trace. |
| `LLM_BASE_URL` | Optional OpenAI-compatible base URL. |
| `LLM_TIMEOUT` | LLM request timeout in seconds; defaults to `5`. |
| `LLM_INPUT_USD_PER_1K` | Input-token price in USD per 1,000 tokens, used for measured `cost_usd`. Defaults to `0`. |
| `LLM_OUTPUT_USD_PER_1K` | Output-token price in USD per 1,000 tokens, used for measured `cost_usd`. Defaults to `0`. |

Without LLM settings, or after any model timeout/malformed output, the deterministic regex extractor and template reply are used.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.solution
```

The server listens on `0.0.0.0:$PORT` (default `8000`).

## API

- `POST /tickets` — process one ticket and return the response contract.
- `GET /runs/{run_id}` — return a run (404 if unknown).
- `POST /runs/{run_id}/decision` — record `{"decision":"approve|reject","approver":"..."}`. The first decision wins; repeated or conflicting decisions return the run unchanged and never create a second ledger record. If a run is not waiting for a person, it is returned unchanged.
- `GET /ledger` — all ledger entries with `run_id`, `ticket_id`, `action`, `amount_usd`, `status`, `recorded_at`.
- `GET /runs/{run_id}/ledger` — extra endpoint for one run's ledger entries.
- `GET /health` — health check.

Run responses are the normal ticket response plus documented extra fields `decision`, `approver` and `decided_at` (null before a decision). Once decided, `human_approval_required` becomes `false`; the ledger status changes from `PROPOSED` to `APPROVED` or `REJECTED` on the same entry.

## Evaluation

```bash
python eval/run_eval.py --label baseline        # LLM disabled by default
python eval/run_eval.py --label after --llm     # optional LLM-enabled run
```

The pass rule is stored in `eval/cases.json`: all expected ticket type, outcome, reason codes, approver, approval flag, billable amount, ledger action and reply phrases must match. Each run writes a timestamped JSON file under `eval/results/` with per-request latency, cost, model calls and failure reasons.

## Render deployment

`render.yaml` and `Procfile` use `python -m src.solution`, which reads `PORT`. After deployment, smoke-test every endpoint:

```bash
python smoke_test.py https://your-service.onrender.com
```

## Tests

```bash
python -m pytest -q
```
