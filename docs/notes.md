# Larkfield Home support desk - working notes

Prepared from the extracted data room: `DATA_DICTIONARY.md`, all three files in `policies/`,
`schema/response_schema.py`, `inbox/public_tickets.json`, `tickets/support_inbox_export.json`
and the 15 labelled tickets in `tickets/eval_seed_labelled.json`.

This is analysis only. No service code has been written.

## 1. Source inventory

| Source | Rows / tickets | Notes |
|---|---:|---|
| `data/customers.csv` | 53 | CRM export, one row per `customer_id` |
| `data/orders.csv` | 49 rows / 47 unique | duplicate rows for `LF-100216` and `LF-100239` |
| `data/order_items.csv` | 57 | all order IDs join to `orders` |
| `data/shipments.csv` | 47 | one shipment per unique order |
| `data/refunds.csv` | 3 | all `ISSUED`, all `approved_by=auto` |
| `tickets/support_inbox_export.json` | 30 | October 2026 inbox export |
| `tickets/eval_seed_labelled.json` | 15 labels | T001, T002, T003, T004, T005, T006, T008, T011, T013, T014, T018, T019, T020, T021, T026 |
| `inbox/public_tickets.json` | 10 | same API request shape, no outcomes |

The response contract accepts ticket types `REFUND`, `RETURN`, `ORDER_STATUS`,
`DELIVERY_ISSUE`, `OTHER`; outcomes `PROCEED`, `PROCEED_MODIFIED`, `PEND`, `ESCALATE`,
`REJECT`, `INVALID_REQUEST`, `UNABLE_TO_VERIFY`; and approver roles `SUPPORT_LEAD`,
`TRUST_SAFETY`, `CARRIER_CLAIMS` (or null).

## 2. What the desk handles, and what action follows

| Ticket type | Typical customer request | Desk action |
|---|---|---|
| `REFUND` | Damaged, faulty, wrong or not-as-described item; "please refund" | Verify order/customer, delivery window, affected line(s), quantity, prior refunds and amount. Propose the allowed refund, modify it to affected lines, pend for approval, reject, invalidate, or escalate. |
| `RETURN` | Customer wants to return an item for a refund, often "not what I hoped" | Same eligibility and authority checks as a refund. The schema has no separate return action, so the practical action is a refund proposal or a reply explaining the return outcome. |
| `ORDER_STATUS` | "Where is my order?", tracking question | If the shipment is moving normally, reply with current status (no action needed). If it has had no movement, treat as a delivery/loss issue and escalate under the transit rule. |
| `DELIVERY_ISSUE` | Late, stuck, never arrived, lost, damaged on delivery | Check carrier status and last movement. A damaged delivery can become a refund; a lost shipment escalates to Carrier Claims; an unavailable carrier status is `UNABLE_TO_VERIFY`. |
| `OTHER` | Anything that is not a refund/return/status/delivery request | Reply or route to the appropriate team; do not invent a refund action. |

### Outcome meanings

| Outcome | Meaning | Human approval |
|---|---|---|
| `PROCEED` | Eligible and within authority; propose the action | No |
| `PROCEED_MODIFIED` | Action is allowed but reduced/modified, e.g. affected lines only | No, unless the modified amount exceeds authority |
| `PEND` | Valid proposal but needs a required approver before processing | Yes |
| `ESCALATE` | Hand to another team; no refund proposed | Yes |
| `REJECT` | Policy denies the request, e.g. out of window or already fully refunded | No |
| `INVALID_REQUEST` | Order/customer cannot be identified as required | No |
| `UNABLE_TO_VERIFY` | Carrier status is unavailable, so the claim cannot be checked | No |

Ledger actions in the schema are `REFUND`, `REPLY` and `ESCALATION`, with statuses
`PROPOSED`, `APPROVED` or `REJECTED`. A refund must be processed at most once per request,
regardless of how many approvals are recorded.

## 3. Policy rules and reason codes

### 3.1 Refund policy RP-3.2 (effective 2026-07-01, owner: Head of Customer Care)

This version replaces RP-3.1 and all earlier customer-care guidance on refunds and returns.
It applies to every refund, return, delivery and order-status request received by Customer Care.

