"""End-to-end test for the dev mock BOPA -> Alerts pipeline.

Exercises :func:`app.domains.dev.service.run_mock_bopa_pipeline`, which drives the
three real pipeline stages (sync -> analyze -> obligation alerts) against committed
fixtures only. Like the individual task tests, the task bodies build their own
``SessionLocal`` and BC client, so we point both at the test's in-memory session
and the fixture-backed mock BC client. ``reference_date`` is pinned so the
obligation assertions do not depend on the wall clock.

The synthetic BOPA fixture (``pipeline_demo_documents.json``) has eight documents:
six whose titles embed a real BC customer/project name and two controls that
match nothing, so the analysis stage yields exactly six matches over five clients:

* doc 1 -> customer ``cust-007`` (Immobiliària Pirineus SL)
* doc 2 -> project ``proj-010`` (Fiscalitat immobiliària), customer ``cust-007``
* doc 3 -> customer ``cust-006`` (Restaurant La Muntanya SL)
* doc 4 -> customer ``cust-001`` (Fontaneria Puigcerdà SL)
* doc 5 -> customer ``cust-005`` (Fundació Cultural Andorrana)
* doc 6 -> project ``proj-006`` (Gestió comunitat de propietaris), customer ``cust-004``
"""

from datetime import date

import pytest

from app.domains.alerts import tasks as alerts_tasks
from app.domains.alerts.models import Alert, AlertStatus, AlertType
from app.domains.alerts.service import AlertsService
from app.domains.bopa import tasks as bopa_tasks
from app.domains.bopa.models import BopaDocument, BopaMatch
from app.domains.bopa.service import BopaService
from app.domains.dev.service import (
    DEMO_BULLETINS,
    DEMO_DOCUMENTS,
    run_mock_bopa_pipeline,
)
from app.integrations.bopa.mock_client import MockBopaClient
from app.integrations.business_central.mock_client import MockBusinessCentralClient

# Consistent with the fixture's fecha_notificacion values (see
# test_alerts_obligations): pobl-002/004/006 qualify on this date.
REFERENCE_DATE = date(2026, 7, 20)
EXPECTED_OBLIGATION_IDS = {"pobl-002", "pobl-004", "pobl-006"}


