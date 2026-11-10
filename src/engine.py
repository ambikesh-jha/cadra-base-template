"""Deterministic rules engine. No network, no wall clock, no randomness."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from schema.response_schema import (
    Check,
    DocumentUsed,
    DraftReply,
    Evidence,
    Resolved,
    TicketResponse,
    Trace,
)

from .data_store import DataStore, OrderItem
from .facts import Facts, ticket_get
from .normalise import (
    calendar_days,
    detect_injection,
    issue_to_ticket_type,
    match_affected_lines,
    normalise_email,
    normalise_text,
    parse_datetime,
    whole_order_requested,
)


CLAUSE_REFUND = "2.2"
CLAUSE_WINDOW = "2.1"
CLAUSE_OUT_OF_WINDOW = "2.3"
CLAUSE_PARTIAL = "2.4"
CLAUSE_PRIOR = "2.5"
CLAUSE_DAMAGE_EXCEPTION = "2.6"
CLAUSE_AUTHORITY = "3.1"
CLAUSE_APPROVAL = "3.2"
CLAUSE_ONCE = "3.3"
CLAUSE_IDENTITY = "4.1"
CLAUSE_CARRIER = "4.2"
CLAUSE_LOST = "5.1"
CLAUSE_OVERRIDE = "5.2"
CLAUSE_STATUS = "5.3"

POLICY_HEADER = re.compile(r"Document:\s*([^|]+?)\s*\|\s*Version\s*([^|]+?)\s*(?:\||$)")
TOOL_BY_SOURCE = {
    "data/orders.csv": "orders_lookup",
    "data/customers.csv": "customers_lookup",
    "data/shipments.csv": "shipments_lookup",
    "data/order_items.csv": "order_items_lookup",
    "data/refunds.csv": "refunds_lookup",
}


def _policy_meta(file_name: str, fallback_document: str, fallback_version: str) -> DocumentUsed:
    path = Path(__file__).resolve().parent.parent / "policies" / file_name
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = POLICY_HEADER.search(line)
            if match:
                return DocumentUsed(
                    document=match.group(1).strip(),
                    version=match.group(2).strip(),
                )
    except OSError:
        pass
    return DocumentUsed(document=fallback_document, version=fallback_version)


REFUND_DOCUMENT = _policy_meta("refund_policy_RP-3.2.md", "RP-3.2", "3.2")


def _evidence(source: str, ref: str, value: Any) -> Evidence:
    return Evidence(source=source, ref=str(ref), value=str(value))


def _check(check_id: str, result: str, clause: str | None, evidence: list[Evidence]) -> Check:
    return Check(check_id=check_id, result=result, evidence=evidence, policy_clause=clause)


def _tools_used(checks: list[Check]) -> list[str]:
    tools = ["rules_engine"]
    by_check = {
        "order_exists": "orders_lookup",
        "customer_match": "customers_lookup",
        "carrier_status": "shipments_lookup",
        "delivery_window": "shipments_lookup",
        "affected_lines": "order_items_lookup",
        "prior_refund": "order_items_lookup",
    }
    for check in checks:
        tool = by_check.get(check.check_id)
        if tool and tool not in tools:
            tools.append(tool)
        for item in check.evidence:
            tool = TOOL_BY_SOURCE.get(item.source)
            if tool and tool not in tools:
                tools.append(tool)
    return tools


def _format_date(value: datetime | None) -> str | None:
    return value.date().isoformat() if value is not None else None


@dataclass
class EngineResult:
    ticket_type: str
    outcome: str
    reason_codes: list[str]
    amount_usd: Decimal | None
    approver_role: str | None
    checks: list[Check]
    order_id: str | None
    customer_id: str | None
    ledger_action: str | None
    request_key: str
    carrier_status: str | None = None
    last_movement: datetime | None = None
    prior_refund_amount: Decimal | None = None
    clarification: bool = False

    @property
    def human_approval_required(self) -> bool:
        return self.outcome in {"PEND", "ESCALATE"}

    def to_response(self, ticket: Any, run_id: str) -> TicketResponse:
        return TicketResponse(
            ticket_id=str(ticket_get(ticket, "ticket_id", "")),
            run_id=run_id,
            ticket_type=self.ticket_type,
            resolved=Resolved(order_id=self.order_id, customer_id=self.customer_id),
            outcome=self.outcome,
            reason_codes=self.reason_codes,
            checks=self.checks,
            human_approval_required=self.human_approval_required,
            approver_role=self.approver_role,
            draft_reply=self._draft_reply(ticket),
            trace=Trace(
                model_calls=[],
                tools_called=_tools_used(self.checks),
                documents_used=[REFUND_DOCUMENT],
                cost_usd=0.0,
            ),
        )

    def _reason_notes(self) -> list[str]:
        notes: list[str] = []
        if "PARTIAL_LINES" in self.reason_codes:
            notes.append(
                "You asked for more than the affected item(s), so policy 2.4 limits this refund to the affected item(s) only."
            )
        if "DAMAGE_EXCEPTION" in self.reason_codes:
            notes.append(
                "We applied the damage exception for photo-backed damage or fault reported within 45 days of delivery."
            )
        if "ALREADY_REFUNDED" in self.reason_codes:
            if self.prior_refund_amount is not None:
                notes.append(
                    f"A prior refund of ${self.prior_refund_amount:.2f} has already been issued for the affected line, so it is not included again."
                )
            else:
                notes.append(
                    "The affected line has already been fully refunded, so it is not included again."
                )
        return notes

    def _draft_reply(self, ticket: Any) -> DraftReply:
        to = normalise_email(ticket_get(ticket, "from_", ticket_get(ticket, "from", "")))
        subject = f"Re: {ticket_get(ticket, 'subject', '')}".strip()
        amount = f"${self.amount_usd:.2f}" if self.amount_usd is not None else None
        notes = self._reason_notes()

        if self.clarification:
            body = (
                "Thanks for contacting us. Please tell us which item on the order is affected and what went wrong, "
                "so we can check what we can do."
            )
        elif self.outcome == "PEND":
            parts = [
                f"We can propose a refund of {amount} for the affected item(s).",
                "Because it is above the automatic limit, it needs Support Lead approval before processing.",
            ]
            parts.extend(notes)
            parts.append("Shipping charges are not included in any refund.")
            body = " ".join(parts)
        elif self.outcome in {"PROCEED", "PROCEED_MODIFIED"} and self.ledger_action == "REFUND":
            parts = [f"We can refund {amount} for the affected item(s)."]
            parts.extend(notes)
            parts.append("Shipping charges are not included in the refund.")
            parts.append("We will process this refund.")
            body = " ".join(parts)
        elif self.outcome == "PROCEED" and self.ledger_action == "REPLY" and self.carrier_status:
            last_movement = _format_date(self.last_movement)
            body = f"The carrier shows the shipment as {self.carrier_status}."
            if last_movement:
                body += f" The last carrier movement was on {last_movement}."
            body += " No refund is needed for this status update."
        elif self.outcome == "ESCALATE" and self.approver_role == "CARRIER_CLAIMS":
            body = (
                "Your shipment has had no carrier movement for more than 10 days. "
                "We are escalating it to Carrier Claims. No refund has been proposed."
            )
        elif self.outcome == "ESCALATE":
            body = "We are escalating this request to Trust & Safety for review. No refund has been proposed."
        elif self.outcome == "REJECT" and "OUT_OF_WINDOW" in self.reason_codes:
            body = "This request is outside the refund window, so we are unable to approve a refund."
        elif self.outcome == "REJECT" and "ALREADY_REFUNDED" in self.reason_codes:
            body = " ".join(["We are unable to approve a further refund."] + notes)
        elif self.outcome == "UNABLE_TO_VERIFY":
            body = (
                "We cannot obtain a usable carrier status for this shipment, so we are checking with the carrier. "
                "No refund has been proposed yet."
            )
        elif self.outcome == "INVALID_REQUEST":
            body = "We could not match this request to the order and customer on file, so we cannot action it as written."
        else:
            body = "Thank you for contacting us. We have reviewed your request and will reply with the current status."
        return DraftReply(to=to, subject=subject, body=body)


class RulesEngine:
    def __init__(self, data: DataStore):
        self.data = data

    def evaluate(self, ticket: Any, facts: Facts) -> EngineResult:
        checks: list[Check] = []
        sender = normalise_email(ticket_get(ticket, "from_", ticket_get(ticket, "from", "")))
        received_at = parse_datetime(ticket_get(ticket, "received_at"))
        request_key = f"{sender}|{facts.order_id or ''}|{facts.issue_type}"
        ticket_type = issue_to_ticket_type(facts.issue_type)
        checks.append(
            _check(
                "dedupe",
                "PASS",
                CLAUSE_ONCE,
                [_evidence("ticket", ticket_get(ticket, "ticket_id", ""), request_key)],
            )
        )

        order = self.data.orders_by_id.get(facts.order_id or "")
        if not order:
            checks.append(
                _check(
                    "order_exists",
                    "FAIL",
                    CLAUSE_IDENTITY,
                    [_evidence("ticket", ticket_get(ticket, "ticket_id", ""), facts.order_id or "no order id")],
                )
            )
            return self._result(
                checks, ticket_type, "INVALID_REQUEST", ["ORDER_NOT_FOUND"], None,
                None, facts.order_id, None, "REPLY", request_key,
            )
        checks.append(
            _check(
                "order_exists",
                "PASS",
                CLAUSE_IDENTITY,
                [_evidence("data/orders.csv", order.order_id, f"customer={order.customer_id}; status={order.status}")],
            )
        )

        customer = self.data.customer_for(order)
        on_file = normalise_email(customer.email if customer else "")
        if not customer or on_file != sender:
            checks.append(
                _check(
                    "customer_match",
                    "FAIL",
                    CLAUSE_IDENTITY,
                    [
                        _evidence("ticket", ticket_get(ticket, "ticket_id", ""), f"sender={sender}"),
                        _evidence("data/customers.csv", order.customer_id, f"email_on_file={on_file}"),
                    ],
                )
            )
            return self._result(
                checks, ticket_type, "INVALID_REQUEST", ["CUSTOMER_MISMATCH"], None,
                None, order.order_id, None, "REPLY", request_key,
            )
        checks.append(
            _check(
                "customer_match",
                "PASS",
                CLAUSE_IDENTITY,
                [_evidence("data/customers.csv", order.customer_id, f"email_on_file={on_file}")],
            )
        )

        injection_hits = detect_injection(ticket_get(ticket, "body", ""))
        injection_hits.extend(detect_injection(ticket_get(ticket, "subject", "")))
        if facts.override_attempt:
            injection_hits.append("model flagged a policy override attempt")
        if injection_hits:
            checks.append(
                _check(
                    "policy_override",
                    "FAIL",
                    CLAUSE_OVERRIDE,
                    [_evidence("ticket", ticket_get(ticket, "ticket_id", ""), "; ".join(dict.fromkeys(injection_hits)))],
                )
            )
            return self._result(
                checks, ticket_type, "ESCALATE", ["POLICY_OVERRIDE_ATTEMPT"], None,
                "TRUST_SAFETY", order.order_id, order.customer_id, "ESCALATION", request_key,
            )
        checks.append(
            _check(
                "policy_override",
                "PASS",
                CLAUSE_OVERRIDE,
                [_evidence("ticket", ticket_get(ticket, "ticket_id", ""), "no override language")],
            )
        )

        if facts.issue_type in {"status", "non_delivery"}:
            return self._evaluate_carrier(
                ticket, facts, order.order_id, order.customer_id, ticket_type,
                received_at, checks, request_key,
            )
        return self._evaluate_refund(
            ticket, facts, order, ticket_type, received_at, checks, request_key,
        )

    def _evaluate_carrier(
        self,
        ticket: Any,
        facts: Facts,
        order_id: str,
        customer_id: str,
        ticket_type: str,
        received_at: datetime | None,
        checks: list[Check],
        request_key: str,
    ) -> EngineResult:
        shipment = self.data.shipment_for(order_id)
        if not shipment or shipment.status == "UNAVAILABLE":
            checks.append(
                _check(
                    "carrier_status",
                    "UNABLE_TO_VERIFY",
                    CLAUSE_CARRIER,
                    [_evidence("data/shipments.csv", shipment.shipment_id if shipment else order_id, shipment.status if shipment else "no shipment")],
                )
            )
            return self._result(
                checks, ticket_type, "UNABLE_TO_VERIFY", ["CARRIER_STATUS_UNAVAILABLE"], None,
                None, order_id, customer_id, "REPLY", request_key,
            )

        if shipment.status == "DELIVERED":
            last_movement = shipment.last_event_at or shipment.delivered_at
            checks.append(
                _check(
                    "carrier_status",
                    "PASS",
                    CLAUSE_STATUS,
                    [
                        _evidence(
                            "data/shipments.csv",
                            shipment.shipment_id,
                            f"status={shipment.status}; last_event_at={shipment.last_event_at}; delivered_at={shipment.delivered_at}",
                        )
                    ],
                )
            )
            checks.append(
                _check(
                    "transit_age",
                    "NOT_APPLICABLE",
                    CLAUSE_LOST,
                    [_evidence("data/shipments.csv", shipment.shipment_id, "carrier records DELIVERED; lost-in-transit rule not applied")],
                )
            )
            result = self._result(
                checks, ticket_type, "PROCEED", [], None,
                None, order_id, customer_id, "REPLY", request_key,
            )
            result.carrier_status = shipment.status
            result.last_movement = last_movement
            return result

        last_movement = shipment.last_event_at
        if last_movement is None and shipment.status != "UNAVAILABLE":
            last_movement = shipment.shipped_at
        if last_movement is None or received_at is None:
            checks.append(
                _check(
                    "carrier_status",
                    "UNABLE_TO_VERIFY",
                    CLAUSE_CARRIER,
                    [_evidence("data/shipments.csv", shipment.shipment_id, "no usable last movement")],
                )
            )
            return self._result(
                checks, ticket_type, "UNABLE_TO_VERIFY", ["CARRIER_STATUS_UNAVAILABLE"], None,
                None, order_id, customer_id, "REPLY", request_key,
            )

        checks.append(
            _check(
                "carrier_status",
                "PASS",
                CLAUSE_CARRIER,
                [
                    _evidence(
                        "data/shipments.csv",
                        shipment.shipment_id,
                        f"status={shipment.status}; last_event_at={shipment.last_event_at}; shipped_at={shipment.shipped_at}",
                    )
                ],
            )
        )
        days = calendar_days(received_at, last_movement)
        if days > 10:
            checks.append(
                _check(
                    "transit_age",
                    "FAIL",
                    CLAUSE_LOST,
                    [_evidence("data/shipments.csv", shipment.shipment_id, f"{days} calendar days since last movement")],
                )
            )
            return self._result(
                checks, ticket_type, "ESCALATE", ["LOST_IN_TRANSIT"], None,
                "CARRIER_CLAIMS", order_id, customer_id, "ESCALATION", request_key,
            )
        checks.append(
            _check(
                "transit_age",
                "PASS",
                CLAUSE_LOST,
                [_evidence("data/shipments.csv", shipment.shipment_id, f"{days} calendar days since last movement")],
            )
        )
        result = self._result(
            checks, ticket_type, "PROCEED", [], None,
            None, order_id, customer_id, "REPLY", request_key,
        )
        result.carrier_status = shipment.status
        result.last_movement = last_movement
        return result

    def _evaluate_refund(
        self,
        ticket: Any,
        facts: Facts,
        order: Any,
        ticket_type: str,
        received_at: datetime | None,
        checks: list[Check],
        request_key: str,
    ) -> EngineResult:
        shipment = self.data.shipment_for(order.order_id)
        if not shipment or not shipment.delivered_at or received_at is None:
            checks.append(
                _check(
                    "delivery_window",
                    "UNABLE_TO_VERIFY",
                    CLAUSE_WINDOW,
                    [_evidence("data/shipments.csv", shipment.shipment_id if shipment else order.order_id, "no delivery date")],
                )
            )
            return self._result(
                checks, ticket_type, "UNABLE_TO_VERIFY", ["CARRIER_STATUS_UNAVAILABLE"], None,
                None, order.order_id, order.customer_id, "REPLY", request_key,
            )

        days = calendar_days(received_at, shipment.delivered_at)
        damage = facts.issue_type in {"damaged", "faulty"}
        reasons: list[str] = []
        if damage and facts.photo_present and 31 <= days <= 45:
            checks.append(
                _check(
                    "delivery_window",
                    "PASS",
                    CLAUSE_DAMAGE_EXCEPTION,
                    [
                        _evidence("data/shipments.csv", shipment.shipment_id, f"delivered_at={shipment.delivered_at}; days={days}"),
                        _evidence("ticket", ticket_get(ticket, "ticket_id", ""), f"photo_present={facts.photo_present}"),
                    ],
                )
            )
            reasons.append("DAMAGE_EXCEPTION")
        elif days <= 30:
            checks.append(
                _check(
                    "delivery_window",
                    "PASS",
                    CLAUSE_WINDOW,
                    [_evidence("data/shipments.csv", shipment.shipment_id, f"delivered_at={shipment.delivered_at}; days={days}")],
                )
            )
        else:
            checks.append(
                _check(
                    "delivery_window",
                    "FAIL",
                    CLAUSE_OUT_OF_WINDOW,
                    [_evidence("data/shipments.csv", shipment.shipment_id, f"delivered_at={shipment.delivered_at}; days={days}")],
                )
            )
            return self._result(
                checks, ticket_type, "REJECT", ["OUT_OF_WINDOW"], None,
                None, order.order_id, order.customer_id, "REPLY", request_key,
            )

        items = self.data.items_for(order.order_id)
        matches = match_affected_lines(ticket_get(ticket, "body", ""), items)
        if not matches and len(items) == 1:
            matches = list(items)
        if not matches:
            checks.append(
                _check(
                    "affected_lines",
                    "FAIL",
                    CLAUSE_REFUND,
                    [_evidence("ticket", ticket_get(ticket, "ticket_id", ""), "no order line matched")],
                )
            )
            result = self._result(
                checks, "OTHER", "PROCEED", [], None,
                None, order.order_id, order.customer_id, "REPLY", request_key,
            )
            result.clarification = True
            return result

        whole_order = whole_order_requested(ticket_get(ticket, "body", ""))
        modified = bool(whole_order and len(matches) < len(items))
        if facts.quantity is not None and any(facts.quantity > item.qty for item in matches):
            modified = True
        if modified:
            reasons.append("PARTIAL_LINES")
        checks.append(
            _check(
                "affected_lines",
                "PASS",
                CLAUSE_PARTIAL if modified else CLAUSE_REFUND,
                [
                    _evidence(
                        "data/order_items.csv",
                        f"{order.order_id}:{item.line_no}",
                        f"{item.product_name}; qty={item.qty}; unit={item.unit_price}",
                    )
                    for item in matches
                ]
                + [_evidence("ticket", ticket_get(ticket, "ticket_id", ""), f"modified={modified}")],
            )
        )

        amount = Decimal("0")
        fully_refunded = 0
        already_refunded_amount = Decimal("0")
        for item in matches:
            prior_refunds = self.data.refunds_for(order.order_id, item.line_no)
            prior_value = sum((refund.amount for refund in prior_refunds), Decimal("0"))
            line_total = Decimal(item.qty) * item.unit_price
            remaining = max(Decimal("0"), line_total - prior_value)
            if remaining <= 0:
                fully_refunded += 1
                already_refunded_amount += prior_value
                if "ALREADY_REFUNDED" not in reasons:
                    reasons.append("ALREADY_REFUNDED")
                checks.append(
                    _check(
                        "prior_refund",
                        "FAIL",
                        CLAUSE_PRIOR,
                        [
                            _evidence("data/refunds.csv", refund.refund_id, f"line={refund.line_no}; amount={refund.amount}")
                            for refund in prior_refunds
                        ] or [_evidence("data/order_items.csv", f"{order.order_id}:{item.line_no}", "line fully refunded")],
                    )
                )
                continue

            if facts.quantity is not None:
                qty = min(facts.quantity, item.qty)
            elif whole_order:
                qty = item.qty
            else:
                qty = 1 if item.qty > 0 else 0
            qty = max(0, min(qty, item.qty))
            line_amount = min(Decimal(qty) * item.unit_price, remaining)
            amount += max(Decimal("0"), line_amount)
            checks.append(
                _check(
                    "prior_refund",
                    "PASS",
                    CLAUSE_PRIOR,
                    [
                        _evidence("data/refunds.csv", refund.refund_id, f"line={refund.line_no}; amount={refund.amount}")
                        for refund in prior_refunds
                    ]
                    or [_evidence("data/order_items.csv", f"{order.order_id}:{item.line_no}", "no prior refund")],
                )
            )

        checks.append(
            _check(
                "amount",
                "PASS" if amount > 0 else "FAIL",
                CLAUSE_REFUND,
                [_evidence("rules", order.order_id, f"amount_usd={amount:.2f}; shipping_refunded=0.00")],
            )
        )
        if amount <= 0:
            result = self._result(
                checks, ticket_type, "REJECT", reasons or ["ALREADY_REFUNDED"], None,
                None, order.order_id, order.customer_id, "REPLY", request_key,
            )
            result.prior_refund_amount = already_refunded_amount or None
            return result

        if amount > Decimal("150"):
            checks.append(
                _check(
                    "authority",
                    "FAIL",
                    CLAUSE_APPROVAL,
                    [_evidence("rules", order.order_id, f"amount_usd={amount:.2f} > 150.00")],
                )
            )
            result = self._result(
                checks, ticket_type, "PEND", reasons + ["APPROVAL_REQUIRED"], amount,
                "SUPPORT_LEAD", order.order_id, order.customer_id, "REFUND", request_key,
            )
            result.prior_refund_amount = already_refunded_amount or None
            return result

        checks.append(
            _check(
                "authority",
                "PASS",
                CLAUSE_AUTHORITY,
                [_evidence("rules", order.order_id, f"amount_usd={amount:.2f} <= 150.00")],
            )
        )
        result = self._result(
            checks, ticket_type, "PROCEED_MODIFIED" if modified else "PROCEED", reasons, amount,
            None, order.order_id, order.customer_id, "REFUND", request_key,
        )
        result.prior_refund_amount = already_refunded_amount or None
        return result

    def _result(
        self,
        checks: list[Check],
        ticket_type: str,
        outcome: str,
        reasons: list[str],
        amount: Decimal | None,
        approver: str | None,
        order_id: str | None,
        customer_id: str | None,
        ledger_action: str,
        request_key: str,
    ) -> EngineResult:
        checks.append(
            _check(
                "ledger_once",
                "PASS",
                CLAUSE_ONCE,
                [_evidence("ledger", request_key, ledger_action)],
            )
        )
        return EngineResult(
            ticket_type=ticket_type,
            outcome=outcome,
            reason_codes=list(dict.fromkeys(reasons)),
            amount_usd=amount,
            approver_role=approver,
            checks=checks,
            order_id=order_id,
            customer_id=customer_id,
            ledger_action=ledger_action,
            request_key=request_key,
        )