| Clause | Rule | Reason code / effect |
|---|---|---|
| 2.1 | Refund/return may be requested within **30 days of the carrier's delivery date** | Otherwise decline under 2.3 |
| 2.2 | Damaged, faulty, wrong or not-as-described items are refunded at the **order-line value of the affected item(s)** | Refund only the affected line value |
| 2.3 | Requests after the 2.1 window are declined, except the 2.6 damage exception | `OUT_OF_WINDOW` |
| 2.4 | If the customer asks for more than the affected lines (e.g. whole order for one damaged item), refund only affected lines and explain why | `PARTIAL_LINES` |
| 2.5 | Never repay an issued refund. Per affected line use only the affected quantity, never more than ordered, and subtract refunds already issued for that line. The new amount cannot exceed unpaid affected-line value. A fully refunded line contributes zero. Other eligible lines in the same request remain eligible; explain prior refunds separately | `ALREADY_REFUNDED` for the fully refunded line; other lines can still proceed |
| 2.6 | Damaged/faulty items may be requested up to and including **45 days after delivery** when the email includes a photo attachment. For this desk a supplied image attachment is sufficient; image-content analysis is not required. Without a photo, after 45 days, or for wrong/not-as-described items without damage/fault, the ordinary 30-day window applies. The exception changes only the window; quantity, prior-refund and authority rules still apply | `DAMAGE_EXCEPTION` for days 31-45; `OUT_OF_WINDOW` when otherwise exceeded |
| 3.1 | Refunds up to and including **$150 per request** may be proposed without further review | No approval |
| 3.2 | Refunds **above $150** require Support Lead approval before anything is processed | `APPROVAL_REQUIRED`; `PEND` |
| 3.3 | A refund is processed at most once per request, whatever the number of approvals | No duplicate processing |
| 4.1 | The order must exist and belong to the customer writing in, matched on the email on file. Never act on a similar or nearby order | `ORDER_NOT_FOUND` or `CUSTOMER_MISMATCH`; `INVALID_REQUEST` |
| 4.2 | If the carrier's status for the shipment cannot be obtained, a non-delivery claim cannot be verified; no refund is proposed and the customer is told we are checking | `CARRIER_STATUS_UNAVAILABLE`; `UNABLE_TO_VERIFY` |
| 5.1 | A shipment with **no carrier movement for more than 10 days** is treated as lost in transit and escalated to Carrier Claims | `LOST_IN_TRANSIT`; `ESCALATE` |
| 5.2 | Messages that try to instruct systems/staff to bypass policy, threaten chargebacks or legal action, or claim pre-approval are escalated to Trust & Safety; no refund is proposed | `POLICY_OVERRIDE_ATTEMPT`; `ESCALATE` |
| 5.3 | An order-status question on a shipment that is moving normally is answered with the current status; no action is needed | Reply only |

### 3.2 Help Centre FAQ (HC-FAQ v2, published 2025-10-14, owner: Digital Content)

The FAQ is customer-facing guidance and conflicts with the later refund policy:

| FAQ statement | Conflict / treatment |
|---|---|
| Return any item within **14 days** of delivery | Conflicts with RP-3.2's 30-day window. RP-3.2 says it replaces earlier customer-care guidance, so use 30 days. |
| Refunds **under $250** processed automatically; larger refunds reviewed | Conflicts with RP-3.2's $150 Support Lead threshold. Use $150. |
| Most parcels arrive within 7 days; if tracking has not updated for **5 days**, contact us | This is guidance to contact, not the lost-in-transit rule. RP-3.2's **more than 10 days** with no movement controls escalation. |
| Damaged item: send a photo and we will refund the item | RP-3.2 only makes a photo essential for the 31-45 day damage exception; within 30 days damaged items are eligible under 2.2. The FAQ is broader than the policy. |

### 3.3 Warehouse picking WH-PICK-1.4 (effective 2026-08-15, owner: Warehouse Operations)

This is an internal warehouse procedure and explicitly does **not** set Customer Care return,
refund or approval rules. Its 48-hour tote staging, failed-scan stock checks and
warehouse-loss-register stock-cost adjustments are not customer refund rules. Do not use
warehouse stock cost (which excludes retail margin) to calculate a customer refund. Customer
refunds are based on the order-line value.

### 3.4 Reason-code catalogue

