"""Tests for worsening-transition alerts (``alerts.evaluate_traffic_transitions``).

Covers the pure severity helper (:func:`is_traffic_worsening`) and the daily task:
first-sight silence, each worsening staging exactly one ``TRAFFIC_CHANGE`` alert,
same/improved silence, the global ``email_on_change_enabled`` toggle, idempotent
re-runs, and the per-user opt-out at dispatch.

Like ``test_alerts_obligations``, the task runs eagerly under ``TESTING=1`` and
builds its own session/client, so ``SessionLocal`` is pointed at the test session
and ``get_business_central_client`` at a stub returning controlled instances.
``reference_date`` is passed explicitly so status derivation never reads the clock.
"""

from datetime import date

import pytest

from app.core.config import settings
from app.domains.alerts import notifications, tasks
from app.domains.alerts.models import (
    Alert,
    AlertCategory,
    AlertStatus,
    AlertType,
    ObligationTrafficState,
    UserAlertPreference,
)
from app.domains.alerts.notifications import dispatch_pending_alert_emails
from app.domains.alerts.utils import is_traffic_worsening
from app.domains.auth.models import User
from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.settings.service import SettingsService
from app.integrations.business_central.mock_client import MockBusinessCentralClient
from app.integrations.business_central.models import BCProjectObligation

# Fixed reference date; with the default thresholds (red 5 / yellow 15 days) the
# due dates below land each instance in a specific traffic-light colour.
REF = date(2026, 7, 20)
GREEN_DUE = date(2026, 8, 30)   # ref + 41 -> Al día
YELLOW_DUE = date(2026, 7, 30)  # ref + 10 -> Próximo
URGENT_DUE = date(2026, 7, 23)  # ref + 3  -> Urgente
OVERDUE_DUE = date(2026, 7, 19)  # ref - 1  -> Vencido

# proj-001 belongs to cust-001, whose alerts reach the manager and jordi@.
CUST1_PROJECT = "proj-001"
MANAGER = "marc@estrategos.ad"
ASSIGNED = "jordi@estrategos.ad"  # cust-001, cust-002


def _inst(instance_id: str, due_date, project_id: str = "proj-x") -> BCProjectObligation:
    return BCProjectObligation(
        id=instance_id,
        project_id=project_id,
        obligation_id="obl-ccaa",
        subject=True,
        due_date=due_date,
        submission_date=None,
    )


class _StubClient(MockBusinessCentralClient):
    """Mock BC client with a caller-controlled project-obligation list."""

    def __init__(self, instances=None):
        self.instances = instances if instances is not None else []

    def get_project_obligations(self):
        return self.instances


# --- Pure logic -------------------------------------------------------------


S = DerivedObligationStatus


@pytest.mark.unit
@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (S.on_track, S.upcoming, True),   # green -> yellow
        (S.on_track, S.overdue, True),    # green -> red (overdue)
        (S.upcoming, S.urgent, True),     # Próximo -> Urgente
        (S.urgent, S.overdue, True),      # Urgente -> Vencido
        (S.on_track, S.on_track, False),  # steady
        (S.urgent, S.upcoming, False),    # improved
        (S.overdue, S.on_track, False),   # improved (filed)
        (S.undated, S.overdue, False),    # off-scale in
        (S.overdue, S.undated, False),    # off-scale out
    ],
)
def test_is_traffic_worsening_matrix(previous, current, expected):
    assert is_traffic_worsening(previous, current) is expected


# --- Task integration -------------------------------------------------------


@pytest.fixture
def wired(db_session, monkeypatch):
    """Point the task's session factory and BC client at test doubles."""
    stub = _StubClient()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(tasks, "get_business_central_client", lambda: stub)
    return db_session, stub


def _run(stub, instances):
    stub.instances = instances
    tasks.evaluate_traffic_transitions(reference_date=REF)


@pytest.mark.integration
def test_task_is_registered():
    assert "alerts.evaluate_traffic_transitions" in tasks.celery.tasks


@pytest.mark.integration
def test_first_sight_stores_status_and_stages_nothing(wired):
    db, stub = wired
    _run(stub, [_inst("po-1", GREEN_DUE)])

    assert db.query(Alert).count() == 0
    state = (
        db.query(ObligationTrafficState)
        .filter(ObligationTrafficState.bc_obligation_id == "po-1")
        .one()
    )
    assert state.last_status == DerivedObligationStatus.on_track.value


