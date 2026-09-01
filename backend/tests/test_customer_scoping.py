"""End-to-end tests for the customer/project scoping (the ticket's acceptance criteria).

Two callers, driven by the mock fixtures: Marc (``marc@estrategos.ad``, RES-01, the
manager) and Jordi (``jordi@estrategos.ad``, RES-02, assigned cust-001 and cust-002).

Fixture shape the assertions lean on: 15 customers, 19 projects, and cust-001/cust-002
own 4 of them (2 each).
"""

from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.main import app

CUSTOMERS_URL = "/api/v1/customers"
PROJECTS_URL = "/api/v1/projects"

MANAGER_EMAIL = "marc@estrategos.ad"
SCOPED_EMAIL = "jordi@estrategos.ad"
UNASSIGNED_EMAIL = "anna@estrategos.ad"

SCOPED_CUSTOMERS = {"cust-001", "cust-002"}
SCOPED_PROJECTS = {"proj-001", "proj-002", "proj-003", "proj-004"}


@pytest.fixture
def client_as(db_session) -> Generator:
    """Build a TestClient authenticated as a user with the given email."""
    app.dependency_overrides.clear()

    def override_get_db():
        yield db_session

    def make(email: str) -> TestClient:
        # Reuse the account when one already exists (the staff seed creates these
        # emails too), so the fixture composes with seeded tests.
        user = db_session.query(User).filter(User.email.ilike(email)).one_or_none()
        if user is None:
            user = User(
                name=email.split("@")[0],
                email=email,
                hashed_password="not-a-real-hash",
                is_verified=True,
            )
            db_session.add(user)
        user.is_verified = True
        db_session.commit()
        db_session.refresh(user)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_verified_user] = lambda: user
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Clientes
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_manager_sees_every_customer(client_as):
    """The manager's listing is unchanged: all 15 fixture customers."""
    with client_as(MANAGER_EMAIL) as client:
        body = client.get(CUSTOMERS_URL, params={"page_size": 100}).json()

    assert len(body["items"]) == 15


@pytest.mark.integration
def test_scoped_user_sees_only_their_customers(client_as):
    """A non-manager sees exactly their assigned customers — the ticket's core ask."""
    with client_as(SCOPED_EMAIL) as client:
        resp = client.get(CUSTOMERS_URL, params={"page_size": 100})

    assert resp.status_code == 200
    assert {c["id"] for c in resp.json()["items"]} == SCOPED_CUSTOMERS


@pytest.mark.integration
def test_user_without_assignments_sees_no_customers(client_as):
    """Resolving with zero assignments is an empty list, not the whole company."""
    with client_as(UNASSIGNED_EMAIL) as client:
        resp = client.get(CUSTOMERS_URL, params={"page_size": 100})

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.integration
def test_empty_page_says_whether_it_is_a_missing_assignment(client_as):
    """The flag lets the screen say "no tienes clientes asignados" truthfully.

    It must be true only for the unassigned caller — not for a search that found
    nothing, and not for a manager.
    """
    with client_as(UNASSIGNED_EMAIL) as client:
        unassigned = client.get(CUSTOMERS_URL, params={"page_size": 100}).json()
        unassigned_projects = client.get(PROJECTS_URL, params={"page_size": 100}).json()
    with client_as(SCOPED_EMAIL) as client:
        no_match = client.get(
            CUSTOMERS_URL, params={"search": "Fundació", "page_size": 100}
        ).json()
    with client_as(MANAGER_EMAIL) as client:
        manager = client.get(CUSTOMERS_URL, params={"page_size": 100}).json()

    assert unassigned["no_assigned_customers"] is True
    assert unassigned_projects["no_assigned_customers"] is True
    # Same empty list, different cause: this one is a filter with no matches.
    assert no_match["items"] == [] and no_match["no_assigned_customers"] is False
    assert manager["no_assigned_customers"] is False


@pytest.mark.integration
def test_scoped_user_cannot_open_another_customer(client_as):
    """A customer outside the scope is a 404, so the URL reveals nothing."""
    with client_as(SCOPED_EMAIL) as client:
        allowed = client.get(f"{CUSTOMERS_URL}/cust-001")
        forbidden = client.get(f"{CUSTOMERS_URL}/cust-005")

    assert allowed.status_code == 200
    assert forbidden.status_code == 404


@pytest.mark.integration
def test_manager_can_open_any_customer(client_as):
    """The manager's detail page keeps working for every customer."""
    with client_as(MANAGER_EMAIL) as client:
        assert client.get(f"{CUSTOMERS_URL}/cust-005").status_code == 200


