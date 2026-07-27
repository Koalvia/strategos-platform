"""Tests for the daily BOPA sync Celery task (issue #50).

Celery runs eagerly/synchronously under ``TESTING=1`` (see ``app.celery_app``),
so the task body executes in-process. The task builds its own DB session via
``SessionLocal`` and its own client via ``get_bopa_client`` (it runs outside a
request scope, so it cannot use ``Depends``). Here we point both at the test's
in-memory session and the fixture-backed ``MockBopaClient`` and assert the task
runs to completion and persists the synced data.
"""

import pytest

from app.domains.alerts.models import Alert, AlertType
from app.domains.bopa import tasks
from app.domains.bopa.models import BopaBulletin, BopaDocument, BopaMatch
from app.integrations.bopa.mock_client import MockBopaClient
from app.integrations.business_central.mock_client import MockBusinessCentralClient


@pytest.fixture
def _wire_task(db_session, monkeypatch):
    """Point the task's session factory and client at the test's fixtures."""
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(tasks, "get_bopa_client", MockBopaClient)
    return db_session


@pytest.fixture
def _wire_full_pipeline(db_session, monkeypatch):
    """Wire both the sync and analysis tasks at the committed mock fixtures.

    Unlike ``_wire_task`` this also points the analysis task at the real
    ``MockBusinessCentralClient`` (which reads ``customers.json``/``projects.json``),
    so the end-to-end BOPA match can be exercised against genuine fixture data.
    """
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(tasks, "get_bopa_client", MockBopaClient)
    monkeypatch.setattr(
        tasks, "get_business_central_client", MockBusinessCentralClient
    )
    return db_session


@pytest.mark.integration
def test_task_is_registered():
    """The task is discoverable under its ``bopa.sync_daily`` names."""
    assert "bopa.sync_daily" in tasks.celery.tasks
    assert "bopa.analyze_matches" in tasks.celery.tasks


@pytest.mark.integration
def test_sync_bopa_daily_runs_and_persists(_wire_task):
    """Calling the task completes without raising and populates the DB."""
    tasks.sync_bopa_daily()

    assert _wire_task.query(BopaBulletin).count() == 1
    assert _wire_task.query(BopaDocument).count() == 3


@pytest.mark.integration
def test_sync_bopa_daily_delay_runs_eagerly(_wire_task):
    """``.delay()`` executes synchronously under TESTING and succeeds."""
    tasks.sync_bopa_daily.delay()

    assert _wire_task.query(BopaBulletin).count() == 1


@pytest.mark.integration
def test_sync_then_analyze_matches_frankenstein_customer(_wire_full_pipeline):
    """End-to-end: the real OEC, SLU edict is synced, read, and matched.

    Syncing pulls the genuine bulletin-82 edict body (which names the society
    "OEC, SLU") into ``html_content``; analysis then crosses it against the
    committed customers and finds the "OEC, SLU" customer (cust-015), producing
    exactly one BOPA match and one alert. This proves the document-ingestion and
    name-crossing logic works on real BOPA text.
    """
    db = _wire_full_pipeline

    tasks.sync_bopa_daily()
    # The real edict body reached the stored OEC document, not the canned stub.
    oec_doc = (
        db.query(BopaDocument)
        .filter_by(document_name="GF_2026_07_16_11_16_54")
        .one()
    )
    assert "OEC, SLU" in (oec_doc.html_content or "")

    tasks.analyze_bopa_matches()

    match = db.query(BopaMatch).filter_by(customer_id="cust-015").one()
    assert match.matched_term == "OEC, SLU"
    assert match.project_id is None
    # No other customer/project name appears in the edict, so it is the only match.
    assert db.query(BopaMatch).count() == 1

    alert = db.query(Alert).filter_by(bopa_match_id=match.id).one()
    assert alert.alert_type is AlertType.BOPA
    assert alert.customer_id == "cust-015"

