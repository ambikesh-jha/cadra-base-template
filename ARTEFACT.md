# Artefact

## Data findings

- 53 customers, 49 order rows -> 47 unique orders with 2 duplicate rows, 57 order items (0 orphans), 47 shipments, 3 issued refunds, 40 inbox/public tickets and 15 labelled tickets.
- Order dates are mixed: 36 ISO and 13 DD/MM/YYYY. Order totals are mixed: 16 plain, 16 `USD`, 17 `$`. There are 13 missing `delivered_at` values, 4 `last_event_at` values before `shipped_at`, 2 `shipped_at` values before the order date, and 3 `UNAVAILABLE` carrier statuses.
- 8/40 emails have case/whitespace noise, 24/40 use non-canonical order IDs, 2 orders do not exist, 1 sender does not own the referenced order, and 4 tickets are duplicates/forwards.

## Policy used

`RP-3.2` version 3.2: 30-day refund/return window, photo-backed damage exception for days 31-45, $150 authority threshold, lost-in-transit after more than 10 calendar days, and affected order-line value only. `HC-FAQ v2` and `WH-PICK-1.4` were not used for customer outcomes.

## Evaluation before and after

Baseline with the LLM disabled: **15/17 passed (88.24%)**. The 2 failures were the new injection phrasings (`ignore all previous instructions`, `disregard the rules above`), which were refunded instead of escalated. After the targeted override-pattern change: **17/17 passed (100%)**.

Cost and latency in 3 lines:

1. Baseline cost: median **$0.00000000** per request, total **$0.00000000** (LLM disabled).
2. Baseline latency: median **8.626 ms**, mean **8.708 ms**, p95 **11.635 ms**.
3. After latency: median **10.111 ms**, mean **10.421 ms**, p95 **15.404 ms**, with median cost **$0.00000000** per request.

**Median cost per request:** **$0.00000000** (LLM disabled baseline and after run).

## Open-policy rule applied

When the carrier records a shipment as `DELIVERED`, a non-delivery claim gets a delivered-status reply with no refund and no lost-in-transit escalation.

## What is not built

No image-content analysis, no live carrier API, no human review UI, no automatic money movement, and no persistent multi-instance database.
