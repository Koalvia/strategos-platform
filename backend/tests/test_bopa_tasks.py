"""Tests for the daily BOPA sync Celery task (issue #50).

Celery runs eagerly/synchronously under ``TESTING=1`` (see ``app.celery_app``),
so the task body executes in-process. The task builds its own DB session via
``SessionLocal`` and its own client via ``get_bopa_client`` (it runs outside a
request scope, so it cannot use ``Depends``). Here we point both at the test's
in-memory session and the fixture-backed ``MockBopaClient`` and assert the task
runs to completion and persists the synced data.
"""

import pytest

from app.domains.bopa import tasks
from app.domains.bopa.models import BopaBulletin, BopaDocument
from app.integrations.bopa.mock_client import MockBopaClient


@pytest.fixture
def _wire_task(db_session, monkeypatch):
    """Point the task's session factory and client at the test's fixtures."""
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(tasks, "get_bopa_client", MockBopaClient)
    return db_session


@pytest.mark.integration
def test_task_is_registered():
    """The task is discoverable under its ``bopa.sync_daily`` name."""
    assert "bopa.sync_daily" in tasks.celery.tasks


@pytest.mark.integration
def test_sync_bopa_daily_runs_and_persists(_wire_task):
    """Calling the task completes without raising and populates the DB."""
    tasks.sync_bopa_daily()

    assert _wire_task.query(BopaBulletin).count() == 2
    assert _wire_task.query(BopaDocument).count() == 4


@pytest.mark.integration
def test_sync_bopa_daily_delay_runs_eagerly(_wire_task):
    """``.delay()`` executes synchronously under TESTING and succeeds."""
    result = tasks.sync_bopa_daily.delay()

    assert result.successful()
    assert _wire_task.query(BopaBulletin).count() == 2