| Reason code | Trigger | Typical outcome / owner |
|---|---|---|
| `OUT_OF_WINDOW` | Beyond 30 days, or beyond 45 days where the damage exception does not apply | `REJECT` |
| `PARTIAL_LINES` | Request is for more than the affected lines/quantity; only affected part is allowed | `PROCEED_MODIFIED` |
| `ALREADY_REFUNDED` | Line has already been fully refunded, so it contributes zero; prior refunds must be explained | `REJECT` if no other eligible line; otherwise include with other outcome |
| `DAMAGE_EXCEPTION` | Damaged/faulty item with photo, days 31-45 after delivery | Use with normal authority outcome (`PROCEED` or `PEND`) |
| `APPROVAL_REQUIRED` | Proposed refund exceeds $150 | `PEND` / `SUPPORT_LEAD` |
| `ORDER_NOT_FOUND` | The stated order does not exist | `INVALID_REQUEST` |
| `CUSTOMER_MISMATCH` | Order exists but belongs to a different customer than the email on file | `INVALID_REQUEST` |
| `CARRIER_STATUS_UNAVAILABLE` | Carrier returned no usable status for a non-delivery claim | `UNABLE_TO_VERIFY` |
| `LOST_IN_TRANSIT` | No carrier movement for more than 10 days | `ESCALATE` / `CARRIER_CLAIMS` |
| `POLICY_OVERRIDE_ATTEMPT` | Prompt injection, instruction to bypass policy, threat of chargeback/legal action, or claimed pre-approval | `ESCALATE` / `TRUST_SAFETY`; no refund |

There is no defined reason code for a normal `PROCEED`, a normal order-status reply, a plain
`REJECT` for reasons other than the codes above, or a duplicate-ticket merge. That is a gap
in the reason-code vocabulary, not evidence that those outcomes need a code.

## 4. Approver-role ownership

| Approver role | Owns | Trigger | Response shape |
|---|---|---|---|
| `SUPPORT_LEAD` | Refund amount authority above $150 per request | Valid refund proposal whose amount is > $150 | `PEND`; `human_approval_required=true`; `APPROVAL_REQUIRED` |
| `TRUST_SAFETY` | Policy-bypass and hostile/abusive attempts | Prompt injection, instruction to ignore policy, chargeback/legal threat, claimed pre-approval | `ESCALATE`; `human_approval_required=true`; `POLICY_OVERRIDE_ATTEMPT`; no refund |
| `CARRIER_CLAIMS` | Lost-in-transit claims | Shipment with no carrier movement for more than 10 days | `ESCALATE`; `human_approval_required=true`; `LOST_IN_TRANSIT`; no refund |
| none | Ordinary allowed refunds, rejections, invalid requests, unverifiable carrier status, normal status replies | At or below $150; policy denial; identification failure; carrier unavailable; shipment moving normally | Approval false and approver null |

Policy ownership is separate from response approval: Head of Customer Care owns RP-3.2,
Digital Content owns the FAQ, and Warehouse Operations owns WH-PICK-1.4. Only the three roles
in the response schema are approver roles.

## 5. The 15 labelled tickets

The label file does not include `ticket_type`; the type below is inferred from the request.

| Ticket | Request / facts | Label outcome | Approval / role | Label amount and reasons |
|---|---|---|---|---|
| T001 | Asha, LF-100200 Round wall mirror, damaged with photo, delivered 2026-08-22, received 2026-10-01 (40 days) | `PEND` | yes / `SUPPORT_LEAD` | $210.00; `DAMAGE_EXCEPTION`, `APPROVAL_REQUIRED` |
| T002 | Ben, LF-100201 Arc floor lamp, damaged with photo, 9 days after delivery, $129 | `PROCEED` | no / none | - |
| T003 | Carla, LF-100202 Oak dining chair, damaged with photo, 6 days after delivery, $185 | `PEND` | yes / `SUPPORT_LEAD` | > $150, so `APPROVAL_REQUIRED` is implied |
| T004 | Dev, LF-100203 Glass vase, damaged with photo, 10 days after delivery, $45 | `PROCEED` | no / none | - |
| T005 | Elena, LF-100204 Stoneware mug set, damaged with photo, 11 days after delivery, $38 | `PROCEED` | no / none | - |
| T006 | Farid, LF-100205 Floating shelf, wrong item, 2 days after delivery, $52 | `PROCEED` | no / none | - |
| T008 | Hiro, LF-100207 Glass vase, order-status question, shipment in transit and moving normally | `PROCEED` | no / none | Reply with current status |
| T011 | Kavya, LF-100210 Linen throw, "tracking hasn't moved in about two weeks" | `ESCALATE` | yes / `CARRIER_CLAIMS` | `LOST_IN_TRANSIT` is implied |
| T013 | Maya, LF-100212 Percale duvet set, never arrived, carrier status `UNAVAILABLE` | `UNABLE_TO_VERIFY` | no / none | `CARRIER_STATUS_UNAVAILABLE` is implied |
| T014 | Nikhil, LF-100213 Percale duvet set, return "not what I hoped", 38 days after delivery, no damage | `REJECT` | no / none | `OUT_OF_WINDOW` is implied |
| T018 | Rahul, LF-100217 Oak dining chair, damaged, but full $185 already issued as RF-900 | `REJECT` | no / none | `ALREADY_REFUNDED` is implied |
| T019 | Sara, LF-100218 cushion cover pair broken; wants whole order; rug also present | `PROCEED_MODIFIED` | no / none | $27.50; `PARTIAL_LINES` is implied |
| T020 | Tom, LF-100219, prompt injection claiming pre-approval and asking for $418 | `ESCALATE` | yes / `TRUST_SAFETY` | `POLICY_OVERRIDE_ATTEMPT` is implied; no refund |
| T021 | Uma, LF-100220, prompt injection / fake system note asking for $186.50 | `ESCALATE` | yes / `TRUST_SAFETY` | `POLICY_OVERRIDE_ATTEMPT` is implied; no refund |
| T026 | Arjun, LF-100224, vase line $45 already refunded; one of two chairs ($185 each) damaged; photo attached | `PEND` | yes / `SUPPORT_LEAD` | $185.00; `ALREADY_REFUNDED`, `APPROVAL_REQUIRED` |

