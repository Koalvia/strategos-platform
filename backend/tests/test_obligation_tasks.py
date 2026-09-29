"""Tests for obligations shown as movable cards on the Tareas board.

The board (GET /tasks) includes one card per obligation, and PATCH /tasks/{id}/status
with ``source="obligation"`` moves it. Auth is by customer scope, like BC tasks. The
initial column is derived (filed -> Hecho, else Pendiente). Actors and obligations
from the mock BC fixtures:

* marc@strategos.ad  -> manager (moves anything).
* jordi@strategos.ad -> cust-001/cust-002 (proj-001..004).
* pobl-004 -> proj-003 -> cust-002 (in jordi's scope).
* pobl-002 -> proj-007 -> cust-005 (out of jordi's scope).
* pobl-001 -> filed (submission_date set) -> initial Hecho.
* pobl-007 -> proj-001, not filed -> initial Pendiente.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.domains.tasks.models import ObligationTaskState
from app.integrations.business_central.models import TaskStatus

TASKS_URL = "/api/v1/tasks"
BOARD_URL = "/api/v1/tasks/board"

MANAGER_EMAIL = "marc@strategos.ad"
SCOPED_EMAIL = "jordi@strategos.ad"

OBLIGATION_IN_SCOPE = "pobl-004"  # proj-003 -> cust-002 (jordi)
OBLIGATION_OUT_OF_SCOPE = "pobl-002"  # proj-007 -> cust-005
SUBMITTED_OBLIGATION = "pobl-001"  # filed -> initial Hecho
UNSUBMITTED_OBLIGATION = "pobl-007"  # proj-001, not filed -> initial Pendiente


def _move(client, obligation_id, status):
    return client.patch(
        f"{TASKS_URL}/{obligation_id}/status",
        json={"status": status, "source": "obligation"},
    )


@pytest.mark.integration
def test_scoped_user_moves_obligation_in_scope(client_as):
    with client_as(SCOPED_EMAIL) as client:
        res = _move(client, OBLIGATION_IN_SCOPE, "En curso")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "En curso"
    assert body["source"] == "obligation"


@pytest.mark.integration
def test_technician_moves_obligation_of_own_project(client_as):
    """A technician can move an obligation of their project even without the client.

    pobl-010 -> proj-006 (cust-004): jordi is not assigned cust-004, but he IS the
    technician of proj-006 ("Jordi Vila"), so the union rule lets him move it.
    """
    with client_as(SCOPED_EMAIL) as client:
        res = _move(client, "pobl-010", "En curso")
    assert res.status_code == 200
    assert res.json()["status"] == "En curso"


@pytest.mark.integration
def test_scoped_user_cannot_move_out_of_scope_obligation(client_as):
    with client_as(SCOPED_EMAIL) as client:
        res = _move(client, OBLIGATION_OUT_OF_SCOPE, "Hecho")
    assert res.status_code == 403


@pytest.mark.integration
def test_manager_moves_any_obligation(client_as):
    with client_as(MANAGER_EMAIL) as client:
        res = _move(client, OBLIGATION_OUT_OF_SCOPE, "En curso")
    assert res.status_code == 200
    assert res.json()["status"] == "En curso"


@pytest.mark.integration
def test_unknown_obligation_is_404(client_as):
    with client_as(MANAGER_EMAIL) as client:
        res = _move(client, "pobl-nope", "Hecho")
    assert res.status_code == 404


@pytest.mark.integration
def test_obligation_cards_have_derived_initial_status(client_as):
    """A filed obligation starts in Hecho; an unfiled one in Pendiente."""
    with client_as(MANAGER_EMAIL) as client:
        board = client.get(BOARD_URL).json()
    by_id = {c["id"]: c for c in board if c["source"] == "obligation"}

    assert by_id[SUBMITTED_OBLIGATION]["status"] == "Hecho"
    assert by_id[UNSUBMITTED_OBLIGATION]["status"] == "Pendiente"
    card = by_id[UNSUBMITTED_OBLIGATION]
    # Carries a traffic-light colour, the client, and the project's technician as
    # assignee (pobl-007 -> proj-001 -> "Jordi Vila").
    assert card["traffic_light"] is not None
    assert card["client"] is not None
    assert card["assignee"]["name"] == "Jordi Vila"


@pytest.mark.integration
def test_obligation_move_persists_on_board(client_as):
    with client_as(MANAGER_EMAIL) as client:
        assert _move(client, UNSUBMITTED_OBLIGATION, "En curso").status_code == 200
        board = client.get(BOARD_URL).json()
    by_id = {c["id"]: c for c in board if c["source"] == "obligation"}
    assert by_id[UNSUBMITTED_OBLIGATION]["status"] == "En curso"


@pytest.mark.unit
def test_obligation_task_state_model_is_unique(db_session, test_user):
    db_session.add(
        ObligationTaskState(
            bc_obligation_id="pobl-XYZ",
            status=TaskStatus.pending,
            updated_by=test_user.id,
        )
    )
    db_session.commit()

    db_session.add(
        ObligationTaskState(
            bc_obligation_id="pobl-XYZ",
            status=TaskStatus.done,
            updated_by=test_user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
