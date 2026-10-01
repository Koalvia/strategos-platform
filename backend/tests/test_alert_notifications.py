"""Tests for alert email delivery (``app.domains.alerts.notifications``).

Routing reuses the visibility scope against the mock fixtures: RES-01 (marc@) is
the manager, RES-02 (jordi@) is assigned cust-001/cust-002, RES-03 (laura@) has
cust-003. ``EmailService.send_email`` is patched so no test ever hits Resend.
"""

import pytest

from app.core.config import settings
from app.domains.alerts import notifications
from app.domains.alerts.models import (
    Alert,
    AlertCategory,
    AlertStatus,
    AlertType,
    UserAlertPreference,
)
from app.domains.alerts.notifications import dispatch_pending_alert_emails
from app.domains.auth.models import User
from app.domains.settings.service import SettingsService
from app.integrations.business_central.mock_client import MockBusinessCentralClient
from app.integrations.business_central.models import (
    BCProject,
    BCProjectObligation,
    BCResource,
    BCUser,
)

MANAGER = "marc@strategos.ad"
ASSIGNED = "jordi@strategos.ad"  # cust-001, cust-002
OTHER = "laura@strategos.ad"  # cust-003
STRANGER = "nobody@example.com"  # no BC resource


@pytest.fixture
def sent(monkeypatch):
    """Capture every send_email call instead of hitting Resend.

    Also sets a test recipient: the source default is blank, and in test mode a
    blank recipient makes the dispatcher refuse to send.
    """
    monkeypatch.setattr(settings, "ALERT_EMAIL_TEST_RECIPIENT", "test-inbox@koalvia.test")
    calls: list[dict] = []

    def _fake_send(to_email, subject, html_content, from_email=None):
        calls.append(
            {"to": to_email, "subject": subject, "html": html_content}
        )
        return {"id": "test"}

    monkeypatch.setattr(notifications.EmailService, "send_email", _fake_send)
    return calls


@pytest.fixture
def users(db_session):
    """Create verified accounts for the four fixture emails."""
    made = {}
    for email in (MANAGER, ASSIGNED, OTHER, STRANGER):
        u = User(
            name=email.split("@")[0],
            email=email,
            hashed_password="x",
            is_verified=True,
        )
        db_session.add(u)
        made[email] = u
    db_session.commit()
    for u in made.values():
        db_session.refresh(u)
    return made


def _bopa_alert(db_session, customer_id: str) -> Alert:
    alert = Alert(
        customer_id=customer_id,
        alert_type=AlertType.BOPA,
        status=AlertStatus.NEW,
        title="Match",
        message="msg",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert


def _obligation_alert(db_session, customer_id: str, code: str) -> Alert:
    alert = Alert(
        customer_id=customer_id,
        alert_type=AlertType.OBLIGATION,
        obligation_code=code,
        status=AlertStatus.NEW,
        title="Obl",
        message="msg",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert


def _real_recipients(calls):
    """The real recipients, read from the test-mode subject line."""
    out = set()
    for c in calls:
        assert c["to"] == settings.ALERT_EMAIL_TEST_RECIPIENT  # test mode default
        # subject: "[PRUEBA · destinatario real: <email>] ..."
        out.add(c["subject"].split("destinatario real: ")[1].split("]")[0])
    return out


@pytest.mark.integration
def test_routes_to_manager_and_assigned(db_session, users, sent):
    """A cust-001 alert reaches the manager and the assigned employee only."""
    _bopa_alert(db_session, "cust-001")

    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())

    assert _real_recipients(sent) == {MANAGER, ASSIGNED}


@pytest.mark.integration
def test_stranger_and_unassigned_excluded(db_session, users, sent):
    """laura@ (cust-003) and the account with no BC resource get nothing."""
    _bopa_alert(db_session, "cust-001")

    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())

    recipients = _real_recipients(sent)
    assert OTHER not in recipients and STRANGER not in recipients


@pytest.mark.integration
def test_dedup_never_resends(db_session, users, sent):
    """A second dispatch sends nothing; the alert is marked emailed once."""
    alert = _bopa_alert(db_session, "cust-001")

    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())
    first = len(sent)
    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())

    assert len(sent) == first  # no new sends
    db_session.refresh(alert)
    assert alert.email_sent_at is not None


@pytest.mark.integration
def test_discarded_alert_is_never_emailed(db_session, users, sent):
    alert = _bopa_alert(db_session, "cust-001")
    alert.status = AlertStatus.DISCARDED
    db_session.commit()

    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())

    assert sent == []


@pytest.mark.integration
def test_preference_suppresses_one_category(db_session, users, sent):
    """jordi@ opting out of IVA stops his IVA email but not the manager's."""
    db_session.add(
        UserAlertPreference(
            user_id=users[ASSIGNED].id,
            category=AlertCategory.IVA,
            email_enabled=False,
        )
    )
    db_session.commit()
    _obligation_alert(db_session, "cust-001", "IVA")

    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())

    recipients = _real_recipients(sent)
    assert MANAGER in recipients and ASSIGNED not in recipients