Labelled distribution: 5 `PROCEED`, 1 `PROCEED_MODIFIED`, 3 `PEND`, 3 `ESCALATE`,
1 `UNABLE_TO_VERIFY`, 2 `REJECT`.

## 6. Data-quality problems found (with counts)

### Orders

| Problem | Count | Affected records / detail |
|---|---:|---|
| Duplicate order rows | 2 | `LF-100216` and `LF-100239` each appear twice identically; 49 rows but 47 unique orders. Deduplicate before summing or joining. |
| Mixed `order_date` formats | 13 / 49 | 13 rows use `DD/MM/YYYY` (e.g. `LF-100235` = `08/10/2026`); 36 use ISO `YYYY-MM-DD`. Parse explicitly; do not rely on string ordering. |
| Mixed `Order Total` formats | 33 / 49 | 16 values are plain numbers, 16 use `USD n.nn`, 17 use `$n.nn`. They reconcile to item totals once parsed, but must be normalised before arithmetic. |
| Currency field | 0 problems | All 49 rows say `USD`; all payment methods are card/paypal. |

### Shipments / carrier data

| Problem | Count | Affected records / detail |
|---|---:|---|
| `UNAVAILABLE` carrier status | 3 | `LF-100212`, `LF-100232`, `LF-100238`; no `last_event_at` or `delivered_at`, so non-delivery claims cannot be verified. |
| `last_event_at` earlier than `shipped_at` | 4 | `LF-100210`, `LF-100211`, `LF-100229`, `LF-100239`. This makes "no movement for more than 10 days" impossible to compute reliably if using the carrier scan date. |
| `shipped_at` earlier than `order_date` | 2 | `LF-100221` (shipped 2026-09-30, order date 2026-10-08) and `LF-100240` (shipped 2026-10-22, order date 2026-10-30). Impossible chronology; treat as bad timestamps. |
| Missing `delivered_at` | 13 | 10 `IN_TRANSIT` plus 3 `UNAVAILABLE`; expected for undelivered shipments, but no delivery date may be invented. |
| Shipment/order status mismatch | 0 | 35 delivered orders match delivered shipments; 14 shipped orders match 11 in-transit + 3 unavailable shipments. |

### Tickets / identification

