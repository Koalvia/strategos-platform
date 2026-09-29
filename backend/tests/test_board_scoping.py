"""Client scoping of the Tareas-board data sources (tasks + obligations).

Both GET /tasks and GET /obligations must return only the caller's visible clients'
rows; a manager sees everything. Actors come from the mock BC fixtures via the real
customer-scope resolver (same as test_customer_scoping.py):

* marc@strategos.ad  -> RES-01, manageAllCustomers -> manager (sees all).
* jordi@strategos.ad -> RES-02 -> cust-001/cust-002 (proj-001..004), non-manager.
* anna@strategos.ad  -> a resource with no customer assignments -> sees none.
"""

from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.main import app

TASKS_URL = "/api/v1/tasks"
BOARD_URL = "/api/v1/tasks/board"
OBLIGATIONS_URL = "/api/v1/obligations"

MANAGER_EMAIL = "marc@strategos.ad"
SCOPED_EMAIL = "jordi@strategos.ad"
UNLINKED_EMAIL = "anna@strategos.ad"  # no customers, but responsible of some projects
NOBODY_EMAIL = "pol@strategos.ad"  # no resource, no technician/responsible link

SCOPED_CUSTOMERS = {"cust-001", "cust-002"}
SCOPED_PROJECTS = {"proj-001", "proj-002", "proj-003", "proj-004"}
# jordi (usr-jordi / "Jordi Vila") is also the technician of these projects, so the
# union rule (client OR technician) widens his board beyond his assigned clients.
JORDI_TECHNICIAN_PROJECTS = {
    "proj-001",
    "proj-003",
    "proj-006",
    "proj-008",
    "proj-010",
    "proj-012",
    "proj-019",
}
JORDI_VISIBLE_PROJECTS = SCOPED_PROJECTS | JORDI_TECHNICIAN_PROJECTS

TOTAL_TASKS = 17  # matches the user_tasks.json fixture (see test_business_central_mock)


@pytest.fixture
def client_as(db_session) -> Generator:
    """TestClient authenticated as a given email, with the real scope resolver.

    Unlike the shared ``client`` fixture, this does NOT pin the customer scope, so
    ``resolve_customer_scope`` runs against the mock BC resources.
    """
    app.dependency_overrides.clear()

    def override_get_db():
        yield db_session

    def make(email: str) -> TestClient:
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
# Tasks
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_manager_sees_all_tasks(client_as):
    """The board shows every BC task, plus obligations as cards, for a manager."""
    with client_as(MANAGER_EMAIL) as client:
        board = client.get(BOARD_URL).json()
    task_cards = [c for c in board if c["source"] == "task"]
    assert len(task_cards) == TOTAL_TASKS
    assert any(c["source"] == "obligation" for c in board)


@pytest.mark.integration
def test_scoped_user_sees_union_of_client_and_technician_projects(client_as):
    """A scoped user's board carries their clients' AND their technician projects."""
    with client_as(SCOPED_EMAIL) as client:
        board = client.get(BOARD_URL).json()
    task_cards = [c for c in board if c["source"] == "task"]
    assert task_cards
    assert len(task_cards) < TOTAL_TASKS
    seen_projects = {c["project"]["id"] for c in task_cards}
    # Only projects in the union (client OR technician), and nothing else.
    assert seen_projects <= JORDI_VISIBLE_PROJECTS
    # Includes a technician-only project (proj-006, cust-004 — not jordi's client).
    assert "proj-006" in seen_projects
    # Excludes a project that is neither his client nor his technician project.
    assert "proj-013" not in seen_projects


@pytest.mark.integration
def test_unlinked_user_sees_empty_board(client_as):
    """A user with no client scope sees no tasks and no obligations."""
    with client_as(UNLINKED_EMAIL) as client:
        board = client.get(BOARD_URL).json()
    assert board == []


# --------------------------------------------------------------------------- #
# Obligations
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_manager_sees_all_obligations(client_as):
    with client_as(MANAGER_EMAIL) as client:
        page = client.get(OBLIGATIONS_URL).json()
    assert page["items"]  # the fixture has obligations


@pytest.mark.integration
def test_scoped_user_sees_client_and_technician_obligations(client_as):
    with client_as(MANAGER_EMAIL) as client:
        all_items = client.get(OBLIGATIONS_URL).json()["items"]
    with client_as(SCOPED_EMAIL) as client:
        scoped_items = client.get(OBLIGATIONS_URL).json()["items"]

    assert len(scoped_items) <= len(all_items)
    # Union: every obligation jordi sees belongs to a client OR technician project.
    assert all(o["project"]["id"] in JORDI_VISIBLE_PROJECTS for o in scoped_items)
    # Includes an obligation of a technician-only project (pobl-010 / proj-006).
    assert any(o["id"] == "pobl-010" for o in scoped_items)


@pytest.mark.integration
def test_responsible_sees_their_project_obligations(client_as):
    """Anna is responsible of proj-003 (not her client) → sees its obligation pobl-004."""
    with client_as(UNLINKED_EMAIL) as client:
        items = client.get(OBLIGATIONS_URL).json()["items"]
    assert any(o["id"] == "pobl-004" for o in items)


@pytest.mark.integration
def test_user_without_any_link_sees_no_obligations(client_as):
    with client_as(NOBODY_EMAIL) as client:
        page = client.get(OBLIGATIONS_URL).json()
    assert page["items"] == []
