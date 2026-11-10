# Larkfield Home - deterministic decision rules

Scope: every refund, return, delivery and order-status request. `RP-3.2` overrides `HC-FAQ v2` and `WH-PICK-1.4`; the FAQ's 14 days, $250 auto-limit and 5-day tracking advice are not used, and warehouse stock cost is never a customer amount.

## 0a. API extras

The required contract is `POST /tickets`, `GET /runs/{run_id}` (404 when unknown), `POST /runs/{run_id}/decision`, and `GET /ledger` (all ledger entries: `run_id`, `ticket_id`, `action`, `amount_usd`, `status`, `recorded_at`). `GET /runs/{run_id}/ledger` is kept as an extra for one run's entries.

A run response is the ticket response plus optional extra fields `decision`, `approver` and `decided_at`. The first decision wins: only a run with `human_approval_required=true` and no prior decision can be decided. Repeated or conflicting decisions return the run unchanged, never add a second record and never change the ledger status. A successful decision sets `human_approval_required=false` and records the decision, approver and timestamp on the same run and ledger entry.

## 0. Normalise before any check

| Input | Rule |
|---|---|
| Email | `trim().lower()`; match against the email on file, never the customer name. |
| Order ID | Find the number in the body, then the subject; normalise to `LF-######` and look up exactly. The bare-number fallback requires order/reference context, not just any six digits. Never fall back to a nearby order. |
| Dates | Parse ISO and `DD/MM/YYYY` explicitly; use the ticket's own `received_at`, never the system clock. |
| Money | Strip `USD`, `$` and commas; use Decimal; order-line value = `qty * unit_price`. |
| Orders | Deduplicate duplicate order rows by `order_id` before sums or joins. Ticket dedupe only applies when an order ID was found. |
| Shipping | Never refund the `shipping_fee`; only affected order-line value is refundable. |
| Photo | An image attachment is enough; do not inspect image content. |

## 1. Check precedence

`duplicate -> identity/order -> injection -> carrier/lost -> window -> lines/prior refunds/amount -> authority -> ledger`.

Identity, injection, carrier and window are terminal gates. A later check never overrides an earlier terminal result. Trust & Safety beats amount approval.

## 2. Decision table

| # | Check | Condition | Outcome | Reason code | Approver |
|---:|---|---|---|---|---|
| 1 | `dedupe` | Same normalised sender + order + issue type as a previous run | Return existing run | none | from prior run |
| 2 | `order_exists` | Order ID not found | `INVALID_REQUEST` | `ORDER_NOT_FOUND` | null |
| 3 | `customer_match` | Order exists but email on file differs from sender | `INVALID_REQUEST` | `CUSTOMER_MISMATCH` | null |
| 4 | `policy_override` | Bypass instruction, claimed pre-approval, chargeback/legal threat, fake system note | `ESCALATE` | `POLICY_OVERRIDE_ATTEMPT` | `TRUST_SAFETY` |
| 5 | `carrier_status` | Non-delivery claim and status is `UNAVAILABLE`, or no usable movement date | `UNABLE_TO_VERIFY` | `CARRIER_STATUS_UNAVAILABLE` | null |
| 6 | `transit_age` | Non-delivery and strictly > 10 calendar days since last movement | `ESCALATE` | `LOST_IN_TRANSIT` | `CARRIER_CLAIMS` |
| 7 | `order_status` | Shipment is moving normally and request is a status question | `PROCEED` (reply) | none | null |
| 8 | `delivery_window` | Damage/fault with photo, days 31-45 after delivery | Eligible; add `DAMAGE_EXCEPTION` | `DAMAGE_EXCEPTION` | per amount |
| 9 | `delivery_window` | Damage/fault within 30 days (photo not required) | Eligible | none | per amount |
| 10 | `delivery_window` | Wrong/not-as-described/change-of-mind within 30 days | Eligible | none | per amount |
| 11 | `delivery_window` | Beyond 30 days (or 45 without photo / non-damage) | `REJECT` | `OUT_OF_WINDOW` | null |
| 12 | `affected_lines` | Request exceeds affected lines or ordered quantity | Refund allowed part only; `PROCEED_MODIFIED` | `PARTIAL_LINES` | per amount |
| 13 | `prior_refund` | An affected line is fully refunded | That line = 0; `ALREADY_REFUNDED` | `ALREADY_REFUNDED` | per remaining amount |
| 14 | `prior_refund` | All affected lines are fully refunded | `REJECT` | `ALREADY_REFUNDED` | null |
| 15 | `amount` | Sum of unpaid affected-line value | Set amount; no shipping | none | per authority |
| 16 | `authority` | Amount <= $150 | `PROCEED` / `PROCEED_MODIFIED` | none | null |
| 17 | `authority` | Amount > $150 | `PEND` | `APPROVAL_REQUIRED` | `SUPPORT_LEAD` |
| 18 | `ledger_once` | Any completed decision | One action per request key | none | n/a |

