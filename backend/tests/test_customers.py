"""Tests for the read-only customers (Clientes) domain (issue #7).

The domain has no database model — customers are served from the fixture-backed
``MockBusinessCentralClient`` (the default DI mode). These tests exercise the
``GET /api/v1/customers`` endpoint through the real FastAPI app: list, the
``search`` and ``status`` filters, response-field parity with ``clientes.png``,
and that the endpoint rejects unauthenticated requests.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

CUSTOMERS_URL = "/api/v1/customers"


@pytest.mark.integration
def test_list_returns_all_eight_customers(client):
    """The list returns every mock customer."""
    resp = client.get(CUSTOMERS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 8


@pytest.mark.integration
def test_response_fields_match_design_columns(client):
    """Each row exposes exactly the columns from clientes.png."""
    resp = client.get(CUSTOMERS_URL)
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == {
        "name",
        "nif",
        "entity_type",
        "responsible",
        "project_count",
        "status",
    }
    # First mock customer, spot-checking the BC -> response mapping.
    assert row == {
        "name": "Fontaneria Puigcerdà SL",
        "nif": "A123456",
        "entity_type": "Societat",
        "responsible": "Marc Solé",
        "project_count": 2,
        "status": "Activo",
    }


@pytest.mark.integration
def test_search_by_name_is_case_insensitive(client):
    """?search= matches the customer name as a case-insensitive substring."""
    resp = client.get(CUSTOMERS_URL, params={"search": "puigcerdà"})
    assert resp.status_code == 200
    body = resp.json()
    assert [c["name"] for c in body] == ["Fontaneria Puigcerdà SL"]


@pytest.mark.integration
def test_search_by_nif(client):
    """?search= matches the NIF as a case-insensitive substring."""
    resp = client.get(CUSTOMERS_URL, params={"search": "g567890"})
    assert resp.status_code == 200
    body = resp.json()
    assert [c["nif"] for c in body] == ["G567890"]
    assert body[0]["name"] == "Fundació Cultural Andorrana"


@pytest.mark.integration
def test_search_with_no_match_returns_empty(client):
    """A search that matches nothing returns an empty list, not an error."""
    resp = client.get(CUSTOMERS_URL, params={"search": "no-such-customer"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_status_filter_isolates_the_inactive_customer(client):
    """?status=Inactivo returns only the single inactive customer."""
    resp = client.get(CUSTOMERS_URL, params={"status": "Inactivo"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Clínica Dental Ordino SL"
    assert body[0]["status"] == "Inactivo"


@pytest.mark.integration
def test_status_filter_active_returns_seven(client):
    """?status=Activo returns the seven active customers."""
    resp = client.get(CUSTOMERS_URL, params={"status": "Activo"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 7
    assert all(c["status"] == "Activo" for c in body)


@pytest.mark.integration
def test_invalid_status_is_rejected(client):
    """An unknown status value is rejected by validation (422)."""
    resp = client.get(CUSTOMERS_URL, params={"status": "Bogus"})
    assert resp.status_code == 422


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