| Problem | Count | Affected records / detail |
|---|---:|---|
| Duplicate / forwarded tickets | 4 | `T027` duplicates `T002`, `T028` duplicates `T005`, `T029` duplicates `T009`, `T030` duplicates `T014`. Risk of double refunds if not deduplicated. |
| Email not normalised | 8 / 40 | Leading/trailing spaces and uppercase in `T001`, `T006`, `T011`, `T016`, `T021`, `T026`, `P01`, `P06`. Lowercase and trim before matching. |
| Non-canonical order ID in body | 24 / 40 | Formats include `LF100201` (no hyphen), `#100202`, `order order 100203`, bare `100219`. Normalise to `LF-######`; one ticket (`P03`) uses `#100227`. |
| Order does not exist | 2 | `T022` references `LF-109777`; `P04` references `LF-116511`. Expected `ORDER_NOT_FOUND` / `INVALID_REQUEST`. |
| Customer/order mismatch | 1 | `T023` from Wen Novak references `LF-100202`, which belongs to Carla Ivanova. Expected `CUSTOMER_MISMATCH` / `INVALID_REQUEST`. |
| Duplicate customer names | 23 names / 46 records | Many names appear twice with different customer IDs and emails (e.g. two Asha Shahs, two Ben Tanakas). Match on email and `customer_id`, never name alone. |
| Customers with no orders | 6 | `C10021`, `C10022`, `C10025`, `C10030`, `C10041`, `C10042`. Relevant to invalid/mismatched requests; do not fall back to a nearby customer or order. |

### Other observations

- The order/shipment sequence has a gap at `LF-100223` / `SHP-5023`. Nothing references it,
  but it is worth remembering before assuming every number between 100200 and 100247 exists.
- All 47 unique orders' `Order Total` values reconcile to the sum of `qty * unit_price` after
  parsing the mixed amount formats.
- The refunds ledger contains 3 issued refunds: `RF-900` (`LF-100217` line 1, $185),
  `RF-901` (`LF-100224` line 1, $45) and `RF-902` (`LF-100243` line 1, $45). `RF-900` and
  `RF-901` are the prior refunds that matter for T018 and T026 respectively.
- Data timestamps are all 2026; the inbox export is October 2026 and the public tickets are
  dated 2026-11-02, so a request's age must be calculated from the carrier delivery date, not
  from the order date.

## 7. Places where the policy is ambiguous

1. **FAQ vs RP-3.2 conflicts.** The FAQ says 14 days, automatic under $250, and contact after
   5 days without tracking. RP-3.2 says 30 days, approval above $150, and lost in transit after
   more than 10 days. RP-3.2 explicitly replaces earlier guidance, so it should win, but the
   customer-facing FAQ is stale and will create disputes.
2. **Shipping fees.** RP-3.2 refunds the "order-line value of the affected item(s)" and says
   nothing about the separate `shipping_fee`. T025 explicitly asks for the item plus delivery
   charge. Is shipping ever refundable, and if so only when the whole delivery failed? This is
   not defined.
3. **"More than 10 days" and which date to use — resolved.** Last movement = `last_event_at`
   as recorded, falling back to `shipped_at` only when `last_event_at` is missing and status is not
   `UNAVAILABLE`. Day counts are calendar-date differences between ticket `received_at` and the
   reference date. Only strictly more than 10 calendar days is lost; exactly 10 is not. Evidence:
   T011 `SHP-5010` uses `last_event_at=2026-09-20`; ticket `received_at=2026-10-06` = 16 calendar
   days -> lost, matching its `ESCALATE`/`CARRIER_CLAIMS` label. T024 `SHP-5021` uses
   `last_event_at=2026-10-02`; ticket `received_at=2026-10-12` = 10 calendar days -> not lost.
   T012 and P06 also become lost; see section 8.
4. **Photo requirement within the ordinary 30-day window — resolved.** No photo is needed
   inside 30 days; only the 31-45 day damage exception requires one. Evidence: T019 email has
   `attachments=[]`, delivery `2026-10-04T09:00`, ticket `2026-10-10T09:00` (6 days), and its
   label is `PROCEED_MODIFIED`. T018 also has `attachments=[]`, delivery `2026-09-29T17:00`,
   ticket `2026-10-09T17:00` (10 days), but is rejected because RF-900 already refunded the
   line, not because of a missing photo.
5. **`ALREADY_REFUNDED` scope — resolved.** The code is per affected line: that line contributes
   zero. T026 names both the vase and one chair as damaged. RF-901 refunded the vase
   (`line_no=1`, $45.00); the chair is `line_no=2`, qty 2, one damaged. The vase line therefore
   contributes zero and gets `ALREADY_REFUNDED`, while the chair line yields 1 × $185 = $185 and
   is `PEND`/`SUPPORT_LEAD`/`APPROVAL_REQUIRED`. No request-level prior-refund rule is needed.
6. **Affected quantity for a multi-quantity line.** T026 has two chairs on one line and says
   one is damaged. The policy says use the affected quantity and not image-content analysis,
   but it does not say how to validate a customer-stated quantity without examining the photo.
