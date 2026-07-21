"""Pydantic schemas for the dev-only tooling domain."""

from pydantic import BaseModel


class MockPipelineResult(BaseModel):
    """Summary of one mock BOPA pipeline run.

    Counts are read from the database after the run, so they reflect the whole
    local dataset (a fresh DB yields exactly the synthetic demo numbers; a DB with
    previously synced/analyzed data reports its cumulative totals).
    """

    bulletins_synced: int
    documents_synced: int
    bopa_matches: int
    bopa_alerts: int
    obligation_alerts: int
