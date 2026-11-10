"""Orchestration: extract facts -> deterministic engine -> response/ledger."""
from __future__ import annotations

import hashlib
from typing import Any

from schema.response_schema import DraftReply, Resolved, TicketResponse, Trace

from .data_store import DataStore
from .engine import RulesEngine
from .facts import Facts, extract_facts, ticket_get
from .llm import draft_reply_with_llm, extract_facts_with_llm, merge_facts
from .normalise import normalise_email
from .storage import RunStore


def make_run_id(ticket_id: str, request_key: str) -> str:
    digest = hashlib.sha256(f"{ticket_id}|{request_key}".encode("utf-8")).hexdigest()
    return f"run_{digest[:20]}"


def _ticket_sender(ticket: Any) -> str:
    return normalise_email(ticket_get(ticket, "from_", ticket_get(ticket, "from", "")))


def _fallback_response(ticket: Any, run_id: str) -> TicketResponse:
    sender = _ticket_sender(ticket)
    subject = str(ticket_get(ticket, "subject", "") or "")
    return TicketResponse(
        ticket_id=str(ticket_get(ticket, "ticket_id", "") or ""),
        run_id=run_id,
        ticket_type="OTHER",
        resolved=Resolved(order_id=None, customer_id=None),
        outcome="UNABLE_TO_VERIFY",
        reason_codes=[],
        checks=[],
        human_approval_required=False,
        approver_role=None,
        draft_reply=DraftReply(
            to=sender,
            subject=f"Re: {subject}".strip(),
            body=(
                "We could not verify this request automatically. We are checking it and will reply. "
                "No refund has been proposed."
            ),
        ),
        trace=Trace(
            model_calls=[],
            tools_called=["fallback"],
            documents_used=[],
            cost_usd=0.0,
        ),
    )


def process_ticket(
    ticket: Any,
    data: DataStore | None = None,
    store: RunStore | None = None,
) -> TicketResponse:
    sender = _ticket_sender(ticket)
    ticket_id = str(ticket_get(ticket, "ticket_id", "") or "")
    facts = Facts(order_id=None, issue_type="other", quantity=None, photo_present=False)
    request_key = f"{sender}||other|{ticket_id}"
    tools: list[str] = []
    model_calls = []
    cost_usd = 0.0

    try:
        data = data or DataStore.load()
        regex_facts = extract_facts(ticket)
        request_key = f"{sender}|{regex_facts.order_id or ''}|{regex_facts.issue_type}"
        if not regex_facts.order_id:
            request_key = f"{request_key}|{ticket_id}"
        model_facts, extract_calls, extract_cost = extract_facts_with_llm(ticket)
        if model_facts is not None:
            facts = merge_facts(regex_facts, model_facts)
            tools.append("llm_extractor")
        else:
            facts = regex_facts
            tools.append("regex_extractor")
        model_calls.extend(extract_calls)
        cost_usd += extract_cost

        if regex_facts.order_id and store is not None:
            existing = store.get_response_by_key(request_key)
            if existing is not None:
                return existing.model_copy(update={"ticket_id": ticket_id})

        result = RulesEngine(data).evaluate(ticket, facts)
        response = result.to_response(ticket, make_run_id(ticket_id, request_key))

        if model_facts is not None:
            llm_reply, reply_calls, reply_cost = draft_reply_with_llm(ticket, result, response.draft_reply)
        else:
            llm_reply, reply_calls, reply_cost = None, [], 0.0
        model_calls.extend(reply_calls)
        cost_usd += reply_cost
        if llm_reply is not None:
            response = response.model_copy(update={"draft_reply": llm_reply})
            tools.append("llm_reply_writer")
        else:
            tools.append("template_reply")

        trace = response.trace.model_copy(
            update={
                "model_calls": model_calls,
                "tools_called": list(dict.fromkeys(tools + response.trace.tools_called)),
                "cost_usd": cost_usd,
            }
        )
        response = response.model_copy(update={"trace": trace})

        if store is not None:
            existing = store.save_run(request_key, response, result.ledger_action, result.amount_usd)
            if existing is not None:
                return existing.model_copy(update={"ticket_id": ticket_id})
        return response
    except Exception:
        fallback = _fallback_response(ticket, make_run_id(ticket_id, request_key))
        if store is not None:
            try:
                existing = store.save_run(request_key, fallback, None, None)
                if existing is not None:
                    return existing.model_copy(update={"ticket_id": ticket_id})
            except Exception:
                pass
        return fallback
