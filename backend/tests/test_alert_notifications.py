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
from app.integrations.business_central.mock_client import MockBusinessCentralClient

MANAGER = "marc@estrategos.ad"
ASSIGNED = "jordi@estrategos.ad"  # cust-001, cust-002
OTHER = "laura@estrategos.ad"  # cust-003
STRANGER = "nobody@example.com"  # no BC resource


@pytest.fixture
def sent(monkeypatch):
    """Capture every send_email call instead of hitting Resend."""
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