@pytest.mark.integration
def test_live_mode_sends_to_the_real_address(db_session, users, sent, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_EMAIL_TEST_MODE", False)
    _bopa_alert(db_session, "cust-001")

    dispatch_pending_alert_emails(db_session, MockBusinessCentralClient())

    tos = {c["to"] for c in sent}
    assert tos == {MANAGER, ASSIGNED}


@pytest.mark.integration
def test_disabled_globally_sends_nothing(db_session, users, sent, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_EMAIL_ENABLED", False)
    _bopa_alert(db_session, "cust-001")

    assert dispatch_pending_alert_emails(db_session, MockBusinessCentralClient()) == 0
    assert sent == []


@pytest.mark.integration
def test_test_mode_with_blank_recipient_refuses_to_send(
    db_session, users, sent, monkeypatch
):
    """Fail-safe: test mode + no recipient must not fan alerts out anywhere."""
    monkeypatch.setattr(settings, "ALERT_EMAIL_TEST_RECIPIENT", "")
    _bopa_alert(db_session, "cust-001")

    assert dispatch_pending_alert_emails(db_session, MockBusinessCentralClient()) == 0
    assert sent == []


# --------------------------------------------------------------------------- #
# Traffic-light alerts route to the project's technician + responsible, not by
# customer. The important case: the technician is the email-test account.
# --------------------------------------------------------------------------- #

TEST_TECH_EMAIL = "brian.marin+strategosemailtest@koalvia.com"
TEST_MANAGER_EMAIL = "brian.marin+managerstrategosemailtest@koalvia.com"


class _TrafficBC(MockBusinessCentralClient):
    """Mock BC with a project whose technician is the email-test user.

    Only the readers the dispatcher touches are overridden; the manager is a
    separate resource so we can prove they are added only when the toggle is on.
    """

    def get_resources(self):
        return [BCResource(id="RES-M", name="Manager Test", email=TEST_MANAGER_EMAIL,
                           manage_all_customers=True)]

    def get_customer_resources(self):
        return []

    def get_users(self):
        return [
            BCUser(id="u-tech", name="Brian Test", email=TEST_TECH_EMAIL,
                   user_name="BRIANTEST"),
            BCUser(id="u-mgr", name="Manager Test", email=TEST_MANAGER_EMAIL,
                   user_name="MGR"),
        ]

    def get_projects(self):
        return [BCProject(id="p1", name="Proyecto Test", customer_id="c1",
                          responsible="", technician="BRIANTEST", status="Activo")]

    def get_project_obligations(self):
        return [BCProjectObligation(id="ob1", project_id="p1", obligation_id="obl-is")]


def _traffic_alert(db_session) -> Alert:
    alert = Alert(
        customer_id="c1",
        alert_type=AlertType.OBLIGATION,
        bc_project_id="p1",
        category=AlertCategory.TRAFFIC_CHANGE,
        status=AlertStatus.NEW,
        title="Semáforo",
        message="msg",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert


@pytest.fixture
def traffic_users(db_session):
    """Verified app accounts for the technician and the manager."""
    for email in (TEST_TECH_EMAIL, TEST_MANAGER_EMAIL):
        db_session.add(
            User(name=email, email=email, hashed_password="x", is_verified=True)
        )
    db_session.commit()


def _set_notify_manager(db_session, value: bool) -> None:
    row = SettingsService(db_session).get_traffic_light()
    row.notify_manager_on_change = value
    db_session.commit()


@pytest.mark.integration
def test_traffic_change_emails_project_technician(db_session, traffic_users, sent):
    """A traffic-light alert reaches the project's technician (the email-test user)."""
    _traffic_alert(db_session)  # notify_manager defaults to False

    dispatch_pending_alert_emails(db_session, _TrafficBC())

    assert _real_recipients(sent) == {TEST_TECH_EMAIL}


@pytest.mark.integration
def test_traffic_change_includes_manager_only_when_toggled(
    db_session, traffic_users, sent
):
    """With the director toggle on, the manager is added to the technician."""
    _set_notify_manager(db_session, True)
    _traffic_alert(db_session)

    dispatch_pending_alert_emails(db_session, _TrafficBC())

    assert _real_recipients(sent) == {TEST_TECH_EMAIL, TEST_MANAGER_EMAIL}


@pytest.mark.integration
def test_traffic_change_respects_optout(db_session, traffic_users, sent):
    """The technician opting out of TRAFFIC_CHANGE stops their email."""
    tech = db_session.query(User).filter(User.email == TEST_TECH_EMAIL).one()
    db_session.add(
        UserAlertPreference(
            user_id=tech.id,
            category=AlertCategory.TRAFFIC_CHANGE,
            email_enabled=False,
        )
    )
    db_session.commit()
    _traffic_alert(db_session)

    dispatch_pending_alert_emails(db_session, _TrafficBC())

    assert TEST_TECH_EMAIL not in _real_recipients(sent)
