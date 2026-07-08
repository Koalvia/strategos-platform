"""Tests for the tasks domain's one local table: ``task_notes`` (issue #10).

Tasks live in Business Central, but internal notes on a task are platform-native
and stored locally. These tests exercise the note create + read round-trip
through the API and directly against the model, plus the guards (empty body
rejected, notes on an unknown BC task 404).
"""

import pytest

from app.domains.tasks.models import TaskNote

NOTES_URL = "/api/v1/tasks/task-001/notes"


@pytest.mark.integration
def test_note_create_and_read_round_trip(client):
    """POST a note, then GET it back with the same body and author."""
    resp = client.post(NOTES_URL, json={"body": "Pendent de rebre model del client"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["task_id"] == "task-001"
    assert created["body"] == "Pendent de rebre model del client"
    assert created["author_id"] is not None
    assert "created_at" in created

    resp = client.get(NOTES_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == created["id"]
    assert body[0]["body"] == "Pendent de rebre model del client"


@pytest.mark.integration
def test_notes_listed_oldest_first(client):
    """Multiple notes on a task come back oldest first."""
    client.post(NOTES_URL, json={"body": "first"})
    client.post(NOTES_URL, json={"body": "second"})
    resp = client.get(NOTES_URL)
    assert resp.status_code == 200
    assert [n["body"] for n in resp.json()] == ["first", "second"]


@pytest.mark.integration
def test_notes_scoped_to_their_task(client):
    """A note on one task does not appear under another task."""
    client.post(NOTES_URL, json={"body": "for task-001"})
    resp = client.get("/api/v1/tasks/task-002/notes")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_empty_note_body_rejected(client):
    """An empty note body is rejected by validation (422)."""
    resp = client.post(NOTES_URL, json={"body": ""})
    assert resp.status_code == 422


@pytest.mark.integration
def test_note_on_unknown_task_is_404(client):
    """Adding or listing notes on a task BC does not know is a 404."""
    assert client.post("/api/v1/tasks/nope/notes", json={"body": "x"}).status_code == 404
    assert client.get("/api/v1/tasks/nope/notes").status_code == 404


@pytest.mark.unit
def test_task_note_model_persists(db_session, test_user):
    """The TaskNote model round-trips directly against the database."""
    note = TaskNote(task_id="task-005", author_id=test_user.id, body="hola")
    db_session.add(note)
    db_session.commit()
    db_session.refresh(note)

    stored = db_session.query(TaskNote).filter(TaskNote.task_id == "task-005").one()
    assert stored.id == note.id
    assert stored.author_id == test_user.id
    assert stored.body == "hola"
    assert stored.created_at is not None
