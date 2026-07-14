"""Tests for the read-only projects (Proyectos) domain (issue #8).

The domain has no database model — projects are served from the fixture-backed
``MockBusinessCentralClient`` (the default DI mode). These tests exercise the
``GET /api/v1/projects`` and ``GET /api/v1/projects/{id}`` endpoints through the
real FastAPI app: list count, the fitxa General fields (including the
customer-name enrichment), the ``search`` / ``project_type`` / ``entity_type`` /
``status`` filters and their composition, detail + 404, and that the endpoints
reject unauthenticated requests.

A second block covers live-shaped data (issue #41/#42 follow-up): the live BC
client leaves ``project_type``/``entity_type``/``has_certificate`` as ``None``
(no source field exists yet), which previously crashed ``ProjectResponse``
validation and the ``project_type``/``entity_type`` filters with a 500.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.projects.service import ProjectsService
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerPage,
    BCProject,
    BCProjectPage,
    CustomerStatus,
    ProjectStatus,
)
from app.main import app

PROJECTS_URL = "/api/v1/projects"


@pytest.mark.integration
def test_list_returns_all_twelve_projects_on_one_page(client):
    """The default page size comfortably fits all 12 mock projects in one page."""
    resp = client.get(PROJECTS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 12
    assert body["next_cursor"] is None


@pytest.mark.integration
def test_page_size_paginates_across_requests(client):
    """?page_size= caps a page; ?cursor= continues from ``next_cursor``."""
    first = client.get(PROJECTS_URL, params={"page_size": 5})
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 5
    assert first_body["next_cursor"] is not None

    second = client.get(
        PROJECTS_URL, params={"page_size": 5, "cursor": first_body["next_cursor"]}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 5

    first_ids = {p["id"] for p in first_body["items"]}
    second_ids = {p["id"] for p in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.integration
def test_response_fields_match_general_fitxa(client):
    """Each project exposes the fitxa General fields, customer resolved to name."""
    resp = client.get(PROJECTS_URL)
    assert resp.status_code == 200
    row = next(p for p in resp.json()["items"] if p["id"] == "proj-001")
    assert set(row) == {
        "id",
        "name",
        "customer",
        "project_type",
        "entity_type",
        "responsible",
        "technician",
        "has_certificate",
        "certificate_expiry",
        "filing_date",
        "status",
    }
    assert row == {
        "id": "proj-001",
        "name": "Assessorament fiscal i comptable",
        "customer": {"id": "cust-001", "name": "Fontaneria Puigcerdà SL"},
        "project_type": "Iguala mensual",
        "entity_type": "Societat",
        "responsible": "Marc Solé",
        "technician": "Jordi Vila",
        "has_certificate": True,
        "certificate_expiry": "2027-03-15",
        "filing_date": "2026-07-25",
        "status": "Activo",
    }


@pytest.mark.integration
def test_nullable_certificate_and_filing_date(client):
    """A project without a certificate exposes null expiry (and null filing date)."""
    resp = client.get(PROJECTS_URL)
    assert resp.status_code == 200
    row = next(p for p in resp.json()["items"] if p["id"] == "proj-005")
    assert row["has_certificate"] is False
    assert row["certificate_expiry"] is None
    assert row["filing_date"] is None


@pytest.mark.integration
def test_search_by_name_is_case_insensitive(client):
    """?search= matches the project name as a case-insensitive substring."""
    resp = client.get(PROJECTS_URL, params={"search": "LABORAL"})
    assert resp.status_code == 200
    body = resp.json()
    assert [p["name"] for p in body["items"]] == ["Gestió laboral"]


@pytest.mark.integration
def test_search_with_no_match_returns_empty(client):
    """A search that matches nothing returns an empty list, not an error."""
    resp = client.get(PROJECTS_URL, params={"search": "no-such-project"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.integration
def test_project_type_filter(client):
    """?project_type= keeps only projects of that type (case-insensitive exact)."""
    resp = client.get(PROJECTS_URL, params={"project_type": "iguala trimestral"})
    assert resp.status_code == 200
    body = resp.json()["items"]
    assert {p["project_type"] for p in body} == {"Iguala trimestral"}
    assert {p["id"] for p in body} == {"proj-003", "proj-004", "proj-011"}


@pytest.mark.integration
def test_entity_type_filter(client):
    """?entity_type= keeps only projects for that entity type."""
    resp = client.get(PROJECTS_URL, params={"entity_type": "Persona física"})
    assert resp.status_code == 200
    body = resp.json()["items"]
    assert {p["entity_type"] for p in body} == {"Persona física"}
    assert {p["id"] for p in body} == {"proj-003", "proj-004"}


@pytest.mark.integration
def test_status_filter_isolates_the_inactive_project(client):
    """?status=Inactivo returns only the single inactive project."""
    resp = client.get(PROJECTS_URL, params={"status": "Inactivo"})
    assert resp.status_code == 200
    body = resp.json()["items"]
    assert [p["id"] for p in body] == ["proj-012"]
    assert body[0]["status"] == "Inactivo"


@pytest.mark.integration
def test_customer_id_filter_isolates_one_customers_projects(client):
    """?customer_id= returns only that customer's projects."""
    resp = client.get(PROJECTS_URL, params={"customer_id": "cust-001"})
    assert resp.status_code == 200
    body = resp.json()["items"]
    assert {p["id"] for p in body} == {"proj-001", "proj-002"}
    assert {p["customer"]["id"] for p in body} == {"cust-001"}


