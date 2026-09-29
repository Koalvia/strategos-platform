"""Tests for the shared vertical order of board cards (PUT /tasks/board/order).

The order is global and persisted (position per card), independent of the status
override. Authorized by the union move rule, like status changes. Actors from the
mock BC fixtures via the real scope resolver:

* marc@strategos.ad  -> manager (may move/reorder anything).
* jordi@strategos.ad -> cust-001/cust-002; not proj-007 -> cannot reorder pobl-002.
"""

import pytest

from app.domains.tasks.models import BoardCardPosition

BOARD_URL = "/api/v1/tasks/board"
ORDER_URL = "/api/v1/tasks/board/order"

MANAGER_EMAIL = "marc@strategos.ad"
SCOPED_EMAIL = "jordi@strategos.ad"
OUT_OF_SCOPE_OBLIGATION = "pobl-002"  # proj-007 -> cust-005 (not jordi's)


def _column(board, status):
    """The ids of the cards in one column, in board order, with their source."""
    return [
        {"id": c["id"], "source": c["source"]}
        for c in board
        if c["status"] == status
    ]


@pytest.mark.integration
def test_manager_reorder_persists_on_board(client_as):
    """Reversing a column's order is reflected on the next board read."""
    with client_as(MANAGER_EMAIL) as client:
        board = client.get(BOARD_URL).json()
        pending = _column(board, "Pendiente")
        assert len(pending) >= 2  # need at least two cards to reorder

        reversed_order = list(reversed(pending))
        res = client.put(ORDER_URL, json={"ordered": reversed_order})
        assert res.status_code == 204

        after = _column(client.get(BOARD_URL).json(), "Pendiente")
    assert [c["id"] for c in after] == [c["id"] for c in reversed_order]


@pytest.mark.integration
def test_reorder_does_not_change_status(client_as):
    """Reordering sets position only; every card keeps its column."""
    with client_as(MANAGER_EMAIL) as client:
        board = client.get(BOARD_URL).json()
        pending = _column(board, "Pendiente")
        assert len(pending) >= 2

        client.put(ORDER_URL, json={"ordered": list(reversed(pending))})
        after = client.get(BOARD_URL).json()
    moved_ids = {c["id"] for c in pending}
    still_pending = {c["id"] for c in after if c["status"] == "Pendiente"}
    assert moved_ids <= still_pending


@pytest.mark.integration
def test_reorder_is_idempotent_single_row(client_as, db_session):
    with client_as(MANAGER_EMAIL) as client:
        board = client.get(BOARD_URL).json()
        pending = _column(board, "Pendiente")[:2]
        assert client.put(ORDER_URL, json={"ordered": pending}).status_code == 204
        assert client.put(ORDER_URL, json={"ordered": pending}).status_code == 204
    rows = (
        db_session.query(BoardCardPosition)
        .filter(BoardCardPosition.card_id == pending[0]["id"])
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
def test_scoped_user_cannot_reorder_out_of_scope_card(client_as):
    with client_as(SCOPED_EMAIL) as client:
        res = client.put(
            ORDER_URL,
            json={"ordered": [{"id": OUT_OF_SCOPE_OBLIGATION, "source": "obligation"}]},
        )
    assert res.status_code == 403


@pytest.mark.integration
def test_unknown_card_is_404(client_as):
    with client_as(MANAGER_EMAIL) as client:
        res = client.put(
            ORDER_URL, json={"ordered": [{"id": "task-nope", "source": "task"}]}
        )
    assert res.status_code == 404


@pytest.mark.integration
def test_reorder_rejects_cards_from_different_columns(client_as):
    """A payload mixing two columns is rejected (422), never silently interleaved."""
    with client_as(MANAGER_EMAIL) as client:
        board = client.get(BOARD_URL).json()
        pending = _column(board, "Pendiente")
        done = _column(board, "Hecho")
        assert pending and done
        res = client.put(ORDER_URL, json={"ordered": [pending[0], done[0]]})
    assert res.status_code == 422