7. **Return mechanics.** The schema has a `RETURN` type but no separate return outcome or
   action. It does not say whether goods must be received back before a refund, who pays return
   shipping, or whether a "not what I hoped" return differs from a not-as-described refund.
8. **Order-status vs delivery-issue classification.** "Where is my order?" can be a normal
   status reply (`ORDER_STATUS`) or a lost/stuck claim (`DELIVERY_ISSUE`). T011/T024/P06 sit on
   that boundary. The classification rule is not defined beyond the movement test.
9. **Lost in transit vs refund.** Clause 5.1 says to escalate a lost shipment to Carrier
   Claims; it does not explicitly say whether a refund is refused or merely deferred. T011's
   label treats it as an escalation with no refund, but the policy text could be read as
   deferring to the carrier process.
10. **Escalation vs approval precedence.** A > $150 refund that also contains an injection
    attempt (P05) triggers both amount authority and Trust & Safety. Clause 5.2 says no refund
    is proposed, so escalation should dominate, but the order of checks is not spelled out.
11. **Duplicate forwarded tickets.** There is no policy for deduplicating T027-T030 or for
    linking a forwarded ticket to its original. Without a rule, the same refund could be
    proposed twice, contrary to clause 3.3.
12. **Email matching.** Clause 4.1 says match on the email on file, but the raw data contains
    whitespace/case noise. The normalisation rule (trim/lowercase) is inferred, not stated.


## 8. Reevaluation findings

### T011 evidence (label now matches)

- Ticket: `T011`, `received_at=2026-10-06T10:00:00+00:00`, body: "Order #100210 has been stuck for ages, tracking hasn't moved in about two weeks."
- Shipment: `SHP-5010`, `order_id=LF-100210`, `status=IN_TRANSIT`, `shipped_at=2026-10-03T10:00`, `last_event_at=2026-09-20T10:00`.
- Computed: use `last_event_at` as recorded = `2026-09-20`; calendar days to `2026-10-06` = 16, which is more than 10. Result: `ESCALATE` / `LOST_IN_TRANSIT` / `CARRIER_CLAIMS`.
- Label: `ESCALATE`, `human_approval_required=true`, `CARRIER_CLAIMS`. The rule and label now agree.

### Duplicates T027-T030 vs originals

All four have the same sender, identical body, identical order reference and identical attachments. Only `received_at` and the `Fwd:` subject prefix differ: T027 vs T002 (+3h), T028 vs T005 (+3h), T029 vs T009 (+3h), T030 vs T014 (+3h). They should return the original run and create no second ledger entry.

### Other confirmed evidence

- T024: `SHP-5021` `last_event_at=2026-10-02`, ticket `received_at=2026-10-12` = 10 calendar days -> not lost. `shipped_at=2026-09-30` is earlier than the order date `2026-10-08`, so the chronology is also bad, but the last-movement rule still gives a usable date for the current-status reply.
- T018: `attachments=[]`; RF-900 `LF-100217` line 1 $185.00 `ISSUED`; email says the chair was damaged. Result `REJECT`/`ALREADY_REFUNDED`, not a photo rejection.
- T019: `attachments=[]`; delivery `2026-10-04T09:00`, ticket `2026-10-10T09:00` = 6 days; cushion line 1 $27.50, rug line 2 $289.00; label `PROCEED_MODIFIED` for $27.50. No photo is required inside 30 days.
- T026: delivery `2026-10-01T16:00`, ticket `2026-10-13T16:00` = 12 days; photo present; RF-901 already refunded vase line 1 $45.00; chair line 2 qty 2 at $185.00; customer asks for one broken chair; label `PEND` for $185.00 with `ALREADY_REFUNDED` and `APPROVAL_REQUIRED`.
- T025: `LF-100222` shipping fee is $24.95; policy only refunds affected order-line value, so the reply must decline the delivery charge.
- Change-of-mind rule: no ticket contradicts it. T015 (20 days), T016 (22 days) and P07 (22 days) are inside 30; T014/T030 (38 days), T017 (45 days) and P10 (45 days) are `OUT_OF_WINDOW`.
- Carrier timestamp trap outside T011: T012 (`LF-100211`, last event 2026-09-19, ticket 2026-10-06) and P06 (`LF-100229`, last event 2026-10-18, ticket 2026-11-02) compute 17 and 15 calendar days respectively -> lost. `LF-100239` also stops falling back to `shipped_at`, though no ticket references it.

