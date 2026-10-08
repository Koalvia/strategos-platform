"""Tests for archiving board cards (status 'Archivada').

Archiving goes through the same PATCH /tasks/{id}/status path as any move. An
archived card is hidden from the board (and from GET /tasks) by default and shown
only with ?status=Archivada; un-archiving moves it back to a chosen column.
Actors from the mock fixtures via the real scope resolver (marc@ = manager).
"""

import pytest

MANAGER_EMAIL = "marc@strategos.ad"
BOARD_URL = "/api/v1/tasks/board"
TASKS_URL = "/api/v1/tasks"
ARCHIVED = "Archivada"

TASK_ID = "task-001"  # proj-001
OBLIGATION_ID = "pobl-001"


def _ids(cards, source=None):
    return {c["id"] for c in cards if source is None or c["source"] == source}


def _archive(client, item_id, source):
    return client.patch(
        f"{TASKS_URL}/{item_id}/status",
        json={"status": ARCHIVED, "source": source},
    )


@pytest.mark.integration
def test_archive_task_hidden_from_board_and_shown_in_filter(client_as):
    with client_as(MANAGER_EMAIL) as client:
        assert TASK_ID in _ids(client.get(BOARD_URL).json())  # present first

        assert _archive(client, TASK_ID, "task").status_code == 200

        board = client.get(BOARD_URL).json()
        assert TASK_ID not in _ids(board)  # hidden from the default board

        archived = client.get(BOARD_URL, params={"status": ARCHIVED}).json()
        assert TASK_ID in _ids(archived)  # visible under the Archivadas filter
        assert all(c["status"] == ARCHIVED for c in archived)


@pytest.mark.integration
def test_unarchive_task_returns_to_chosen_column(client_as):
    with client_as(MANAGER_EMAIL) as client:
        _archive(client, TASK_ID, "task")
        res = client.patch(
            f"{TASKS_URL}/{TASK_ID}/status",
            json={"status": "En curso", "source": "task"},
        )
        assert res.status_code == 200

        board = {c["id"]: c for c in client.get(BOARD_URL).json()}
        assert board[TASK_ID]["status"] == "En curso"
        archived = client.get(BOARD_URL, params={"status": ARCHIVED}).json()
        assert TASK_ID not in _ids(archived)


@pytest.mark.integration
def test_archive_obligation_hidden_from_board_and_shown_in_filter(client_as):
    with client_as(MANAGER_EMAIL) as client:
        assert OBLIGATION_ID in _ids(client.get(BOARD_URL).json(), source="obligation")

        assert _archive(client, OBLIGATION_ID, "obligation").status_code == 200

        assert OBLIGATION_ID not in _ids(client.get(BOARD_URL).json())
        archived = client.get(BOARD_URL, params={"status": ARCHIVED}).json()
        assert OBLIGATION_ID in _ids(archived)


@pytest.mark.integration
def test_archived_task_excluded_from_list_tasks(client_as):
    with client_as(MANAGER_EMAIL) as client:
        _archive(client, TASK_ID, "task")
        assert TASK_ID not in _ids(client.get(TASKS_URL).json())
        assert TASK_ID in _ids(client.get(TASKS_URL, params={"status": ARCHIVED}).json())
