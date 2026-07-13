"""Tests for the read-only obligations (Obligaciones) domain (issue #9).

The domain has no database model — obligations are served from the fixture-backed
``MockBusinessCentralClient`` (the default DI mode). These tests cover:

* the catalog endpoint (count + periodicity mapping),
* the per-project instance mapping (obligation / project / client names),
* the **derived status** (``derive_status``) asserted against a frozen reference
  date for each of Vencido / Próximo / Al día (including a filed instance),
* the ``status`` / ``project_id`` / date-range filters and due-date ordering, and
* that the endpoints reject unauthenticated requests.

The instance endpoint derives status against a reference "today". Tests freeze it
by overriding the ``get_reference_date`` dependency so assertions do not depend on
the real clock.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.obligations.router import get_reference_date
from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.obligations.service import ObligationsService, derive_status
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerPage,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCProjectPage,
    CustomerStatus,
    ProjectStatus,
)
from app.main import app

CATALOG_URL = "/api/v1/obligations/catalog"
OBLIGATIONS_URL = "/api/v1/obligations"

# A fixed "today" the fixtures are laid out around: pobl-001 (filed) is well past
# due, pobl-002..005 are overdue, several fall inside the 7-day window, and
# pobl-012 (2026-10-31) is far in the future.
FROZEN_TODAY = date(2026, 7, 1)


@pytest.fixture
def frozen_client(client):
    """The authenticated client with the obligation reference date frozen."""
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    yield client
    app.dependency_overrides.pop(get_reference_date, None)


# --------------------------------------------------------------------------- #
# derive_status (pure unit tests)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_derive_status_overdue_when_past_due_and_unfiled():
    """A past-due, unfiled instance is Vencido."""
    status = derive_status(date(2026, 6, 15), None, FROZEN_TODAY)
    assert status is DerivedObligationStatus.overdue


@pytest.mark.unit
def test_derive_status_upcoming_within_window():
    """An unfiled instance due within 7 days (inclusive) is Próximo."""
    assert derive_status(FROZEN_TODAY, None, FROZEN_TODAY) is DerivedObligationStatus.upcoming
    assert (
        derive_status(date(2026, 7, 8), None, FROZEN_TODAY)
        is DerivedObligationStatus.upcoming
    )


@pytest.mark.unit
def test_derive_status_on_track_when_far_future():
    """An unfiled instance due beyond the window is Al día."""
    assert (
        derive_status(date(2026, 7, 9), None, FROZEN_TODAY)
        is DerivedObligationStatus.on_track
    )


@pytest.mark.unit
def test_derive_status_filed_is_on_track_even_if_past_due():
    """A filed instance is Al día regardless of how far past due it was."""
    status = derive_status(date(2026, 6, 15), date(2026, 6, 10), FROZEN_TODAY)
    assert status is DerivedObligationStatus.on_track


@pytest.mark.unit
def test_derive_status_undated_when_no_due_date():
    """An instance without a due date is Sin fecha, never overdue/upcoming."""
    assert derive_status(None, None, FROZEN_TODAY) is DerivedObligationStatus.undated
    # A due-less instance is undated even if a submission date is somehow present.
    assert (
        derive_status(None, date(2026, 6, 10), FROZEN_TODAY)
        is DerivedObligationStatus.undated
    )


# --------------------------------------------------------------------------- #
# Catalog endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_catalog_returns_ten_obligation_types(client):
    """The catalog returns every mock obligation type (10)."""
    resp = client.get(CATALOG_URL)
    assert resp.status_code == 200
    assert len(resp.json()) == 10


@pytest.mark.integration
def test_catalog_fields_and_periodicity(client):
    """Each catalog entry exposes code, name, periodicity and due-date rule."""
    resp = client.get(CATALOG_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == {"code", "name", "periodicity", "due_date_rule"}
    by_code = {o["code"]: o for o in body}
    assert by_code["IRPF"]["periodicity"] == "trimestral"
    assert by_code["CCAA"]["name"] == "Dipòsit de comptes (CCAA)"
    assert by_code["CASS"]["periodicity"] == "mensual"
    assert by_code["IS"]["periodicity"] == "anual"


# --------------------------------------------------------------------------- #
# Instance endpoint: mapping, status, filters, ordering
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_instance_mapping_includes_obligation_project_client_names(frozen_client):
    """Each instance resolves the obligation, project and client display names."""
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    row = next(o for o in resp.json() if o["id"] == "pobl-002")
    assert set(row) == {
        "id",
        "obligation",
        "project",
        "client",
        "subject",
        "due_date",
        "submission_date",
        "status",
    }
    assert row["obligation"] == {"code": "CCAA", "name": "Dipòsit de comptes (CCAA)"}
    assert row["project"] == {"id": "proj-007", "name": "Comptabilitat fundació"}
    assert row["client"] == {"id": "cust-005", "name": "Fundació Cultural Andorrana"}
    assert row["subject"] is True
    assert row["due_date"] == "2026-06-20"
    assert row["submission_date"] is None
    assert row["status"] == "Vencido"


@pytest.mark.integration
def test_derived_status_across_endpoint(frozen_client):
    """The endpoint derives Vencido / Próximo / Al día for the frozen date."""
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    status_by_id = {o["id"]: o["status"] for o in resp.json()}
    # Filed, though past due.
    assert status_by_id["pobl-001"] == "Al día"
    # Unfiled and past due.
    assert status_by_id["pobl-002"] == "Vencido"
    # Unfiled, due 2026-07-05 -> within the 7-day window of 2026-07-01.
    assert status_by_id["pobl-006"] == "Próximo"
    # Unfiled, due 2026-10-31 -> far future.
    assert status_by_id["pobl-012"] == "Al día"


@pytest.mark.integration
def test_results_ordered_by_due_date(frozen_client):
    """Instances come back ordered by due date ascending."""
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    due_dates = [o["due_date"] for o in resp.json()]
    assert due_dates == sorted(due_dates)


@pytest.mark.integration
def test_status_filter(frozen_client):
    """?status= keeps only instances in that derived state."""
    resp = frozen_client.get(OBLIGATIONS_URL, params={"status": "Vencido"})
    assert resp.status_code == 200
    body = resp.json()
    assert {o["status"] for o in body} == {"Vencido"}
    # pobl-002..005 are overdue; pobl-001 is filed so it drops out.
    assert {o["id"] for o in body} == {"pobl-002", "pobl-003", "pobl-004", "pobl-005"}


@pytest.mark.integration
def test_project_id_filter(frozen_client):
    """?project_id= restricts to a single project's obligations."""
    resp = frozen_client.get(OBLIGATIONS_URL, params={"project_id": "proj-012"})
    assert resp.status_code == 200
    body = resp.json()
    assert {o["project"]["id"] for o in body} == {"proj-012"}
    assert {o["id"] for o in body} == {"pobl-003", "pobl-005"}


