"""Smoke tests proving the test harness boots and wires app + auth + DB.

These intentionally cover only existing behavior (health check, listing a
list's tasks, ownership enforcement). Filter-specific tests belong with the
feature that adds them.
"""

import pytest

from app.domains.auth.models import User
from app.domains.lists.models import List as TaskList
from app.domains.tasks.models import Task
from app.domains.tasks.schemas import PriorityEnum


def test_health_ok(client):
    """The app boots and the public health endpoint responds without an API key."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.integration
def test_list_tasks_returns_owned_tasks(client, db_session, test_user):
    """GET /tasks returns the tasks of a list owned by the current user."""
    task_list = TaskList(name="Inbox", user_id=test_user.id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(title="Write report", list_id=task_list.id, priority=PriorityEnum.high),
            Task(title="Read email", list_id=task_list.id, priority=PriorityEnum.low),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}")

    assert response.status_code == 200
    body = response.json()
    assert {task["title"] for task in body} == {"Write report", "Read email"}


@pytest.mark.auth
def test_list_tasks_rejects_other_users_list(client, db_session, test_user):
    """A user cannot read the tasks of a list they do not own."""
    other_user = User(
        name="Other User",
        email="other@example.com",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    foreign_list = TaskList(name="Private", user_id=other_user.id)
    db_session.add(foreign_list)
    db_session.commit()
    db_session.refresh(foreign_list)

    response = client.get(f"/api/v1/tasks?list_id={foreign_list.id}")

    assert response.status_code == 404
