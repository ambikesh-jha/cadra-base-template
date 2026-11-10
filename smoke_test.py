#!/usr/bin/env python3
"""Smoke-test every API endpoint against a running base URL."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("BASE_URL", "http://localhost:8000")).rstrip("/")

TICKET = {
    "ticket_id": "SMOKE-001",
    "received_at": "2026-09-28T10:00:00+00:00",
    "channel": "email",
    "from": "carla.ivanova2@mail.example",
    "to": "support@larkfield.example",
    "subject": "Damaged Oak dining chair",
    "body": "My Oak dining chair from order LF-100202 arrived damaged. Photo attached, please refund.",
    "attachments": [
        {"file_name": "damage.jpg", "content_type": "image/jpeg", "content_base64": ""}
    ],
}


def request(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        return error.code, {"detail": error.read().decode("utf-8", errors="replace")}


def check(label: str, condition: bool, detail: object = None) -> None:
    if not condition:
        raise AssertionError(f"{label} failed: {detail}")
    print(f"PASS {label}")


def main() -> int:
    status, health = request("GET", "/health")
    check("GET /health", status == 200 and health.get("status") == "ok", health)

    status, created = request("POST", "/tickets", TICKET)
    check("POST /tickets", status == 200 and bool(created.get("run_id")), created)
    run_id = created["run_id"]

    status, run = request("GET", f"/runs/{run_id}")
    check("GET /runs/{run_id}", status == 200 and run.get("run_id") == run_id, run)

    status, run_ledger = request("GET", f"/runs/{run_id}/ledger")
    check("GET /runs/{run_id}/ledger", status == 200 and isinstance(run_ledger, list), run_ledger)

    status, decided = request(
        "POST", f"/runs/{run_id}/decision", {"decision": "approve", "approver": "Support Lead"}
    )
    check(
        "POST /runs/{run_id}/decision",
        status == 200
        and decided.get("run_id") == run_id
        and "decision" in decided
        and "approver" in decided
        and "decided_at" in decided,
        decided,
    )

    status, all_ledger = request("GET", "/ledger")
    check("GET /ledger", status == 200 and isinstance(all_ledger, list), all_ledger)
    print(f"Smoke test passed against {BASE_URL}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"FAIL {error}")
        raise SystemExit(1)
