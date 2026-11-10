"""Normalisation and deterministic email-fact helpers."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "order", "item", "items",
    "set", "pair", "my", "our", "please", "thanks", "hello", "dear", "support",
    "arrived", "damaged", "broken", "cracked", "refund", "return", "received",
    "wrong", "faulty", "about", "would", "like", "have", "has", "had", "was", "were",
    "one", "two", "three", "whole", "just", "now", "still", "nothing", "tracking",
}

INJECTION_PATTERNS = [
    r"ignore\s+(your|all|any|the|previous|prior)\s+instructions?",
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+|my\s+|previous\s+|prior\s+)*instructions?",
    r"ignore\s+(the\s+)?policy",
    r"disregard\s+(?:the\s+|all\s+|any\s+|these\s+|those\s+)?(?:rules?|instructions?|polic(?:y|ies))(?:\s+above)?",
    r"note\s+to\s+the\s+(ai|assistant)",
    r"\[\s*system\s*\]",
    r"pre[-\s]?approved",
    r"authori[sz]ed\s+to\s+process",
    r"without\s+(any\s+)?review",
    r"mark\s+human_approval_required",
    r"bypass\s+(the\s+)?policy",
    r"override\s+(the\s+)?policy",
    r"chargeback|legal\s+action|lawsuit|\bsue\b",
]


def normalise_email(value: str | None) -> str:
    return (value or "").strip().lower()


def normalise_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def extract_order_id(value: str | None) -> str | None:
    text = value or ""
    patterns = [
        r"\bLF[-\s]?(\d{6})\b",
        r"#\s*(\d{6})\b",
        r"\border\s+order\s+(\d{6})\b",
        r"\border\s+(?:id|number|no\.?)?\s*[:#-]?\s*(\d{6})\b",
        r"\b(?:reference|ref|ticket|purchase)\s*(?:id|number|no\.?)?\s*[:#-]?\s*(\d{6})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"LF-{match.group(1)}"
    return None


def normalise_order_id(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    found = extract_order_id(text)
    if found:
        return found
    match = re.fullmatch(r"(?:LF[-\s]?)?(\d{6})", text, re.IGNORECASE)
    if match:
        return f"LF-{match.group(1)}"
    return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_date(value: str | None) -> date | None:
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_money(value: str | None) -> Decimal:
    text = (value or "").strip().replace(",", "")
    text = re.sub(r"(?i)usd", "", text).replace("$", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def calendar_days(later: datetime, earlier: datetime) -> int:
    return (later.date() - earlier.date()).days


def _attachment_value(attachment: Any, key: str) -> str:
    if isinstance(attachment, dict):
        return str(attachment.get(key, ""))
    return str(getattr(attachment, key, ""))


def has_photo(attachments: Iterable[Any] | None) -> bool:
    for attachment in attachments or []:
        content_type = _attachment_value(attachment, "content_type").lower()
        file_name = _attachment_value(attachment, "file_name").lower()
        if content_type.startswith("image/"):
            return True
        if file_name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic")):
            return True
    return False


def detect_injection(body: str | None) -> list[str]:
    text = normalise_text(body)
    hits: list[str] = []
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(pattern)
    return hits


def infer_issue_type(subject: str | None, body: str | None) -> str:
    text = normalise_text(f"{subject or ''} {body or ''}")

    if re.search(r"\bwrong\s+item\b|received\s+something\s+else|not\s+what\s+i\s+ordered", text):
        return "wrong"
    if re.search(r"\bnot\s+as\s+described\b", text):
        return "not_as_described"
    if re.search(r"\bfaulty\b|\bmalfunction", text):
        return "faulty"
    if re.search(r"\bdamaged\b|\bcrack(ed|ing)\b|\bcame\s+broken\b|\bbroken\b", text):
        return "damaged"

    if re.search(r"where\s+is\s+my\s+order|where\s+order\b", text):
        return "status"
    if re.search(
        r"never\s+arrived|has\s+not\s+arrived|hasn't\s+arrived|stuck\s+for|"
        r"tracking\s+hasn'?t\s+(moved|changed)|tracking\s+has\s+not\s+(moved|changed)|"
        r"gone\s+missing|is\s+it\s+lost|still\s+nothing|hasn'?t\s+changed",
        text,
    ):
        return "non_delivery"

    if re.search(r"\breturn(ing)?\b", text):
        return "change_of_mind"
    if re.search(r"where\s+is\s+my\s+order|hasn'?t\s+arrived\s+yet", text):
        return "status"
    return "other"


def extract_quantity(body: str | None) -> int | None:
    text = normalise_text(body)
    if re.search(r"\bone\s+of\s+(?:my\s+|the\s+)?(?:two|2)\b", text):
        return 1
    if re.search(r"\bone\s+of\s+(?:my\s+|the\s+)?(?:three|3)\b", text):
        return 1
    if re.search(r"\b(?:just|only)\s+one\b", text):
        return 1
    return None


def whole_order_requested(body: str | None) -> bool:
    text = normalise_text(body)
    return bool(re.search(r"\bwhole\s+order\b|\bfor\s+the\s+entire\s+order\b", text))


def match_affected_lines(body: str | None, items: Iterable[Any]) -> list[Any]:
    text = normalise_text(body)
    if not text:
        return []
    matches: list[Any] = []
    for item in items:
        product = normalise_text(item.product_name)
        if product and product in text:
            matches.append(item)
            continue
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", product)
            if len(token) > 2 and token not in STOP_WORDS and not token.isdigit()
        ]
        if tokens and any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens):
            matches.append(item)
    return matches


def issue_to_ticket_type(issue_type: str) -> str:
    if issue_type == "status":
        return "ORDER_STATUS"
    if issue_type == "non_delivery":
        return "DELIVERY_ISSUE"
    if issue_type == "change_of_mind":
        return "RETURN"
    if issue_type in {"damaged", "faulty", "wrong", "not_as_described"}:
        return "REFUND"
    return "OTHER"
