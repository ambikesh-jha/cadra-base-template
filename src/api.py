"""FastAPI surface for the deterministic core."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from schema.response_schema import Decision, LedgerEntry, RunResponse, Ticket, TicketResponse

from .data_store import DataStore
from .service import process_ticket
from .storage import RunStore


def create_app(
    data: DataStore | None = None,
    store: RunStore | None = None,
) -> FastAPI:
    data = data or DataStore.load()
    store = store or RunStore()
    app = FastAPI(title="Larkfield deterministic support core")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/tickets", response_model=TicketResponse)
    def handle_ticket(ticket: Ticket) -> TicketResponse:
        return process_ticket(ticket, data=data, store=store)

    @app.get("/runs/{run_id}", response_model=RunResponse)
    def get_run(run_id: str) -> dict:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.post("/runs/{run_id}/decision", response_model=RunResponse)
    def record_decision(run_id: str, decision: Decision) -> dict:
        updated = store.record_decision(run_id, decision)
        if updated is None:
            raise HTTPException(status_code=404, detail="run not found")
        return updated

    @app.get("/ledger", response_model=list[LedgerEntry])
    def ledger() -> list[dict]:
        return store.all_ledger()

    @app.get("/runs/{run_id}/ledger")
    def ledger_for_run(run_id: str) -> list[dict]:
        return store.ledger_for(run_id)

    return app


app = create_app()
