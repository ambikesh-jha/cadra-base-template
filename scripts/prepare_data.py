#!/usr/bin/env python3
"""One-command, read-only data preparation and data-quality report."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_store import DataStore  # noqa: E402
from src.normalise import (  # noqa: E402
    extract_order_id,
    normalise_email,
    parse_date,
    parse_datetime,
)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    data = DataStore.load(ROOT / "data")
    orders_raw = rows(ROOT / "data/orders.csv")
    shipments_raw = rows(ROOT / "data/shipments.csv")

    iso_dates = sum(1 for row in orders_raw if re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["order_date"].strip()))
    dmy_dates = sum(1 for row in orders_raw if re.fullmatch(r"\d{2}/\d{2}/\d{4}", row["order_date"].strip()))
    plain_total = sum(1 for row in orders_raw if re.fullmatch(r"\d+(\.\d+)?", row["Order Total"].strip()))
    usd_total = sum(1 for row in orders_raw if row["Order Total"].strip().upper().startswith("USD"))
    dollar_total = sum(1 for row in orders_raw if row["Order Total"].strip().startswith("$"))

    unavailable = sum(1 for row in shipments_raw if row["status"].strip() == "UNAVAILABLE")
    missing_delivered = sum(1 for row in shipments_raw if not row["delivered_at"].strip())
    last_before_shipped = 0
    shipped_before_order = 0
    for row in shipments_raw:
        shipped_at = parse_datetime(row["shipped_at"])
        last_at = parse_datetime(row["last_event_at"])
        shipped = parse_date(row["shipped_at"])
        delivered_order = data.orders_by_id.get(row["order_id"].strip())
        if shipped_at and last_at and last_at < shipped_at:
            last_before_shipped += 1
        if shipped and delivered_order and delivered_order.order_date and shipped < delivered_order.order_date:
            shipped_before_order += 1

    inbox = json.loads((ROOT / "tickets/support_inbox_export.json").read_text(encoding="utf-8"))
    public = json.loads((ROOT / "inbox/public_tickets.json").read_text(encoding="utf-8"))
    labelled = json.loads((ROOT / "tickets/eval_seed_labelled.json").read_text(encoding="utf-8"))
    all_tickets = inbox + public

    email_noise = sum(1 for ticket in all_tickets if ticket["from"] != normalise_email(ticket["from"]) or ticket["from"] != ticket["from"].strip())
    noncanonical = 0
    missing_order = 0
    mismatch = 0
    for ticket in all_tickets:
        order_id = extract_order_id(ticket["body"])
        if order_id and order_id not in ticket["body"]:
            noncanonical += 1
        order = data.orders_by_id.get(order_id or "")
        if not order:
            missing_order += 1
            continue
        customer = data.customer_for(order)
        if not customer or normalise_email(customer.email) != normalise_email(ticket["from"]):
            mismatch += 1

    duplicate_tickets = 0
    seen: set[tuple[str, str, str]] = set()
    for ticket in all_tickets:
        key = (
            normalise_email(ticket["from"]),
            extract_order_id(ticket["body"]) or "",
            re.sub(r"^\s*(fwd?|re):\s*", "", ticket["subject"].lower()).strip(),
        )
        if key in seen:
            duplicate_tickets += 1
        seen.add(key)

    print("Larkfield data room - read-only preparation report")
    print(f"customers={data.counts.get('customers', 0)}")
    print(
        "orders="
        f"{data.counts.get('order_rows', 0)} raw / {data.counts.get('unique_orders', 0)} unique / "
        f"{data.counts.get('duplicate_order_rows', 0)} duplicate rows"
    )
    print(f"order_items={data.counts.get('order_items', 0)} (orphans={data.counts.get('item_orphans', 0)})")
    print(f"shipments={data.counts.get('shipments', 0)}")
    print(f"refunds={data.counts.get('refunds', 0)}")
    print(f"tickets={len(inbox)} inbox + {len(public)} public; labelled={len(labelled)}")
    print("")
    print("Data quality")
    print(f"order_date formats: ISO={iso_dates}, DD/MM/YYYY={dmy_dates}")
    print(f"order total formats: plain={plain_total}, USD={usd_total}, $={dollar_total}")
    print(f"carrier status UNAVAILABLE={unavailable}")
    print(f"missing delivered_at={missing_delivered}")
    print(f"last_event_at before shipped_at={last_before_shipped}")
    print(f"shipped_at before order_date={shipped_before_order}")
    print(f"email case/whitespace noise={email_noise}/{len(all_tickets)}")
    print(f"non-canonical order ID in body={noncanonical}/{len(all_tickets)}")
    print(f"missing order={missing_order}; customer mismatch={mismatch}")
    print(f"duplicate/forwarded tickets={duplicate_tickets}")
    print("")
    print("Source files were not modified.")


if __name__ == "__main__":
    main()