@pytest.mark.integration
def test_due_date_range_filter(frozen_client):
    """?due_after / ?due_before bound the due date (both inclusive) and compose."""
    resp = frozen_client.get(
        OBLIGATIONS_URL,
        params={"due_after": "2026-06-20", "due_before": "2026-07-05"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {o["id"] for o in body} == {
        "pobl-002",
        "pobl-003",
        "pobl-004",
        "pobl-005",
        "pobl-006",
        "pobl-008",
        "pobl-011",
    }


@pytest.mark.integration
def test_filters_compose(frozen_client):
    """status + project_id intersect (all must match)."""
    resp = frozen_client.get(
        OBLIGATIONS_URL,
        params={"status": "Vencido", "project_id": "proj-012"},
    )
    assert resp.status_code == 200
    assert {o["id"] for o in resp.json()} == {"pobl-003", "pobl-005"}


@pytest.mark.integration
def test_invalid_status_is_rejected(client):
    """An unknown status value is rejected by validation (422)."""
    resp = client.get(OBLIGATIONS_URL, params={"status": "Bogus"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Live-shaped data: obligations / links with no dates (issue #40)
# --------------------------------------------------------------------------- #


class _LiveShapedBCClient(BusinessCentralClient):
    """A stand-in BC client shaped like the real (thin) BC payloads.

    Obligations expose only code/name (no periodicity/rule) and project-obligation
    links carry no subject/dates/status — exactly what the live client returns
    today, so we can exercise the ``due_date is None`` path without HTTP mocking.
    """

    def get_customers(self):
        return [
            BCCustomer(
                id="C1",
                name="Acme SL",
                nif="A1",
                customer_type="Company",
                responsible="MS",
                active_project_count=1,
                status=CustomerStatus.active,
            )
        ]

    def get_customers_page(self, **kwargs):
        return BCCustomerPage(items=self.get_customers(), next_cursor=None)

    def get_projects(self):
        return [
            BCProject(
                id="P1",
                name="Fiscal advisory",
                customer_id="C1",
                responsible="",
                technician="",
                status=ProjectStatus.active,
            )
        ]

    def get_projects_page(self, **kwargs):
        return BCProjectPage(items=self.get_projects(), next_cursor=None)

    def get_customer_names(self, customer_ids):
        wanted = set(customer_ids)
        return {c.id: c.name for c in self.get_customers() if c.id in wanted}

    def get_users(self):
        return []

    def get_user_tasks(self):
        return []

    def get_obligations(self):
        return [BCObligation(id="IRPF", code="IRPF", name="IRPF")]

    def get_project_obligations(self):
        return [
            BCProjectObligation(id="po-1", project_id="P1", obligation_id="IRPF")
        ]


@pytest.mark.unit
def test_catalog_carries_none_periodicity_for_live_shaped_obligation():
    """A live-shaped obligation surfaces with periodicity/rule as None."""
    service = ObligationsService(db=None, bc_client=_LiveShapedBCClient())
    catalog = service.list_catalog()
    assert len(catalog) == 1
    assert catalog[0].code == "IRPF"
    assert catalog[0].periodicity is None
    assert catalog[0].due_date_rule is None


@pytest.mark.unit
def test_undated_instance_does_not_crash_and_is_sin_fecha():
    """A dateless link is mapped to Sin fecha, resolving its display names."""
    service = ObligationsService(db=None, bc_client=_LiveShapedBCClient())
    result = service.list_project_obligations(reference_date=FROZEN_TODAY)
    assert len(result) == 1
    row = result[0]
    assert row.due_date is None
    assert row.subject is None
    assert row.status is DerivedObligationStatus.undated
    # Display names still resolve from the catalog/project/customer.
    assert row.obligation.name == "IRPF"
    assert row.project.name == "Fiscal advisory"
    assert row.client.name == "Acme SL"


@pytest.mark.unit
def test_undated_instances_excluded_from_date_bounded_filters():
    """Undated instances never match a due_after / due_before bound."""
    service = ObligationsService(db=None, bc_client=_LiveShapedBCClient())
    assert service.list_project_obligations(
        reference_date=FROZEN_TODAY, due_after=date(2020, 1, 1)
    ) == []
    assert service.list_project_obligations(
        reference_date=FROZEN_TODAY, due_before=date(2030, 1, 1)
    ) == []
    # ...but a status filter for the undated bucket still returns them.
    undated = service.list_project_obligations(
        reference_date=FROZEN_TODAY, status=DerivedObligationStatus.undated
    )
    assert {r.id for r in undated} == {"po-1"}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


@pytest.mark.auth
def test_catalog_requires_authentication(db_session):
    """Without a verified user the catalog endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(CATALOG_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.auth
def test_instances_require_authentication(db_session):
    """Without a verified user the instances endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(OBLIGATIONS_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
