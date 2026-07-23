"""Tests for the on-demand BOPA scan endpoint and the worker-startup trigger.

``POST /bopa/scan`` runs the full pipeline synchronously (sync -> analyze ->
obligation alerts) so the "Iniciar Escaneo" button gets the refreshed state back
in one round-trip. The Celery ``worker_ready`` handler queues the same three
steps as a chain every time a worker starts.

The pipeline steps themselves are covered by ``test_customer_bopa_matches`` and
``test_run_bopa_pipeline``; here we replace them with recorders so these tests
stay fast and assert only the wiring: HTTP shape, execution order, and the chain
that gets queued on startup.
"""

import pytest

from app import celery_app
from app.domains.bopa import router as bopa_router
from app.domains.bopa.schemas import SyncResult
from app.domains.bopa.service import BopaService

SCAN_URL = "/api/v1/bopa/scan"


@pytest.fixture
def _recorded_pipeline(monkeypatch):
    """Replace the three pipeline steps with recorders and capture call order."""
    calls: list[str] = []

    def fake_sync(self):
        calls.append("sync")
        return SyncResult(bulletins_synced=1, documents_synced=3, documents_failed=0)

    def fake_analyze():
        calls.append("analyze")
        return 2

    def fake_generate():
        calls.append("alerts")

    monkeypatch.setattr(BopaService, "sync_latest", fake_sync)
    monkeypatch.setattr(bopa_router, "analyze_bopa_matches", fake_analyze)
    monkeypatch.setattr(bopa_router, "generate_obligation_alerts", fake_generate)
    return calls


@pytest.mark.integration
def test_scan_runs_pipeline_and_returns_result(client, _recorded_pipeline):
    """The endpoint runs sync -> analyze -> alerts and reports the counts."""
    resp = client.post(SCAN_URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "bulletins_synced": 1,
        "documents_synced": 3,
        "documents_failed": 0,
        "matches_created": 2,
    }
    assert _recorded_pipeline == ["sync", "analyze", "alerts"]


@pytest.mark.auth
def test_scan_requires_authentication(db_session):
    """Without a verified user the scan endpoint refuses the request."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.post(SCAN_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.unit
def test_worker_ready_queues_full_pipeline_chain(monkeypatch):
    """On worker start, a chain of the three immutable signatures is queued."""
    built = []

    class FakeChain:
        def __init__(self, *signatures):
            self.signatures = signatures
            self.applied = 0
            built.append(self)

        def apply_async(self):
            self.applied += 1

    monkeypatch.setattr(celery_app, "chain", FakeChain)

    celery_app.run_bopa_pipeline_on_startup()

    assert len(built) == 1
    assert built[0].applied == 1
    names = [sig.task for sig in built[0].signatures]
    assert names == [
        "bopa.sync_daily",
        "bopa.analyze_matches",
        "alerts.generate_obligation_alerts",
    ]
    # Immutable signatures so no result is passed from one step to the next.
    assert all(sig.immutable for sig in built[0].signatures)