@pytest.mark.integration
def test_scoping_composes_with_search(client_as):
    """A search still cannot reach outside the scope."""
    with client_as(SCOPED_EMAIL) as client:
        # "Fundació" only matches cust-005, which is not assigned to Jordi.
        resp = client.get(CUSTOMERS_URL, params={"search": "Fundació", "page_size": 100})

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.integration
def test_scoped_response_shape_is_unchanged(client_as):
    """Scoping changes which rows come back, never their fields."""
    with client_as(SCOPED_EMAIL) as client:
        row = client.get(CUSTOMERS_URL, params={"page_size": 100}).json()["items"][0]

    assert set(row) == {
        "id",
        "name",
        "nif",
        "entity_type",
        "responsible",
        "project_count",
        "status",
    }


# --------------------------------------------------------------------------- #
# Proyectos
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_manager_sees_every_project(client_as):
    """The manager's project listing is unchanged: all 19."""
    with client_as(MANAGER_EMAIL) as client:
        body = client.get(PROJECTS_URL, params={"page_size": 100}).json()

    assert len(body["items"]) == 19


@pytest.mark.integration
def test_scoped_user_sees_only_their_customers_projects(client_as):
    """Projects follow the customer scope — "solo sus propios proyectos"."""
    with client_as(SCOPED_EMAIL) as client:
        resp = client.get(PROJECTS_URL, params={"page_size": 100})

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {p["id"] for p in items} == SCOPED_PROJECTS
    assert {p["customer"]["id"] for p in items} == SCOPED_CUSTOMERS


@pytest.mark.integration
def test_user_without_assignments_sees_no_projects(client_as):
    with client_as(UNASSIGNED_EMAIL) as client:
        resp = client.get(PROJECTS_URL, params={"page_size": 100})

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.integration
def test_scoped_user_cannot_open_another_customers_project(client_as):
    """proj-007 belongs to cust-005, outside Jordi's scope."""
    with client_as(SCOPED_EMAIL) as client:
        allowed = client.get(f"{PROJECTS_URL}/proj-001")
        forbidden = client.get(f"{PROJECTS_URL}/proj-007")

    assert allowed.status_code == 200
    assert forbidden.status_code == 404


@pytest.mark.integration
def test_customer_id_filter_cannot_escape_the_scope(client_as):
    """Asking for another customer's projects by query param returns nothing."""
    with client_as(SCOPED_EMAIL) as client:
        resp = client.get(
            PROJECTS_URL, params={"customer_id": "cust-005", "page_size": 100}
        )

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.integration
def test_scoped_listing_pages_across_requests(client_as):
    """A scoped listing still paginates, and the pages do not overlap."""
    with client_as(SCOPED_EMAIL) as client:
        first = client.get(CUSTOMERS_URL, params={"page_size": 1}).json()
        assert len(first["items"]) == 1
        assert first["next_cursor"] is not None

        second = client.get(
            CUSTOMERS_URL, params={"page_size": 1, "cursor": first["next_cursor"]}
        ).json()

    assert len(second["items"]) == 1
    first_ids = {c["id"] for c in first["items"]}
    second_ids = {c["id"] for c in second["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == SCOPED_CUSTOMERS


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_dashboard_kpis_follow_the_scope(client_as):
    """The KPI tiles agree with the listings instead of reporting company totals."""
    with client_as(SCOPED_EMAIL) as client:
        customers = client.get("/api/v1/dashboard/active-customers").json()
        projects = client.get("/api/v1/dashboard/active-projects").json()

    assert customers["total"] == len(SCOPED_CUSTOMERS)
    assert projects["total"] == len(SCOPED_PROJECTS)


@pytest.mark.integration
def test_dashboard_kpis_unchanged_for_the_manager(client_as):
    with client_as(MANAGER_EMAIL) as client:
        customers = client.get("/api/v1/dashboard/active-customers").json()
        projects = client.get("/api/v1/dashboard/active-projects").json()

    assert customers["total"] == 15
    assert projects["total"] == 19


@pytest.mark.integration
def test_dashboard_billing_is_scoped_and_still_paginates(client_as):
    """Billing pages within the scope: the window stays 10, the universe shrinks."""
    with client_as(SCOPED_EMAIL) as client:
        body = client.get(
            "/api/v1/dashboard/billing", params={"page": 1, "page_size": 10}
        ).json()

    assert body["meta"]["total_count"] == len(SCOPED_CUSTOMERS)
    assert body["meta"]["page_size"] == 10
    assert {row["customer_id"] for row in body["items"]} <= SCOPED_CUSTOMERS


# --------------------------------------------------------------------------- #
# Usuarios (same rule, one resolver)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_users_directory_follows_the_same_rule(client_as, db_session):
    """The manager sees the whole staff directory; a scoped user sees only themselves."""
    from scripts.seed_staff_users import seed_staff_users

    seed_staff_users(db_session)

    with client_as(MANAGER_EMAIL) as client:
        manager_rows = client.get("/api/v1/users").json()
    with client_as(SCOPED_EMAIL) as client:
        scoped_rows = client.get("/api/v1/users").json()

    assert len(manager_rows) == 6
    assert [row["email"] for row in scoped_rows] == [SCOPED_EMAIL]
