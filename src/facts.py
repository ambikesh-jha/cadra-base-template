"""Deterministic email-fact extraction.

This is the no-LLM baseline for the narrow extraction contract. A later LLM
extractor must return the same four facts; the rules engine stays authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .normalise import (
    detect_injection,
    extract_order_id,
    extract_quantity,
    has_photo,
    infer_issue_type,
)


@dataclass(frozen=True)
class Facts:
    order_id: str | None
    issue_type: str
    quantity: int | None
    photo_present: bool
    override_attempt: bool = False


def ticket_get(ticket: Any, key: str, default: Any = None) -> Any:
    if isinstance(ticket, dict):
        return ticket.get(key, default)
    return getattr(ticket, key, default)


def extract_facts(ticket: Any) -> Facts:
    body = ticket_get(ticket, "body", "") or ""
    subject = ticket_get(ticket, "subject", "") or ""
    attachments = ticket_get(ticket, "attachments", []) or []
    return Facts(
        order_id=extract_order_id(body) or extract_order_id(subject),
        issue_type=infer_issue_type(subject, body),
        quantity=extract_quantity(body),
        photo_present=has_photo(attachments),
        override_attempt=bool(detect_injection(body) or detect_injection(subject)),
    )
