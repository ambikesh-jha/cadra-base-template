from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import src.llm as llm
import src.service as service
import src.solution as solution
from src.data_store import DataStore
from src.facts import Facts, extract_facts
from src.storage import RunStore


def test_photo_present_only_uses_attachment_metadata(monkeypatch):
    ticket = {
        "ticket_id": "PHOTO",
        "received_at": "2026-10-01T10:00:00+00:00",
        "channel": "email",
        "from": "asha.shah0@mail.example",
        "to": "support@larkfield.example",
        "subject": "Damaged item",
        "body": "The item arrived damaged and I attached a photo.",
        "attachments": [],
    }

    def fake_chat(messages):
        return (
            json.dumps(
                {
                    "order_id": "LF-100200",
                    "issue_type": "damaged",
                    "quantity": 1,
                    "photo_present": True,
                    "override_attempt": False,
                }
            ),
            llm.ModelCall(model="fake", input_tokens=1, output_tokens=1),
            0.0,
        )

    monkeypatch.setattr(llm, "_chat", fake_chat)
    model_facts, _, _ = llm.extract_facts_with_llm(ticket)
    assert model_facts is not None
    assert model_facts.photo_present is False
    assert llm.merge_facts(extract_facts(ticket), model_facts).photo_present is False


def test_duplicate_request_key_uses_regex_facts_not_model(monkeypatch, data, inbox_tickets, tmp_path):
    ticket = next(item for item in inbox_tickets if item["ticket_id"] == "T002")
    answers = iter(["faulty", "wrong"])

    def fake_extract(ticket):
        return (
            Facts(
                order_id="LF-100999",
                issue_type=next(answers),
                quantity=9,
                photo_present=True,
                override_attempt=False,
            ),
            [],
            0.0,
        )

    monkeypatch.setattr(service, "extract_facts_with_llm", fake_extract)
    store = RunStore(tmp_path / "runs.db")
    first = service.process_ticket(ticket, data=data, store=store)
    second = service.process_ticket(dict(ticket, ticket_id="T002-MODEL-CHANGED"), data=data, store=store)
    assert first.run_id == second.run_id
    assert len(store.all_ledger()) == 1
    store.close()


def test_solution_uses_port_environment(monkeypatch):
    calls = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.delenv("PORT", raising=False)
    solution.main()
    assert calls[-1][1]["port"] == 8000
    monkeypatch.setenv("PORT", "9123")
    solution.main()
    assert calls[-1][1]["port"] == 9123


@pytest.mark.parametrize("outcome", ["ESCALATE", "REJECT", "INVALID_REQUEST", "UNABLE_TO_VERIFY"])
def test_reply_validator_rejects_refund_promises_for_non_refund_outcomes(outcome, monkeypatch):
    result = SimpleNamespace(
        outcome=outcome,
        ticket_type="OTHER",
        ledger_action="ESCALATION" if outcome == "ESCALATE" else "REPLY",
        amount_usd=None,
        prior_refund_amount=None,
        reason_codes=[],
        carrier_status=None,
        last_movement=None,
        clarification=False,
        human_approval_required=outcome == "ESCALATE",
        approver_role="TRUST_SAFETY" if outcome == "ESCALATE" else None,
    )
    assert llm._reply_valid("We will issue a refund to your card.", result) is False
    assert llm._reply_valid("No refund has been proposed.", result) is True

    def fake_chat(messages):
        return (
            json.dumps({"subject": "Re", "body": "We will issue a refund to your card."}),
            llm.ModelCall(model="fake", input_tokens=1, output_tokens=1),
            0.0,
        )

    monkeypatch.setattr(llm, "_chat", fake_chat)
    fallback = llm.DraftReply(to="x", subject="s", body="template")
    reply, _, _ = llm.draft_reply_with_llm({}, result, fallback)
    assert reply is None


def test_llm_timeout_defaults_to_five_seconds(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT", raising=False)
    assert llm._timeout() == 5.0
    monkeypatch.setenv("LLM_TIMEOUT", "2.5")
    assert llm._timeout() == 2.5
