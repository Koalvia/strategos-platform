"""Tests for BC obligation alerts (Phase 2 of the Alerts domain).

Covers the pure trigger rule (:func:`should_generate_obligation_alert`) and the
daily Celery task (:func:`generate_obligation_alerts`): creation, in-memory-set
idempotency, and state reconciliation (auto-dismissal of filed obligations).

The task runs eagerly under ``TESTING=1`` and builds its own session/client, so —
like ``test_bopa_tasks`` — we point ``SessionLocal`` at the test session and
``get_business_central_client`` at the fixture-backed mock. ``reference_date`` is
passed explicitly so the assertions do not depend on the wall clock.
"""

from datetime import date

import pytest

from app.domains.alerts import tasks
from app.domains.alerts.models import Alert, AlertStatus, AlertType
from app.domains.alerts.utils import should_generate_obligation_alert
from app.integrations.business_central.mock_client import MockBusinessCentralClient
from app.integrations.business_central.models import BCProjectObligation

# A fixed "today" consistent with the fecha_notificacion values seeded in the
# project_obligations fixture (past/near dates fire, 2026-10-15 stays in future).
REFERENCE_DATE = date(2026, 7, 20)

# Fixture instances that qualify on REFERENCE_DATE (subject, unfiled, due).
EXPECTED_DUE_IDS = {"pobl-002", "pobl-004", "pobl-006"}


# --- Pure logic -------------------------------------------------------------


def _obligation(**overrides) -> BCProjectObligation:
    base = dict(
        id="po-x",
        project_id="proj-1",
        obligation_id="obl-1",
        subject=True,
        submission_date=None,
        fecha_notificacion=date(2026, 7, 1),
    )
    base.update(overrides)
    return BCProjectObligation(**base)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),  # subject, unfiled, notification in the past
        ({"fecha_notificacion": REFERENCE_DATE}, True),  # exactly today fires
        ({"fecha_notificacion": date(2026, 8, 1)}, False),  # future: not yet
        ({"fecha_notificacion": None}, False),  # no notification date
        ({"subject": False}, False),  # not liable
        ({"subject": None}, False),  # unknown liability
        ({"submission_date": date(2026, 7, 2)}, False),  # already filed
    ],
)
def test_should_generate_matrix(overrides, expected):
    assert (
        should_generate_obligation_alert(_obligation(**overrides), REFERENCE_DATE)
        is expected
    )


@pytest.mark.unit
def test_should_generate_requires_explicit_reference_date():
    """The pure function takes no default reference date (never reads the clock)."""
    with pytest.raises(TypeError):
        should_generate_obligation_alert(_obligation())  # type: ignore[call-arg]


# --- Task integration -------------------------------------------------------


@pytest.fixture
def _wire_task(db_session, monkeypatch):
    """Point the task's session factory and BC client at the test fixtures."""
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        tasks, "get_business_central_client", MockBusinessCentralClient
    )
    return db_session


@pytest.mark.integration
def test_task_is_registered():
    assert "alerts.generate_obligation_alerts" in tasks.celery.tasks


@pytest.mark.integration
def test_creates_alerts_for_due_obligations(_wire_task):
    tasks.generate_obligation_alerts(reference_date=REFERENCE_DATE)

    alerts = _wire_task.query(Alert).all()
    assert {a.bc_obligation_id for a in alerts} == EXPECTED_DUE_IDS
    for alert in alerts:
        assert alert.alert_type is AlertType.OBLIGATION
        assert alert.status is AlertStatus.NEW
        assert alert.title and alert.message  # denormalized display populated


@pytest.mark.integration
def test_task_is_idempotent(_wire_task):
    tasks.generate_obligation_alerts(reference_date=REFERENCE_DATE)
    tasks.generate_obligation_alerts(reference_date=REFERENCE_DATE)

    assert _wire_task.query(Alert).count() == len(EXPECTED_DUE_IDS)


@pytest.mark.integration
def test_auto_dismisses_filed_obligation(_wire_task):
    """An active alert whose obligation is now filed is moved to DISCARDED."""
    # pobl-001 carries a submission_date in the fixture (filed in the ERP).
    stale = Alert(
        customer_id="cust-x",
        alert_type=AlertType.OBLIGATION,
        bc_obligation_id="pobl-001",
        title="Old",
        message="Old",
        status=AlertStatus.NEW,
    )
    _wire_task.add(stale)
    _wire_task.commit()

    tasks.generate_obligation_alerts(reference_date=REFERENCE_DATE)

    # Re-query rather than refresh: the task closes its session, detaching `stale`.
    rows = (
        _wire_task.query(Alert)
        .filter(Alert.bc_obligation_id == "pobl-001")
        .all()
    )
    # No fresh alert is created for the filed obligation; the existing one is dismissed.
    assert len(rows) == 1
    assert rows[0].status is AlertStatus.DISCARDED
