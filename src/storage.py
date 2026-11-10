"""SQLite persistence for runs and the refund/reply/escalation ledger."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from schema.response_schema import Decision, TicketResponse


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    ticket_id TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decision TEXT,
    approver TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    ticket_id TEXT NOT NULL,
    action TEXT NOT NULL,
    amount_usd REAL,
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    configured = os.getenv("RUN_DB_PATH")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "larkfield" / "runs.db"


class RunStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self._lock:
            self.connection.executescript(SCHEMA)
            self._ensure_columns()
            self.connection.commit()

    def _ensure_columns(self) -> None:
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        for name in ("decision", "approver", "decided_at"):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT")

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def get_response_by_key(self, request_key: str) -> TicketResponse | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT response_json FROM runs WHERE request_key = ?", (request_key,)
            ).fetchone()
        if not row:
            return None
        return TicketResponse.model_validate_json(row["response_json"])

    def save_run(
        self,
        request_key: str,
        response: TicketResponse,
        action: str | None,
        amount: Decimal | None,
    ) -> TicketResponse | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                self.connection.execute(
                    "INSERT INTO runs (run_id, request_key, ticket_id, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        response.run_id,
                        request_key,
                        response.ticket_id,
                        response.model_dump_json(),
                        now,
                    ),
                )
                if action:
                    self.connection.execute(
                        "INSERT INTO ledger (run_id, ticket_id, action, amount_usd, status, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            response.run_id,
                            response.ticket_id,
                            action,
                            float(amount) if amount is not None else None,
                            "PROPOSED",
                            now,
                        ),
                    )
                self.connection.commit()
                return None
            except sqlite3.IntegrityError:
                self.connection.rollback()
                existing = self.get_response_by_key(request_key)
                if existing is not None:
                    return existing
                row = self.connection.execute(
                    "SELECT response_json FROM runs WHERE run_id = ?", (response.run_id,)
                ).fetchone()
                if row is not None:
                    return TicketResponse.model_validate_json(row["response_json"])
                return None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        data = json.loads(row["response_json"])
        data["decision"] = row["decision"]
        data["approver"] = row["approver"]
        data["decided_at"] = row["decided_at"]
        return data

    def record_decision(self, run_id: str, decision: Decision) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None
            response = TicketResponse.model_validate_json(row["response_json"])
            ledger_row = self.connection.execute(
                "SELECT status FROM ledger WHERE run_id = ?", (run_id,)
            ).fetchone()
            if (
                row["decision"] is not None
                or not response.human_approval_required
                or (ledger_row is not None and ledger_row["status"] != "PROPOSED")
            ):
                return self.get_run(run_id)

            decided_at = datetime.now(timezone.utc).isoformat()
            status = "APPROVED" if decision.decision == "approve" else "REJECTED"
            updated = response.model_copy(update={"human_approval_required": False})
            self.connection.execute(
                "UPDATE runs SET response_json = ?, decision = ?, approver = ?, decided_at = ? WHERE run_id = ?",
                (updated.model_dump_json(), decision.decision, decision.approver, decided_at, run_id),
            )
            self.connection.execute(
                "UPDATE ledger SET status = ? WHERE run_id = ?", (status, run_id)
            )
            self.connection.commit()
            return self.get_run(run_id)

    def ledger_for(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT run_id, ticket_id, action, amount_usd, status, recorded_at "
                "FROM ledger WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_ledger(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT run_id, ticket_id, action, amount_usd, status, recorded_at "
                "FROM ledger ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]
