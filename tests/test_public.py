from __future__ import annotations

from decimal import Decimal

from src.facts import extract_facts


EXPECTED = {
    "P01": {"outcome": "PROCEED", "reasons": {"DAMAGE_EXCEPTION"}, "amount": Decimal("64.00"), "approver": None, "ledger": "REFUND"},
    "P02": {"outcome": "PEND", "reasons": {"APPROVAL_REQUIRED"}, "amount": Decimal("289.00"), "approver": "SUPPORT_LEAD", "ledger": "REFUND"},
    "P03": {"outcome": "PROCEED", "reasons": set(), "amount": None, "approver": None, "ledger": "REPLY"},
    "P04": {"outcome": "INVALID_REQUEST", "reasons": {"ORDER_NOT_FOUND"}, "amount": None, "approver": None, "ledger": "REPLY"},
    "P05": {"outcome": "ESCALATE", "reasons": {"POLICY_OVERRIDE_ATTEMPT"}, "amount": None, "approver": "TRUST_SAFETY", "ledger": "ESCALATION"},
    "P06": {"outcome": "ESCALATE", "reasons": {"LOST_IN_TRANSIT"}, "amount": None, "approver": "CARRIER_CLAIMS", "ledger": "ESCALATION"},
    "P07": {"outcome": "PROCEED", "reasons": set(), "amount": Decimal("45.00"), "approver": None, "ledger": "REFUND"},
    "P08": {"outcome": "PROCEED_MODIFIED", "reasons": {"PARTIAL_LINES"}, "amount": Decimal("38.00"), "approver": None, "ledger": "REFUND"},
    "P09": {"outcome": "UNABLE_TO_VERIFY", "reasons": {"CARRIER_STATUS_UNAVAILABLE"}, "amount": None, "approver": None, "ledger": "REPLY"},
    "P10": {"outcome": "REJECT", "reasons": {"OUT_OF_WINDOW"}, "amount": None, "approver": None, "ledger": "REPLY"},
}


def test_public_tickets_match_derived_expectations(engine, public_tickets):
    mismatches = []
    for ticket in public_tickets:
        expected = EXPECTED[ticket["ticket_id"]]
        result = engine.evaluate(ticket, extract_facts(ticket))
        problems = []
        if result.outcome != expected["outcome"]:
            problems.append(f"outcome={result.outcome} expected={expected['outcome']}")
        if set(result.reason_codes) != expected["reasons"]:
            problems.append(f"reasons={sorted(result.reason_codes)} expected={sorted(expected['reasons'])}")
        actual_amount = result.amount_usd.quantize(Decimal("0.01")) if result.amount_usd is not None else None
        if actual_amount != expected["amount"]:
            problems.append(f"amount={actual_amount} expected={expected['amount']}")
        if result.approver_role != expected["approver"]:
            problems.append(f"approver={result.approver_role} expected={expected['approver']}")
        if result.ledger_action != expected["ledger"]:
            problems.append(f"ledger={result.ledger_action} expected={expected['ledger']}")
        if problems:
            mismatches.append(f"{ticket['ticket_id']}: " + "; ".join(problems))
    assert not mismatches, "\n".join(mismatches)


def test_public_tickets_are_deterministic(engine, public_tickets):
    for ticket in public_tickets:
        first = engine.evaluate(ticket, extract_facts(ticket)).to_response(ticket, "run_test")
        second = engine.evaluate(ticket, extract_facts(ticket)).to_response(ticket, "run_test")
        assert first.model_dump() == second.model_dump()
