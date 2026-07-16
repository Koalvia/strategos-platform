"""Tests for the read-only customers (Clientes) domain (issue #7).

The domain has no database model — customers are served from the fixture-backed
``MockBusinessCentralClient`` (the default DI mode). These tests exercise the
``GET /api/v1/customers`` endpoint through the real FastAPI app: paginated
listing (``items``/``next_cursor``), the ``search`` and ``status`` filters,
response-field parity with ``clientes.png``, and that the endpoint rejects
unauthenticated requests.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

CUSTOMERS_URL = "/api/v1/customers"


@pytest.mark.integration
def test_list_returns_all_customers_on_one_page(client):
    """The default page size (25) comfortably fits all 14 mock customers in one page."""
    resp = client.get(CUSTOMERS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 14
    assert body["next_cursor"] is None


@pytest.mark.integration
def test_response_fields_match_design_columns(client):
    """Each row exposes exactly the columns from clientes.png."""
    resp = client.get(CUSTOMERS_URL)
    assert resp.status_code == 200
    row = resp.json()["items"][0]
    assert set(row) == {
        "id",
        "name",
        "nif",
        "entity_type",
        "responsible",
        "project_count",
        "status",
    }
    # First mock customer, spot-checking the BC -> response mapping.
    assert row == {
        "id": "cust-001",
        "name": "Fontaneria Puigcerdà SL",
        "nif": "A123456",
        "entity_type": "Societat",
        "responsible": "Marc Solé",
        "project_count": 2,
        "status": "Activo",
    }


@pytest.mark.integration
def test_page_size_paginates_across_requests(client):
    """?page_size= caps a page; ?cursor= continues from ``next_cursor``."""
    first = client.get(CUSTOMERS_URL, params={"page_size": 3})
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 3
    assert first_body["next_cursor"] is not None

    second = client.get(
        CUSTOMERS_URL, params={"page_size": 3, "cursor": first_body["next_cursor"]}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 3

    first_names = {c["name"] for c in first_body["items"]}
    second_names = {c["name"] for c in second_body["items"]}
    assert first_names.isdisjoint(second_names)


@pytest.mark.integration
def test_search_by_name_is_case_insensitive(client):
    """?search= matches the customer name as a case-insensitive substring."""
    resp = client.get(CUSTOMERS_URL, params={"search": "puigcerdà"})
    assert resp.status_code == 200
    body = resp.json()
    assert [c["name"] for c in body["items"]] == ["Fontaneria Puigcerdà SL"]


@pytest.mark.integration
def test_search_by_nif(client):
    """?search= matches the NIF as a case-insensitive substring."""
    resp = client.get(CUSTOMERS_URL, params={"search": "g567890"})
    assert resp.status_code == 200
    body = resp.json()
    assert [c["nif"] for c in body["items"]] == ["G567890"]
    assert body["items"][0]["name"] == "Fundació Cultural Andorrana"


@pytest.mark.integration
def test_search_with_no_match_returns_empty(client):
    """A search that matches nothing returns an empty list, not an error."""
    resp = client.get(CUSTOMERS_URL, params={"search": "no-such-customer"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.integration
def test_status_filter_isolates_the_inactive_customer(client):
    """?status=Inactivo returns only the single inactive customer."""
    resp = client.get(CUSTOMERS_URL, params={"status": "Inactivo"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Clínica Dental Ordino SL"
    assert body["items"][0]["status"] == "Inactivo"


@pytest.mark.integration
def test_status_filter_active_returns_active_customers(client):
    """?status=Activo returns the 13 active customers (only cust-008 is inactive)."""
    resp = client.get(CUSTOMERS_URL, params={"status": "Activo"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 13
    assert all(c["status"] == "Activo" for c in body["items"])


@pytest.mark.integration
def test_search_and_status_compose(client):
    """?search= and ?status= intersect (AND): both must match."""
    # cust-008 "Clínica Dental Ordino SL" is the one Inactivo customer.
    active = client.get(CUSTOMERS_URL, params={"search": "Ordino", "status": "Activo"})
    assert active.status_code == 200
    assert active.json()["items"] == []
    inactive = client.get(
        CUSTOMERS_URL, params={"search": "Ordino", "status": "Inactivo"}
    )
    assert [c["id"] for c in inactive.json()["items"]] == ["cust-008"]


@pytest.mark.integration
def test_last_page_has_no_next_cursor(client):
    """Paging to the final page yields the remainder and a null next_cursor."""
    first = client.get(CUSTOMERS_URL, params={"page_size": 10}).json()
    assert len(first["items"]) == 10
    assert first["next_cursor"] is not None
    second = client.get(
        CUSTOMERS_URL, params={"page_size": 10, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 4  # 14 total - 10 on the first page
    assert second["next_cursor"] is None


@pytest.mark.integration
def test_generated_client_is_listed_and_detailed(client):
    """A generated client (cust-014) surfaces in the list and detail views.

    Expected display values are resolved from the mock BC client rather than
    hardcoded, since the client fields are Faker-generated in the fixture.
    """
    from app.integrations.business_central.mock_client import (
        MockBusinessCentralClient,
    )

    expected = next(
        c for c in MockBusinessCentralClient().get_customers() if c.id == "cust-014"
    )
    listing = client.get(CUSTOMERS_URL).json()["items"]
    assert any(c["id"] == "cust-014" for c in listing)

    detail = client.get(f"{CUSTOMERS_URL}/cust-014")
    assert detail.status_code == 200
    body = detail.json()
    assert body["name"] == expected.name
    assert body["entity_type"] == expected.customer_type
    # project_count is sourced from the BC active_project_count, not a live count.
    assert body["project_count"] == expected.active_project_count
    assert body["status"] == "Activo"


@pytest.mark.integration
def test_invalid_status_is_rejected(client):
    """An unknown status value is rejected by validation (422)."""
    resp = client.get(CUSTOMERS_URL, params={"status": "Bogus"})
    assert resp.status_code == 422


@pytest.mark.integration
def test_detail_returns_a_known_customer(client):
    """GET /customers/{id} returns the one customer, all fields mapped."""
    resp = client.get(f"{CUSTOMERS_URL}/cust-005")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "id": "cust-005",
        "name": "Fundació Cultural Andorrana",
        "nif": "G567890",
        "entity_type": "Fundació",
        "responsible": "Anna Ferrer",
        "project_count": 1,
        "status": "Activo",
    }


@pytest.mark.integration
def test_detail_unknown_id_returns_404(client):
    """GET /customers/{id} 404s for an unknown id."""
    resp = client.get(f"{CUSTOMERS_URL}/cust-999")
    assert resp.status_code == 404


@pytest.mark.auth
def test_endpoint_requires_authentication(db_session):
    """Without a verified user the endpoint refuses the request.

    Here we deliberately do NOT override ``get_verified_user`` so the real
    dependency runs; with no bearer credentials the request is rejected.
    """

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(CUSTOMERS_URL)
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
            resp = unauth_client.get(f"{CUSTOMERS_URL}/cust-001")
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
