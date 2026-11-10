from __future__ import annotations

import pytest

from src.facts import extract_facts


def test_labelled_tickets_match_engine(engine, labels, inbox_tickets):
    tickets = {ticket["ticket_id"]: ticket for ticket in inbox_tickets}
    mismatches = []

    for label in labels:
        ticket = tickets[label["ticket_id"]]
        result = engine.evaluate(ticket, extract_facts(ticket))
        problems = []

        if result.outcome != label["expected_outcome"]:
            problems.append(f"outcome={result.outcome} expected={label['expected_outcome']}")
        if result.human_approval_required != label["expected_human_approval_required"]:
            problems.append(
                f"approval={result.human_approval_required} expected={label['expected_human_approval_required']}"
            )
        if result.approver_role != label["expected_approver_role"]:
            problems.append(
                f"approver={result.approver_role} expected={label['expected_approver_role']}"
            )
        if "expected_amount_usd" in label:
            actual = float(result.amount_usd) if result.amount_usd is not None else None
            if actual != label["expected_amount_usd"]:
                problems.append(f"amount={actual} expected={label['expected_amount_usd']}")
        if "expected_reason_codes" in label:
            if set(result.reason_codes) != set(label["expected_reason_codes"]):
                problems.append(
                    f"reasons={sorted(result.reason_codes)} expected={sorted(label['expected_reason_codes'])}"
                )

        if problems:
            mismatches.append(f"{label['ticket_id']}: " + "; ".join(problems))

    assert not mismatches, "\n".join(mismatches)