@pytest.mark.integration
@pytest.mark.parametrize(
    ("first_due", "second_due"),
    [
        (GREEN_DUE, YELLOW_DUE),   # green -> yellow
        (GREEN_DUE, OVERDUE_DUE),  # green -> red
        (YELLOW_DUE, URGENT_DUE),  # Próximo -> Urgente
        (URGENT_DUE, OVERDUE_DUE),  # Urgente -> Vencido
    ],
)
def test_each_worsening_stages_one_alert(wired, first_due, second_due):
    db, stub = wired
    _run(stub, [_inst("po-1", first_due)])  # first sight, silent
    _run(stub, [_inst("po-1", second_due)])  # worsened

    alerts = db.query(Alert).all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type is AlertType.OBLIGATION
    assert alert.category is AlertCategory.TRAFFIC_CHANGE
    assert alert.status is AlertStatus.NEW
    # NULL bc_obligation_id so uq_alert_bc_obligation never blocks re-alerting.
    assert alert.bc_obligation_id is None
    assert alert.title and alert.message


@pytest.mark.integration
def test_same_or_improved_updates_state_silently(wired):
    db, stub = wired
    _run(stub, [_inst("po-1", URGENT_DUE)])  # first sight: Urgente
    _run(stub, [_inst("po-1", GREEN_DUE)])   # improved to Al día

    assert db.query(Alert).count() == 0
    state = (
        db.query(ObligationTrafficState)
        .filter(ObligationTrafficState.bc_obligation_id == "po-1")
        .one()
    )
    assert state.last_status == DerivedObligationStatus.on_track.value


@pytest.mark.integration
def test_global_toggle_off_stages_nothing_but_tracks_state(wired):
    db, stub = wired
    SettingsService(db).get_traffic_light().email_on_change_enabled = False
    db.commit()

    _run(stub, [_inst("po-1", GREEN_DUE)])
    _run(stub, [_inst("po-1", OVERDUE_DUE)])  # a worsening, but emails are off

    assert db.query(Alert).count() == 0
    state = (
        db.query(ObligationTrafficState)
        .filter(ObligationTrafficState.bc_obligation_id == "po-1")
        .one()
    )
    assert state.last_status == DerivedObligationStatus.overdue.value


@pytest.mark.integration
def test_rerun_same_day_is_idempotent(wired):
    db, stub = wired
    _run(stub, [_inst("po-1", GREEN_DUE)])
    _run(stub, [_inst("po-1", OVERDUE_DUE)])  # stages one
    _run(stub, [_inst("po-1", OVERDUE_DUE)])  # nothing new: already advanced

    assert db.query(Alert).count() == 1


@pytest.mark.integration
def test_multiple_worsenings_over_life_are_not_blocked(wired):
    """Two colour changes for the same obligation stage two alerts (no uq clash)."""
    db, stub = wired
    _run(stub, [_inst("po-1", GREEN_DUE)])
    _run(stub, [_inst("po-1", YELLOW_DUE)])   # green -> yellow
    _run(stub, [_inst("po-1", OVERDUE_DUE)])  # yellow -> red

    alerts = db.query(Alert).all()
    assert len(alerts) == 2
    assert all(a.bc_obligation_id is None for a in alerts)


@pytest.mark.integration
def test_per_user_opt_out_excludes_user_at_dispatch(wired, monkeypatch):
    """A TRAFFIC_CHANGE opt-out drops that user; others still get the email."""
    db, stub = wired

    # Verified accounts for the two cust-001 recipients.
    users = {}
    for email in (MANAGER, ASSIGNED):
        u = User(
            name=email.split("@")[0],
            email=email,
            hashed_password="x",
            is_verified=True,
        )
        db.add(u)
        users[email] = u
    db.commit()
    for u in users.values():
        db.refresh(u)

    # jordi@ opts out of colour-change emails.
    db.add(
        UserAlertPreference(
            user_id=users[ASSIGNED].id,
            category=AlertCategory.TRAFFIC_CHANGE,
            email_enabled=False,
        )
    )
    db.commit()

    # Stage a worsening for a cust-001 obligation.
    _run(stub, [_inst("po-1", GREEN_DUE, project_id=CUST1_PROJECT)])
    _run(stub, [_inst("po-1", OVERDUE_DUE, project_id=CUST1_PROJECT)])
    assert db.query(Alert).count() == 1

    # Capture sends and dispatch (test mode reveals the real recipient in subject).
    monkeypatch.setattr(
        settings, "ALERT_EMAIL_TEST_RECIPIENT", "test-inbox@koalvia.test"
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        notifications.EmailService,
        "send_email",
        lambda to_email, subject, html_content, from_email=None: calls.append(
            {"to": to_email, "subject": subject}
        ),
    )

    dispatch_pending_alert_emails(db, MockBusinessCentralClient())

    real_recipients = {
        c["subject"].split("destinatario real: ")[1].split("]")[0] for c in calls
    }
    assert MANAGER in real_recipients
    assert ASSIGNED not in real_recipients
