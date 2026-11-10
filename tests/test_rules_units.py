from __future__ import annotations

from schema.response_schema import Decision
from src.facts import extract_facts
from src.service import process_ticket
from src.storage import RunStore


def test_t024_is_ten_calendar_days_and_not_lost(engine, inbox_tickets):
    ticket = next(ticket for ticket in inbox_tickets if ticket["ticket_id"] == "T024")
    result = engine.evaluate(ticket, extract_facts(ticket))
    assert result.outcome == "PROCEED"
    assert result.ledger_action == "REPLY"
    assert "LOST_IN_TRANSIT" not in result.reason_codes


def test_t011_uses_recorded_last_event_and_is_lost(engine, inbox_tickets):
    ticket = next(ticket for ticket in inbox_tickets if ticket["ticket_id"] == "T011")
    result = engine.evaluate(ticket, extract_facts(ticket))
    assert result.outcome == "ESCALATE"
    assert result.reason_codes == ["LOST_IN_TRANSIT"]
    assert result.approver_role == "CARRIER_CLAIMS"


def test_duplicate_ticket_reuses_run_and_does_not_double_ledger(data, inbox_tickets, tmp_path):
    store = RunStore(tmp_path / "runs.db")
    tickets = {ticket["ticket_id"]: ticket for ticket in inbox_tickets}
    original = process_ticket(tickets["T002"], data=data, store=store)
    duplicate = process_ticket(tickets["T027"], data=data, store=store)

    assert duplicate.run_id == original.run_id
    assert duplicate.ticket_id == "T027"
    assert len(store.all_ledger()) == 1
    assert store.all_ledger()[0]["status"] == "PROPOSED"

    updated = store.record_decision(original.run_id, Decision(decision="approve", approver="Support Lead"))
    assert updated["human_approval_required"] is False
    assert updated["decision"] is None
    assert store.ledger_for(original.run_id)[0]["status"] == "PROPOSED"
    assert len(store.all_ledger()) == 1
    store.close()
