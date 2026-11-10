from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi import HTTPException

from schema.response_schema import Decision
from src.facts import extract_facts
from src.service import process_ticket
from src.storage import RunStore


def ticket_for(data, order_id: str, ticket_id: str, received_at: str, body: str, subject: str = "Request") -> dict:
    order = data.orders_by_id[order_id]
    customer = data.customer_for(order)
    return {
        "ticket_id": ticket_id,
        "received_at": received_at,
        "channel": "email",
        "from": customer.email,
        "to": "support@larkfield.example",
        "subject": subject,
        "body": body,
        "attachments": [],
    }


def test_first_decision_wins_and_non_waiting_runs_are_unchanged(data, inbox_tickets, tmp_path):
    store = RunStore(tmp_path / "runs.db")
    tickets = {ticket["ticket_id"]: ticket for ticket in inbox_tickets}

    pending = process_ticket(tickets["T003"], data=data, store=store)
    before = store.get_run(pending.run_id)
    assert before["human_approval_required"] is True
    assert before["decision"] is None

    approved = store.record_decision(
        pending.run_id, Decision(decision="approve", approver="Support Lead")
    )
    assert approved["human_approval_required"] is False
    assert approved["decision"] == "approve"
    assert approved["approver"] == "Support Lead"
    assert approved["decided_at"]
    assert store.ledger_for(pending.run_id)[0]["status"] == "APPROVED"

    repeated = store.record_decision(
        pending.run_id, Decision(decision="reject", approver="Someone Else")
    )
    assert repeated["decision"] == "approve"
    assert repeated["approver"] == "Support Lead"
    assert repeated["decided_at"] == approved["decided_at"]
    assert store.ledger_for(pending.run_id)[0]["status"] == "APPROVED"
    assert len(store.ledger_for(pending.run_id)) == 1

    normal = process_ticket(tickets["T002"], data=data, store=store)
    unchanged = store.record_decision(
        normal.run_id, Decision(decision="approve", approver="Support Lead")
    )
    assert unchanged["human_approval_required"] is False
    assert unchanged["decision"] is None
    assert store.ledger_for(normal.run_id)[0]["status"] == "PROPOSED"
    store.close()


def test_run_and_ledger_endpoints(data, inbox_tickets, tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DB_PATH", str(tmp_path / "default.db"))
    from src.api import create_app

    store = RunStore(tmp_path / "api.db")
    app = create_app(data=data, store=store)
    tickets = {ticket["ticket_id"]: ticket for ticket in inbox_tickets}
    response = process_ticket(tickets["T002"], data=data, store=store)

    get_run = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/runs/{run_id}")
    get_ledger = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ledger")

    assert get_run(response.run_id)["run_id"] == response.run_id
    with pytest.raises(HTTPException) as error:
        get_run("run_unknown")
    assert error.value.status_code == 404

    entries = get_ledger()
    assert entries[-1]["run_id"] == response.run_id
    assert set(entries[-1]) >= {
        "run_id", "ticket_id", "action", "amount_usd", "status", "recorded_at"
    }
    store.close()


def test_dedupe_only_when_order_id_is_found(data, tmp_path):
    store = RunStore(tmp_path / "runs.db")
    first = {
        "ticket_id": "NOORDER1",
        "received_at": "2026-10-01T10:00:00+00:00",
        "channel": "email",
        "from": "nobody@mail.example",
        "to": "support@larkfield.example",
        "subject": "Refund",
        "body": "Please refund my order.",
        "attachments": [],
    }
    second = dict(first, ticket_id="NOORDER2")
    one = process_ticket(first, data=data, store=store)
    two = process_ticket(second, data=data, store=store)

    assert one.run_id != two.run_id
    assert len(store.all_ledger()) == 2
    store.close()


def test_single_line_fallback_and_multi_line_clarification(data, engine):
    single = ticket_for(
        data,
        "LF-100200",
        "SINGLE",
        "2026-08-25T10:00:00+00:00",
        "Please refund order LF-100200. It arrived damaged.",
        "Damaged item",
    )
    single_result = engine.evaluate(single, extract_facts(single))
    assert single_result.amount_usd == Decimal("210.00")
    assert single_result.outcome == "PEND"
    assert not single_result.clarification

    multi = ticket_for(
        data,
        "LF-100218",
        "MULTI",
        "2026-10-10T10:00:00+00:00",
        "Please refund the damaged item on order LF-100218.",
        "Damaged item",
    )
    multi_result = engine.evaluate(multi, extract_facts(multi))
    assert multi_result.ticket_type == "OTHER"
    assert multi_result.outcome == "PROCEED"
    assert multi_result.amount_usd is None
    assert multi_result.ledger_action == "REPLY"
    assert multi_result.clarification is True


def test_delivered_shipment_does_not_escalate_as_lost(data, engine):
    ticket = ticket_for(
        data,
        "LF-100222",
        "DELIVERED",
        "2026-12-31T10:00:00+00:00",
        "My order LF-100222 never arrived and is lost.",
        "Never arrived",
    )
    result = engine.evaluate(ticket, extract_facts(ticket))
    assert result.outcome == "PROCEED"
    assert "LOST_IN_TRANSIT" not in result.reason_codes
    assert result.ledger_action == "REPLY"
    assert result.carrier_status == "DELIVERED"
    assert "DELIVERED" in result.to_response(ticket, "run_test").draft_reply.body