### Key rule lines

- Last movement = `last_event_at` as recorded; fall back to `shipped_at` only when `last_event_at` is missing and status is not `UNAVAILABLE`; if neither is usable, `UNABLE_TO_VERIFY`.
- Lost and window day counts are **calendar-date differences**: `received_at.date() - reference.date()`, ignoring times. Strictly more than 10 calendar days is lost; exactly 10 is not.
- `T011` uses `last_event_at=2026-09-20`, not `shipped_at=2026-10-03`: 16 calendar days to `2026-10-06` -> lost, matching its `ESCALATE`/`CARRIER_CLAIMS` label. `T012`, `P06` and `LF-100239` also change because their recorded last event is used as-is; `T024` is 10 calendar days -> not lost.
- A non-delivery claim on `UNAVAILABLE` carrier status is never a pass, even if `shipped_at` exists.
- If the carrier records the shipment as `DELIVERED`, a non-delivery claim is answered as a delivered-status reply (`PROCEED`, no refund) and the lost-in-transit rule is not applied.
- Window is inclusive by calendar date: day 30 and day 45 still qualify; day 31-45 damage needs a photo.
- Refund quantity = customer-stated quantity, capped at `ordered_qty - refunded_qty` per line.
- Quantity missing: use ordered quantity only when the email asks for the whole line/order, otherwise 1; always cap.
- If an order has exactly one line and no line name matches, use that line. If it has several lines and none match, send a clarification reply (`OTHER`) and propose no refund.
- Refund amount = remaining affected value minus prior issued refunds on that line; never negative.
- Fully refunded lines contribute zero and add `ALREADY_REFUNDED`; other eligible lines still proceed.
- Ledger actions: `PROCEED`/`PROCEED_MODIFIED`/`PEND` with a positive refund -> `REFUND`; `ESCALATE` -> `ESCALATION`; `REJECT`/`INVALID_REQUEST`/`UNABLE_TO_VERIFY` and normal replies -> `REPLY`. All start `PROPOSED`; approval updates the same entry.
- A clarification reply is `ticket_type=OTHER`, `outcome=PROCEED`, no reason code, no refund, ledger `REPLY` `PROPOSED`. Use it when identity passes but the affected line cannot be mapped.
- PEND writes a `PROPOSED` refund only; approval updates that same ledger entry, never creates a second.
- Escalations, rejections, invalid requests and unverifiable claims propose no refund and create no REFUND ledger entry.
- Approver roles are only `SUPPORT_LEAD`, `TRUST_SAFETY`, `CARRIER_CLAIMS`; otherwise null.

### Ledger write per outcome

