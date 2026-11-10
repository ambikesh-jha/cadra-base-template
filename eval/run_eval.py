#!/usr/bin/env python3
"""Run the Larkfield evaluation cases and write a timestamped JSON result file."""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_store import DataStore  # noqa: E402
from src.service import process_ticket  # noqa: E402
from src.storage import RunStore  # noqa: E402


def parse_amount(response: Any, ledger_action: str | None) -> float | None:
    if ledger_action != "REFUND":
        return None
    for check in response.checks:
        if check.check_id != "amount":
            continue
        for evidence in check.evidence:
            match = re.search(r"amount_usd=([0-9.]+)", evidence.value)
            if match:
                return round(float(match.group(1)), 2)
    return None


def ledger_action(response: Any) -> str | None:
    for check in response.checks:
        if check.check_id == "ledger_once" and check.evidence:
            return check.evidence[-1].value
    return None


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def evaluate_case(case: dict[str, Any], data: DataStore, work_dir: Path) -> dict[str, Any]:
    expected = case["expected"]
    store = RunStore(work_dir / f"{case['id']}.db")
    started = time.perf_counter()
    try:
        response = process_ticket(case["ticket"], data=data, store=store)
    finally:
        store.close()
    latency_ms = (time.perf_counter() - started) * 1000.0
    action = ledger_action(response)
    amount = parse_amount(response, action)
    actual = {
        "ticket_type": response.ticket_type,
        "outcome": response.outcome,
        "reason_codes": sorted(response.reason_codes),
        "approver_role": response.approver_role,
        "human_approval_required": response.human_approval_required,
        "amount_usd": amount,
        "ledger_action": action,
        "draft_reply": response.draft_reply.body,
    }
    failures: list[str] = []
    for field in (
        "ticket_type",
        "outcome",
        "approver_role",
        "human_approval_required",
        "amount_usd",
        "ledger_action",
    ):
        if actual[field] != expected[field]:
            failures.append(f"{field}: actual={actual[field]!r} expected={expected[field]!r}")
    if set(actual["reason_codes"]) != set(expected["reason_codes"]):
        failures.append(
            f"reason_codes: actual={actual['reason_codes']!r} expected={sorted(expected['reason_codes'])!r}"
        )
    for term in expected.get("reply_terms", []):
        if term.lower() not in actual["draft_reply"].lower():
            failures.append(f"reply missing term {term!r}")
    return {
        "id": case["id"],
        "name": case["name"],
        "pass": not failures,
        "failures": failures,
        "expected": expected,
        "actual": actual,
        "latency_ms": round(latency_ms, 3),
        "cost_usd": round(float(response.trace.cost_usd), 8),
        "model_calls": [call.model_dump() for call in response.trace.model_calls],
        "tools_called": response.trace.tools_called,
        "documents_used": [doc.model_dump() for doc in response.trace.documents_used],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "eval/cases.json"))
    parser.add_argument("--label", default="run")
    parser.add_argument("--results-dir", default=str(ROOT / "eval/results"))
    parser.add_argument("--llm", action="store_true", help="Enable the optional LLM layer")
    args = parser.parse_args()

    if not args.llm:
        for key in list(os.environ):
            if key.startswith("LLM_"):
                del os.environ[key]

    payload = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = payload["cases"]
    pass_rule = payload["pass_rule"]
    data = DataStore.load(ROOT / "data")

    with tempfile.TemporaryDirectory() as temp_dir:
        results = [evaluate_case(case, data, Path(temp_dir)) for case in cases]

    latencies = [item["latency_ms"] for item in results]
    costs = [item["cost_usd"] for item in results]
    passed = sum(1 for item in results if item["pass"])
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "llm_enabled": args.llm,
        "total_cost_usd": round(sum(costs), 8),
        "median_cost_usd": round(statistics.median(costs), 8) if costs else 0.0,
        "mean_cost_usd": round(statistics.mean(costs), 8) if costs else 0.0,
        "mean_latency_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "median_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(percentile(latencies, 0.95), 3),
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", args.label).strip("-") or "run"
    output_dir = Path(args.results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{timestamp}-{label}.json"
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "pass_rule": pass_rule,
        "summary": summary,
        "cases": results,
    }
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        f"{passed}/{len(results)} passed; "
        f"median latency {summary['median_latency_ms']} ms; "
        f"median cost ${summary['median_cost_usd']:.8f}; "
        f"llm={args.llm}"
    )
    for item in results:
        if not item["pass"]:
            print(f"FAIL {item['id']}: {'; '.join(item['failures'])}")
    print(f"results: {output_path}")


if __name__ == "__main__":
    main()