@pytest.fixture
def _wire_pipeline(db_session, monkeypatch):
    """Point both task bodies' session factory and BC client at the test fixtures."""
    monkeypatch.setattr(bopa_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(alerts_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        bopa_tasks, "get_business_central_client", MockBusinessCentralClient
    )
    monkeypatch.setattr(
        alerts_tasks, "get_business_central_client", MockBusinessCentralClient
    )
    return db_session


@pytest.mark.integration
def test_pipeline_persists_documents(_wire_pipeline):
    """Stage 1 persists the synthetic bulletin's documents."""
    result = run_mock_bopa_pipeline(_wire_pipeline, reference_date=REFERENCE_DATE)

    assert result.bulletins_synced == 1
    assert result.documents_synced == 8
    assert _wire_pipeline.query(BopaDocument).count() == 8


@pytest.mark.integration
def test_pipeline_search_finds_synthetic_document(_wire_pipeline):
    """The persisted synthetic content is searchable through the real search path."""
    run_mock_bopa_pipeline(_wire_pipeline, reference_date=REFERENCE_DATE)

    demo_client = MockBopaClient(
        bulletins_fixture=DEMO_BULLETINS, documents_fixture=DEMO_DOCUMENTS
    )
    page = BopaService(_wire_pipeline, demo_client).search_documents(q="Pirineus")

    assert page.total == 1
    assert "Immobiliària Pirineus SL" in page.items[0].title


@pytest.mark.integration
def test_pipeline_creates_bopa_matches_and_alerts(_wire_pipeline):
    """Stage 2 yields exactly six matches (four customer, two project) + alerts."""
    result = run_mock_bopa_pipeline(_wire_pipeline, reference_date=REFERENCE_DATE)

    assert result.bopa_matches == 6
    assert result.bopa_alerts == 6

    matches = _wire_pipeline.query(BopaMatch).all()
    matched_terms = {m.matched_term for m in matches}
    assert matched_terms == {
        "Immobiliària Pirineus SL",
        "Fiscalitat immobiliària",
        "Restaurant La Muntanya SL",
        "Fontaneria Puigcerdà SL",
        "Fundació Cultural Andorrana",
        "Gestió comunitat de propietaris",
    }
    # Matches span five distinct clients.
    assert {m.customer_id for m in matches} == {
        "cust-001",
        "cust-004",
        "cust-005",
        "cust-006",
        "cust-007",
    }
    # The project-level matches carry both customer_id and project_id.
    by_term = {m.matched_term: m for m in matches}
    assert by_term["Fiscalitat immobiliària"].customer_id == "cust-007"
    assert by_term["Fiscalitat immobiliària"].project_id == "proj-010"
    assert by_term["Gestió comunitat de propietaris"].customer_id == "cust-004"
    assert by_term["Gestió comunitat de propietaris"].project_id == "proj-006"

    # BOPA alert payload resolves display fields from the linked match/document.
    page = AlertsService(_wire_pipeline).list_alerts()
    bopa_alerts = [a for a in page.items if a.alert_type is AlertType.BOPA]
    assert len(bopa_alerts) == 6
    for alert in bopa_alerts:
        assert alert.status is AlertStatus.NEW  # pure pipeline leaves all NEW
        assert alert.matched_term  # display term populated
        assert alert.document_title  # linked document title populated


@pytest.mark.integration
def test_pipeline_creates_obligation_alerts(_wire_pipeline):
    """Stage 3 turns due BC obligations into Obligation alerts with a payload."""
    result = run_mock_bopa_pipeline(_wire_pipeline, reference_date=REFERENCE_DATE)

    assert result.obligation_alerts == len(EXPECTED_OBLIGATION_IDS)

    obligation_alerts = (
        _wire_pipeline.query(Alert)
        .filter(Alert.alert_type == AlertType.OBLIGATION)
        .all()
    )
    assert {a.bc_obligation_id for a in obligation_alerts} == EXPECTED_OBLIGATION_IDS
    for alert in obligation_alerts:
        assert alert.title and alert.message  # denormalized display populated


@pytest.mark.integration
def test_pipeline_is_idempotent(_wire_pipeline):
    """Re-running the pipeline does not duplicate matches or alerts."""
    run_mock_bopa_pipeline(_wire_pipeline, reference_date=REFERENCE_DATE)
    second = run_mock_bopa_pipeline(_wire_pipeline, reference_date=REFERENCE_DATE)

    assert second.bopa_matches == 6
    assert second.bopa_alerts == 6
    assert second.obligation_alerts == len(EXPECTED_OBLIGATION_IDS)
    # No new bulletin/documents synced on the second pass.
    assert second.bulletins_synced == 0
    assert second.documents_synced == 0


@pytest.mark.integration
def test_pipeline_demo_states_populate_all_tabs(_wire_pipeline):
    """demo_states=True moves a fixed subset to VIEWED/DISCARDED, idempotently."""
    run_mock_bopa_pipeline(
        _wire_pipeline, reference_date=REFERENCE_DATE, demo_states=True
    )

    def counts_by_status():
        rows = _wire_pipeline.query(Alert).all()
        return {
            status: sum(1 for a in rows if a.status is status)
            for status in AlertStatus
        }

    first = counts_by_status()
    # 9 alerts total (6 BOPA + 3 obligation): 2 viewed, 1 discarded, 6 new.
    assert first[AlertStatus.VIEWED] == 2
    assert first[AlertStatus.DISCARDED] == 1
    assert first[AlertStatus.NEW] == 6

    # The targeted alerts are the expected ones (by stable key).
    fontaneria = (
        _wire_pipeline.query(Alert)
        .filter(Alert.alert_type == AlertType.BOPA, Alert.customer_id == "cust-001")
        .one()
    )
    assert fontaneria.status is AlertStatus.VIEWED
    discarded = (
        _wire_pipeline.query(Alert)
        .filter(Alert.bc_obligation_id == "pobl-006")
        .one()
    )
    assert discarded.status is AlertStatus.DISCARDED

    # Re-running with demo_states keeps the same distribution (idempotent).
    run_mock_bopa_pipeline(
        _wire_pipeline, reference_date=REFERENCE_DATE, demo_states=True
    )
    assert counts_by_status() == first
