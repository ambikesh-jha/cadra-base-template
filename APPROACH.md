# Approach

The service is deterministic first. Ticket facts are normalised and passed to an ordered rules engine ([src/engine.py](src/engine.py)); policy RP-3.2 wins over the stale FAQ and warehouse document, as recorded in [docs/rules.md](docs/rules.md).

## Claims and code

- Email, order-ID, date and money normalisation is pure and testable ([src/normalise.py](src/normalise.py)).
- Duplicate request keys use regex-derived facts only, so model variation cannot change them ([src/service.py](src/service.py)).
- The engine applies identity, injection, carrier/lost, window, affected-line, prior-refund, amount and authority checks in order ([src/engine.py](src/engine.py)).
- SQLite runs and ledger writes are locked and idempotent; the first decision wins and updates the same entry ([src/storage.py](src/storage.py)).
- The API exposes tickets, runs, decisions, all-ledger and per-run ledger endpoints ([src/api.py](src/api.py)).
- The optional LLM extracts facts and phrases replies only. Photo evidence comes from attachments, override flags escalate, and wording is rejected if it invents amounts or promises refunds on non-refund outcomes ([src/llm.py](src/llm.py)).
- Unexpected processing errors return `UNABLE_TO_VERIFY` with no ledger action ([src/service.py](src/service.py)).

## Verification

`tests/` covers labelled/public tickets and contract edge cases. The eval ([eval/run_eval.py](eval/run_eval.py)) uses [eval/cases.json](eval/cases.json), records latency and cost, and writes timestamped JSON under [eval/results/](eval/results/). Baseline was 15/17; after adding the new override phrasings it is 17/17 with the LLM disabled.

## Limits

No image-content analysis, no live carrier API, no human review UI, and no persistent multi-instance database.