| Outcome | Ledger action | Status |
|---|---|---|
| `PROCEED` / `PROCEED_MODIFIED` + refund | `REFUND` | `PROPOSED` |
| `PEND` | `REFUND` | `PROPOSED` (awaits `SUPPORT_LEAD`) |
| `ESCALATE` | `ESCALATION` | `PROPOSED` |
| `REJECT` / `INVALID_REQUEST` / `UNABLE_TO_VERIFY` | `REPLY` | `PROPOSED` |
| Normal status reply / clarification (`PROCEED`, no refund) | `REPLY` | `PROPOSED` |

## 3. Ticket-type routing

| Type | Deterministic action |
|---|---|
| `REFUND` | Run window -> lines/prior refunds -> amount -> authority. |
| `RETURN` | Same as refund; change-of-mind is eligible within 30 days for affected line value. |
| `ORDER_STATUS` | Normal movement -> status reply; stale > 10 days -> lost escalation; unavailable -> unable to verify. |
| `DELIVERY_ISSUE` | Delivered damage -> refund path; non-delivery -> carrier/lost path. |
| `OTHER` | Reply/route only; never invent a refund. |

### Change-of-mind check

No ticket contradicts the change-of-mind rule. Inside 30 calendar days: `T015` (20), `T016` (22), `P07` (22) -> eligible. Outside 30: `T014`/`T030` (38), `T017` (45), `P10` (45) -> `OUT_OF_WINDOW`.

## 4. Rule-change evidence

| Ticket / record | Evidence | Computed result | Label |
|---|---|---|---|
| `T011` | `SHP-5010` `last_event_at=2026-09-20` is used as recorded, not `shipped_at=2026-10-03`; ticket `received_at=2026-10-06` | 16 calendar days -> `ESCALATE` / `LOST_IN_TRANSIT` / `CARRIER_CLAIMS` | matches |
| `T012` | `SHP-5011` `last_event_at=2026-09-19`; ticket `received_at=2026-10-06` | 17 calendar days -> lost | no label |
| `P06` | `SHP-5029` `last_event_at=2026-10-18`; ticket `received_at=2026-11-02` | 15 calendar days -> lost | public ticket, no label |
| `LF-100239` | `SHP-5039` `last_event_at=2026-10-29T09:00` is used as recorded instead of `shipped_at=2026-10-29T17:00` | timestamp changes; no ticket references it | n/a |
| `T024` | `SHP-5021` `last_event_at=2026-10-02`; ticket `received_at=2026-10-12` | 10 calendar days -> not lost; current-status reply | no label |

## 5. Ticket traps

| Trap | Ticket IDs |
|---|---|
| Email case/whitespace noise | `T001`, `T006`, `T011`, `T016`, `T021`, `T026`, `P01`, `P06` |
| Non-canonical order ID | `T002`, `T003`, `T004`, `T006`, `T007`, `T008`, `T010`, `T011`, `T012`, `T014`, `T015`, `T016`, `T018`, `T019`, `T020`, `T024`, `T027`, `T030`, `P02`, `P03`, `P06`, `P07`, `P08`, `P10` |
| Missing order | `T022` (`LF-109777`), `P04` (`LF-116511`) |
| Wrong sender / customer mismatch | `T023` (Wen references Carla's `LF-100202`) |
| Injection / claimed pre-approval | `T020`, `T021`, `P05` |
| Duplicate / forwarded | `T027=T002`, `T028=T005`, `T029=T009`, `T030=T014` (same sender and body; only `received_at` and `Fwd:` subject differ) |
| Whole-order ask for one affected item | `T019`, `T026`, `P08` |
| Shipping-fee ask | `T025` |
| Carrier status unavailable | `T013` (`LF-100212`), `P09` (`LF-100232`) |
| Carrier timestamp bad: last event before shipment | `T011` (`LF-100210`), `T012` (`LF-100211`), `P06` (`LF-100229`), plus `LF-100239` |
| Carrier timestamp bad: shipped before order | `T024` (`LF-100221`), plus `LF-100240` |
| Messy wording / status vs loss | `T011`, `T024`, `P06` |
| Mixed date and amount formats | Stored data, all tickets joining `orders` |
