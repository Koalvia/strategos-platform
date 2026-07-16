"""Tests for the read-only tasks (Tareas) domain (issue #10).

Tasks are served from the fixture-backed ``MockBusinessCentralClient`` (the
default DI mode); only internal notes live in the local ``task_notes`` table
(covered by ``test_tasks_local_table.py``). These tests cover:

* the list endpoint (count + field mapping of title / project / assignee /
  priority / status / due date),
* the ``status`` / ``project_id`` / ``assignee_id`` filters and that they compose,
* ``/tasks/mine`` scoping to the current user (mapped to their BC assignee by
  email, and empty when no BC user matches), and
* that the endpoints reject unauthenticated requests.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.main import app

TASKS_URL = "/api/v1/tasks"
MINE_URL = "/api/v1/tasks/mine"


@pytest.fixture
def bc_user_client(db_session):
    """An authenticated client whose user maps to BC assignee ``usr-anna``.

    ``list_my_tasks`` resolves the BC assignee by email, so the seeded user's
    email must match a BC user (``anna@estrategos.ad``).
    """
    user = User(
        name="Anna Ferrer",
        email="anna@estrategos.ad",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_verified_user] = lambda: user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# List endpoint: mapping, count
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_list_returns_all_tasks(client):
    """The list returns every mock task (15)."""
    resp = client.get(TASKS_URL)
    assert resp.status_code == 200
    assert len(resp.json()) == 15


@pytest.mark.integration
def test_task_field_mapping(client):
    """Each task maps title/project/assignee/priority/status/due date from BC."""
    resp = client.get(TASKS_URL)
    assert resp.status_code == 200
    row = next(t for t in resp.json() if t["id"] == "task-001")
    assert set(row) == {
        "id",
        "title",
        "project",
        "assignee",
        "priority",
        "status",
        "due_date",
    }
    assert row["title"] == "Revisar model IS abans de presentar"
    assert row["project"] == {"id": "proj-001", "name": "Assessorament fiscal i comptable"}
    assert row["assignee"] == {"id": "usr-marc", "name": "Marc Solé"}
    assert row["priority"] == "Alta"
    assert row["status"] == "Pendiente"
    assert row["due_date"] == "2026-07-08"


@pytest.mark.integration
def test_priority_and_status_vocabulary(client):
    """Priority and status use the Alta/Media/Baja · Pendiente/En curso/Hecho labels."""
    resp = client.get(TASKS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert {t["priority"] for t in body} <= {"Alta", "Media", "Baja"}
    assert {t["status"] for t in body} <= {"Pendiente", "En curso", "Hecho"}
    # The mock spans all three columns.
    assert {t["status"] for t in body} == {"Pendiente", "En curso", "Hecho"}


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_status_filter(client):
    """?status= keeps only tasks in that board column."""
    resp = client.get(TASKS_URL, params={"status": "En curso"})
    assert resp.status_code == 200
    body = resp.json()
    assert {t["status"] for t in body} == {"En curso"}
    assert {t["id"] for t in body} == {"task-011", "task-012", "task-013"}


@pytest.mark.integration
def test_project_id_filter(client):
    """?project_id= restricts to a single project's tasks."""
    resp = client.get(TASKS_URL, params={"project_id": "proj-001"})
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()} == {"task-001", "task-012"}


@pytest.mark.integration
def test_assignee_id_filter(client):
    """?assignee_id= restricts to a single assignee's tasks."""
    resp = client.get(TASKS_URL, params={"assignee_id": "usr-marc"})
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()} == {"task-001", "task-002", "task-014"}


@pytest.mark.integration
def test_filters_compose(client):
    """status + assignee_id intersect (all must match)."""
    resp = client.get(
        TASKS_URL, params={"status": "Hecho", "assignee_id": "usr-marc"}
    )
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()} == {"task-014"}


@pytest.mark.integration
def test_project_id_and_assignee_id_compose(client):
    """project_id + assignee_id intersect (all must match)."""
    # proj-001 has task-001 (usr-marc) and task-012 (usr-jordi); scoping to
    # usr-marc keeps only task-001.
    resp = client.get(
        TASKS_URL, params={"project_id": "proj-001", "assignee_id": "usr-marc"}
    )
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()} == {"task-001"}


@pytest.mark.integration
def test_invalid_status_is_rejected(client):
    """An unknown status value is rejected by validation (422)."""
    resp = client.get(TASKS_URL, params={"status": "Bogus"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# /tasks/mine
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_mine_scopes_to_current_user(bc_user_client):
    """/tasks/mine returns only tasks assigned to the mapped BC user."""
    resp = bc_user_client.get(MINE_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert {t["assignee"]["id"] for t in body} == {"usr-anna"}
    assert {t["id"] for t in body} == {"task-003", "task-006", "task-011", "task-015"}


@pytest.mark.integration
def test_mine_respects_status_filter(bc_user_client):
    """/tasks/mine composes with ?status=."""
    resp = bc_user_client.get(MINE_URL, params={"status": "En curso"})
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()} == {"task-011"}


@pytest.mark.integration
def test_mine_empty_when_no_bc_user_matches(client):
    """A local user with no matching BC email has no tasks."""
    # The default ``test_user`` email (test@example.com) is not a BC user.
    resp = client.get(MINE_URL)
    assert resp.status_code == 200
    assert resp.json() == []


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


@pytest.mark.auth
def test_list_requires_authentication(db_session):
    """Without a verified user the list endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(TASKS_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.auth
def test_mine_requires_authentication(db_session):
    """Without a verified user the mine endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(MINE_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
