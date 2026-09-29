"""Tests for moving BC tasks between workflow columns (PATCH /tasks/{id}/status).

Auth is by the union rule: a manager moves any task; anyone else only tasks whose
project's client is in their scope OR where they are the project's technician or
responsible. Actors from the mock BC fixtures via the real scope resolver:

* marc@strategos.ad  -> RES-01, manageAllCustomers -> manager (moves anything).
* jordi@strategos.ad -> RES-02 -> cust-001/cust-002 (proj-001..004); technician of
  proj-006 among others.
* anna@strategos.ad  -> a resource with no customer assignments; responsible of
  proj-003/004/007/012 only, so she cannot move a task of proj-001.
"""

from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.domains.tasks.models import TaskStatusOverride
from app.integrations.business_central.models import TaskStatus
from app.main import app

TASKS_URL = "/api/v1/tasks"

MANAGER_EMAIL = "marc@strategos.ad"
SCOPED_EMAIL = "jordi@strategos.ad"
UNLINKED_EMAIL = "anna@strategos.ad"

IN_SCOPE_TASK = "task-001"  # proj-001 -> cust-001 -> jordi's scope
OUT_OF_SCOPE_TASK = "task-003"  # proj-007 -> not jordi's

WAITING = "Esperando información / respuesta del cliente"


@pytest.fixture
def client_as(db_session) -> Generator:
    """TestClient authenticated as a given email, using the real scope resolver."""
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


@pytest.mark.integration
def test_scoped_user_moves_task_in_scope(client_as):
    """A non-manager moves a task whose client is in their scope."""
    with client_as(SCOPED_EMAIL) as client:
        res = client.patch(
            f"{TASKS_URL}/{IN_SCOPE_TASK}/status", json={"status": "En curso"}
        )
    assert res.status_code == 200
    assert res.json()["status"] == "En curso"


@pytest.mark.integration
def test_technician_moves_task_of_own_project(client_as):
    """A technician can move a task of their project even without the client.

    task-004 -> proj-006 (cust-004): jordi is not assigned cust-004 but IS the
    technician of proj-006 ("Jordi Vila"), so the union rule lets him move it.
    """
    with client_as(SCOPED_EMAIL) as client:
        res = client.patch(f"{TASKS_URL}/task-004/status", json={"status": "En curso"})
    assert res.status_code == 200


@pytest.mark.integration
def test_scoped_user_cannot_move_out_of_scope_task(client_as):
    """A non-manager cannot move a task of a client outside their scope."""
    with client_as(SCOPED_EMAIL) as client:
        res = client.patch(
            f"{TASKS_URL}/{OUT_OF_SCOPE_TASK}/status", json={"status": "Hecho"}
        )
    assert res.status_code == 403


@pytest.mark.integration
def test_manager_moves_any_task(client_as):
    """A manager moves a task regardless of client."""
    with client_as(MANAGER_EMAIL) as client:
        res = client.patch(
            f"{TASKS_URL}/{OUT_OF_SCOPE_TASK}/status", json={"status": WAITING}
        )
    assert res.status_code == 200
    assert res.json()["status"] == WAITING


@pytest.mark.integration
def test_unlinked_user_cannot_move(client_as):
    """A user with no client scope cannot move any task."""
    with client_as(UNLINKED_EMAIL) as client:
        res = client.patch(
            f"{TASKS_URL}/{IN_SCOPE_TASK}/status", json={"status": "En curso"}
        )
    assert res.status_code == 403


@pytest.mark.integration
def test_unknown_task_is_404(client_as):
    with client_as(MANAGER_EMAIL) as client:
        res = client.patch(f"{TASKS_URL}/task-nope/status", json={"status": "Hecho"})
    assert res.status_code == 404


@pytest.mark.integration
def test_override_is_reflected_on_board_and_filter(client_as):
    """A moved task shows its override status on the board and in the status filter."""
    with client_as(MANAGER_EMAIL) as client:
        moved = client.patch(
            f"{TASKS_URL}/{IN_SCOPE_TASK}/status", json={"status": WAITING}
        )
        assert moved.status_code == 200

        by_id = {c["id"]: c for c in client.get(TASKS_URL).json()}
        assert by_id[IN_SCOPE_TASK]["status"] == WAITING

        waiting = client.get(TASKS_URL, params={"status": WAITING}).json()
        assert any(c["id"] == IN_SCOPE_TASK for c in waiting)

        pending = client.get(TASKS_URL, params={"status": "Pendiente"}).json()
        assert all(c["id"] != IN_SCOPE_TASK for c in pending)


@pytest.mark.integration
def test_patch_is_idempotent_single_row(client_as, db_session):
    with client_as(MANAGER_EMAIL) as client:
        r1 = client.patch(
            f"{TASKS_URL}/{IN_SCOPE_TASK}/status", json={"status": "En curso"}
        )
        r2 = client.patch(
            f"{TASKS_URL}/{IN_SCOPE_TASK}/status", json={"status": "En curso"}
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    rows = (
        db_session.query(TaskStatusOverride)
        .filter(TaskStatusOverride.task_id == IN_SCOPE_TASK)
        .all()
    )
    assert len(rows) == 1


@pytest.mark.unit
def test_status_override_model_persists_and_is_unique(db_session, test_user):
    """The model round-trips the enum and enforces one override per task."""
    db_session.add(
        TaskStatusOverride(
            task_id="task-XYZ",
            status=TaskStatus.waiting_client,
            updated_by=test_user.id,
        )
    )
    db_session.commit()

    row = db_session.query(TaskStatusOverride).filter_by(task_id="task-XYZ").one()
    assert row.status is TaskStatus.waiting_client
    assert row.updated_at is not None

    db_session.add(
        TaskStatusOverride(
            task_id="task-XYZ", status=TaskStatus.done, updated_by=test_user.id
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
