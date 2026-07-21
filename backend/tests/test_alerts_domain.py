"""Tests for the Alerts domain (endpoints + service).

Alerts are platform-native, so these seed rows directly via the ``db_session``
fixture and hit the API through the authenticated ``client``. State is global
(shared by all users), which keeps the assertions simple: an alert has one
``status`` and no per-user read tracking.
"""

from datetime import datetime

import pytest

from app.domains.alerts.models import Alert, AlertStatus, AlertType
from app.domains.alerts.service import AlertsService
from app.domains.bopa.models import BopaBulletin, BopaDocument, BopaMatch


@pytest.fixture
def bopa_match(db_session):
    """A BopaMatch (with its bulletin + document) to link alerts against."""
    bulletin = BopaBulletin(
        year=2026,
        num=1,
        is_extra=False,
        published_at=datetime(2026, 1, 1),
        total_document_count=1,
        sumari_pdf_url="https://example.com/sumari.pdf",
    )
    db_session.add(bulletin)
    db_session.flush()

    document = BopaDocument(
        bulletin_id=bulletin.id,
        document_name="doc-1",
        file_type="html",
        organisme="Org",
        organisme_pare="OrgPare",
        tema="Tema",
        tema_pare="TemaPare",
        title="Acme SL mencionada en el BOPA",
        article_date=datetime(2026, 1, 1),
        source_url="https://example.com/doc-1",
        pdf_url="https://example.com/doc-1.pdf",
    )
    db_session.add(document)
    db_session.flush()

    match = BopaMatch(
        customer_id="C001",
        document_id=document.id,
        matched_term="Acme SL",
    )
    db_session.add(match)
    db_session.flush()
    return match


def _make_alert(db_session, match, status=AlertStatus.NEW):
    alert = Alert(
        customer_id=match.customer_id,
        bopa_match_id=match.id,
        alert_type=AlertType.BOPA,
        status=status,
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert


def test_list_alerts_returns_display_fields(client, db_session, bopa_match):
    _make_alert(db_session, bopa_match)

    response = client.get("/api/v1/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["customer_id"] == "C001"
    assert item["alert_type"] == "BOPA"
    assert item["status"] == "new"
    assert item["matched_term"] == "Acme SL"
    assert item["document_title"] == "Acme SL mencionada en el BOPA"
    assert item["source_url"] == "https://example.com/doc-1"
    # Unified display fields mirror the BOPA-specific ones.
    assert item["title"] == "Acme SL"
    assert item["message"] == "Acme SL mencionada en el BOPA"


def test_list_alerts_filters_by_status(client, db_session, bopa_match):
    _make_alert(db_session, bopa_match, status=AlertStatus.VIEWED)

    assert client.get("/api/v1/alerts?status=new").json()["total"] == 0
    viewed = client.get("/api/v1/alerts?status=viewed").json()
    assert viewed["total"] == 1


def test_unread_count(client, db_session, bopa_match):
    _make_alert(db_session, bopa_match, status=AlertStatus.NEW)

    response = client.get("/api/v1/alerts/unread-count")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_update_status_transitions(client, db_session, bopa_match):
    alert = _make_alert(db_session, bopa_match)

    seen = client.patch(f"/api/v1/alerts/{alert.id}", json={"status": "viewed"})
    assert seen.status_code == 200
    assert seen.json()["status"] == "viewed"

    discarded = client.patch(
        f"/api/v1/alerts/{alert.id}", json={"status": "discarded"}
    )
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"


def test_update_status_unknown_alert_404(client):
    response = client.patch("/api/v1/alerts/9999", json={"status": "viewed"})
    assert response.status_code == 404


def test_mark_all_read(client, db_session, bopa_match):
    _make_alert(db_session, bopa_match, status=AlertStatus.NEW)

    response = client.post("/api/v1/alerts/mark-all-read")
    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert client.get("/api/v1/alerts/unread-count").json()["count"] == 0


def test_create_for_match_is_idempotent(db_session, bopa_match):
    service = AlertsService(db_session)

    first = service.create_for_match(bopa_match)
    db_session.commit()
    second = service.create_for_match(bopa_match)
    db_session.commit()

    assert first.id == second.id
    assert db_session.query(Alert).filter(
        Alert.bopa_match_id == bopa_match.id
    ).count() == 1
