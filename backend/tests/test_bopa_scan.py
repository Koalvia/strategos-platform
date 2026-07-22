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

from datetime import datetime

import pytest

from app import celery_app
from app.domains.bopa import router as bopa_router
from app.domains.bopa import tasks as bopa_tasks
from app.domains.bopa.schemas import SyncResult
from app.domains.bopa.service import BopaService

SCAN_URL = "/api/v1/bopa/scan"


@pytest.fixture
def _recorded_pipeline(monkeypatch):
    """Replace the pipeline steps with recorders and capture call order.

    Covers both the global analyzer and the customer-scoped one, so a test can
    assert which path a given request took.
    """
    calls: list[str] = []

    def fake_sync(self):
        calls.append("sync")
        return SyncResult(bulletins_synced=1, documents_synced=3, documents_failed=0)

    def fake_analyze():
        calls.append("analyze")
        return 2

    def fake_analyze_customer(customer_id):
        calls.append(f"analyze_customer:{customer_id}")
        return 5

    def fake_generate():
        calls.append("alerts")

    monkeypatch.setattr(BopaService, "sync_latest", fake_sync)
    monkeypatch.setattr(bopa_router, "analyze_bopa_matches", fake_analyze)
    monkeypatch.setattr(
        bopa_router, "analyze_bopa_matches_for_customer", fake_analyze_customer
    )
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


@pytest.mark.integration
def test_scan_scoped_to_customer_runs_only_customer_analyzer(client, _recorded_pipeline):
    """With ``?customer_id`` the endpoint runs sync -> customer analyze only.

    The global analyzer and the obligation-alerts job must not run: match alerts
    are raised inline by the scoped analyzer, and obligation alerts are a separate
    global job.
    """
    resp = client.post(SCAN_URL, params={"customer_id": "cust-001"})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "bulletins_synced": 1,
        "documents_synced": 3,
        "documents_failed": 0,
        "matches_created": 5,
    }
    assert _recorded_pipeline == ["sync", "analyze_customer:cust-001"]


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
        app.dependency_overrides.pop(get_db, None)


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


@pytest.mark.unit
def test_worker_ready_skips_when_lock_not_claimed(monkeypatch):
    """A worker that loses the startup lock does not queue a second chain."""
    built = []

    class FakeChain:
        def __init__(self, *signatures):
            built.append(self)

        def apply_async(self):
            raise AssertionError("chain should not be queued when the lock is lost")

    monkeypatch.setattr(celery_app, "chain", FakeChain)
    monkeypatch.setattr(celery_app, "_claim_startup_run", lambda: False)

    celery_app.run_bopa_pipeline_on_startup()

    assert built == []


class _SingleCustomerBCClient:
    """Minimal BC client: one customer (with a NIF) and its projects.

    Enough for ``CustomersService.get_customer`` and the scoped analyzer, which
    only call ``get_customers()`` / ``get_projects()``.
    """

    def __init__(self, customer, projects):
        self._customer = customer
        self._projects = projects

    def get_customers(self):
        return [self._customer]

    def get_projects(self):
        return self._projects


@pytest.mark.integration
def test_scoped_analyzer_matches_only_target_customer(
    db_session, monkeypatch, bopa_bulletin_factory
):
    """The scoped analyzer persists name/NIF/project matches for the target
    customer only, raises one alert per match, writes **no** ``BopaAnalysisLog``,
    and is idempotent on re-run."""
    from app.domains.alerts.models import Alert
    from app.domains.bopa.models import BopaAnalysisLog, BopaDocument, BopaMatch
    from app.integrations.business_central.models import (
        BCCustomer,
        BCProject,
        CustomerStatus,
        ProjectStatus,
    )

    target = BCCustomer(
        id="cust-001",
        name="ACME Corp",
        nif="A123456",
        customer_type="Company",
        responsible="",
        active_project_count=1,
        status=CustomerStatus.active,
    )
    project = BCProject(
        id="proj-1",
        name="Bridge Renewal",
        customer_id="cust-001",
        responsible="",
        technician="",
        status=ProjectStatus.active,
    )
    bc_client = _SingleCustomerBCClient(target, [project])
    monkeypatch.setattr(bopa_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(bopa_tasks, "get_business_central_client", lambda: bc_client)

    bulletin_id = bopa_bulletin_factory().id

    def _doc(title, body, name):
        return BopaDocument(
            bulletin_id=bulletin_id,
            title=title,
            html_content=body,
            document_name=name,
            file_type="html",
            organisme="Org",
            organisme_pare="Gov",
            tema="Tema",
            tema_pare="TemaPare",
            article_date=datetime(2026, 1, 1),
            source_url=f"https://example.com/{name}",
            pdf_url=f"https://example.com/{name}.pdf",
        )

    db_session.add_all(
        [
            _doc("Award to ACME Corp", "ACME Corp wins the tender", "byname.html"),
            _doc("Tax notice", "Ref NIF A123456 pending", "bynif.html"),
            _doc("Works update", "Bridge Renewal progresses", "byproject.html"),
            _doc("Unrelated notice", "Nothing relevant here", "none.html"),
            _doc("Award to Other SL", "Other SL wins", "other.html"),
        ]
    )
    db_session.commit()

    created = bopa_tasks.analyze_bopa_matches_for_customer("cust-001")
    assert created == 3

    matches = db_session.query(BopaMatch).filter_by(customer_id="cust-001").all()
    assert {m.matched_term for m in matches} == {"ACME Corp", "A123456", "Bridge Renewal"}
    project_match = next(m for m in matches if m.matched_term == "Bridge Renewal")
    assert project_match.project_id == "proj-1"

    # Nothing leaked to any other customer.
    assert (
        db_session.query(BopaMatch).filter(BopaMatch.customer_id != "cust-001").count()
        == 0
    )

    # One alert per match, and — the whole point — no per-bulletin analysis log,
    # so the global path can still analyze this bulletin for other customers.
    assert db_session.query(Alert).count() == 3
    assert db_session.query(BopaAnalysisLog).count() == 0

    # Idempotent: a second scoped scan adds nothing new.
    assert bopa_tasks.analyze_bopa_matches_for_customer("cust-001") == 0
    assert db_session.query(BopaMatch).filter_by(customer_id="cust-001").count() == 3


@pytest.mark.integration
def test_scoped_analyzer_unknown_customer_raises_404(db_session, monkeypatch):
    """An unknown customer id surfaces as a 404 (via CustomersService)."""
    from fastapi import HTTPException

    from app.integrations.business_central.models import BCCustomer, CustomerStatus

    other = BCCustomer(
        id="cust-002",
        name="Other SL",
        nif="B999999",
        customer_type="Company",
        responsible="",
        active_project_count=0,
        status=CustomerStatus.active,
    )
    monkeypatch.setattr(bopa_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        bopa_tasks,
        "get_business_central_client",
        lambda: _SingleCustomerBCClient(other, []),
    )

    with pytest.raises(HTTPException) as exc:
        bopa_tasks.analyze_bopa_matches_for_customer("cust-001")
    assert exc.value.status_code == 404