@pytest.mark.integration
def test_customer_id_filter_with_no_match_returns_empty(client):
    """?customer_id= for an unknown customer returns an empty list, not an error."""
    resp = client.get(PROJECTS_URL, params={"customer_id": "cust-999"})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.integration
def test_customer_id_filter_composes_with_other_filters(client):
    """?customer_id= intersects with the other filters (all must match)."""
    # cust-007 owns proj-010 (Iguala mensual) and proj-011 (Iguala trimestral);
    # adding project_type keeps only the trimestral one.
    resp = client.get(
        PROJECTS_URL,
        params={"customer_id": "cust-007", "project_type": "Iguala trimestral"},
    )
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["items"]] == ["proj-011"]


@pytest.mark.integration
def test_filters_compose(client):
    """Multiple filters intersect (all must match)."""
    resp = client.get(
        PROJECTS_URL,
        params={"project_type": "Iguala trimestral", "status": "Activo"},
    )
    assert resp.status_code == 200
    body = resp.json()["items"]
    # All three trimestral projects are active, so status=Activo keeps all of them.
    assert {p["id"] for p in body} == {"proj-003", "proj-004", "proj-011"}

    resp = client.get(
        PROJECTS_URL,
        params={"entity_type": "Persona física", "search": "IGI"},
    )
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["items"]] == ["proj-004"]


@pytest.mark.integration
def test_invalid_status_is_rejected(client):
    """An unknown status value is rejected by validation (422)."""
    resp = client.get(PROJECTS_URL, params={"status": "Bogus"})
    assert resp.status_code == 422


@pytest.mark.integration
def test_detail_returns_a_known_project(client):
    """GET /projects/{id} returns the one project, customer name resolved."""
    resp = client.get(f"{PROJECTS_URL}/proj-007")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "proj-007"
    assert body["name"] == "Comptabilitat fundació"
    assert body["customer"] == {"id": "cust-005", "name": "Fundació Cultural Andorrana"}
    assert body["entity_type"] == "Fundació"


@pytest.mark.integration
def test_detail_unknown_id_returns_404(client):
    """GET /projects/{id} 404s for an unknown id."""
    resp = client.get(f"{PROJECTS_URL}/proj-999")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Live-shaped data: no project_type/entity_type/has_certificate source (#41/#42)
# --------------------------------------------------------------------------- #


class _LiveShapedBCClient(BusinessCentralClient):
    """A stand-in BC client shaped like the real (thin) BC payloads.

    The live client has no BC source field for ``project_type``/``entity_type``/
    ``has_certificate`` yet, so it leaves them ``None`` — exactly what this stub
    returns, letting us exercise that path without HTTP mocking.
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

    def get_projects_page(
        self,
        *,
        search=None,
        project_type=None,
        entity_type=None,
        status=None,
        cursor=None,
        page_size=25,
    ):
        projects = self.get_projects()
        if search:
            needle = search.casefold()
            projects = [p for p in projects if needle in p.name.casefold()]
        if project_type is not None:
            wanted = project_type.casefold()
            projects = [
                p for p in projects if (p.project_type or "").casefold() == wanted
            ]
        if entity_type is not None:
            wanted = entity_type.casefold()
            projects = [
                p for p in projects if (p.entity_type or "").casefold() == wanted
            ]
        if status is not None:
            projects = [p for p in projects if p.status is status]
        return BCProjectPage(items=projects, next_cursor=None)

    def get_customer_names(self, customer_ids):
        wanted = set(customer_ids)
        return {c.id: c.name for c in self.get_customers() if c.id in wanted}

    def get_users(self):
        return []

    def get_user_tasks(self):
        return []

    def get_obligations(self):
        return []

    def get_project_obligations(self):
        return []


@pytest.mark.unit
def test_live_shaped_project_serializes_with_none_type_fields():
    """A live-shaped project (no type/certificate data) still validates."""
    service = ProjectsService(db=None, bc_client=_LiveShapedBCClient())
    page = service.list_projects()
    assert len(page.items) == 1
    assert page.items[0].project_type is None
    assert page.items[0].entity_type is None
    assert page.items[0].has_certificate is None


@pytest.mark.unit
def test_project_type_filter_excludes_untyped_projects_without_crashing():
    """Filtering by project_type/entity_type never matches a None field."""
    service = ProjectsService(db=None, bc_client=_LiveShapedBCClient())
    assert service.list_projects(project_type="Iguala mensual").items == []
    assert service.list_projects(entity_type="Societat").items == []


@pytest.mark.auth
def test_list_requires_authentication(db_session):
    """Without a verified user the list endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(PROJECTS_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.auth
def test_detail_requires_authentication(db_session):
    """Without a verified user the detail endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(f"{PROJECTS_URL}/proj-001")
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
