"""Tests for the optional priority filter on the list-tasks endpoint.

These cover the behavior added by issue #1: ``GET /tasks`` accepts an optional
``priority`` query parameter, combines it with the existing ``completed``
filter, and still enforces list ownership.
"""

import pytest

from app.domains.lists.models import List as TaskList
from app.domains.tasks.models import Task
from app.domains.tasks.schemas import PriorityEnum


def _seed_list_with_tasks(db_session, user_id):
    """Create a list owned by ``user_id`` with one task per priority."""
    task_list = TaskList(name="Inbox", user_id=user_id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(title="High task", list_id=task_list.id, priority=PriorityEnum.high),
            Task(title="Medium task", list_id=task_list.id, priority=PriorityEnum.medium),
            Task(title="Low task", list_id=task_list.id, priority=PriorityEnum.low),
        ]
    )
    db_session.commit()
    return task_list


@pytest.mark.integration
@pytest.mark.parametrize(
    "priority, expected_title",
    [("high", "High task"), ("medium", "Medium task"), ("low", "Low task")],
)
def test_priority_filter_returns_only_matching_tasks(
    client, db_session, test_user, priority, expected_title
):
    """GET /tasks?priority=<p> returns only that list's tasks with priority <p>."""
    task_list = _seed_list_with_tasks(db_session, test_user.id)

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}&priority={priority}"
    )

    assert response.status_code == 200
    body = response.json()
    assert [task["title"] for task in body] == [expected_title]
    assert all(task["priority"] == priority for task in body)


@pytest.mark.integration
def test_priority_omitted_returns_all_tasks(client, db_session, test_user):
    """When priority is omitted, all tasks of the list are returned."""
    task_list = _seed_list_with_tasks(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}")

    assert response.status_code == 200
    body = response.json()
    assert {task["title"] for task in body} == {
        "High task",
        "Medium task",
        "Low task",
    }


@pytest.mark.integration
def test_priority_combines_with_completed_filter(client, db_session, test_user):
    """The priority filter combines with the existing completed filter."""
    task_list = TaskList(name="Inbox", user_id=test_user.id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(
                title="High done",
                list_id=task_list.id,
                priority=PriorityEnum.high,
                completed=True,
            ),
            Task(
                title="High pending",
                list_id=task_list.id,
                priority=PriorityEnum.high,
                completed=False,
            ),
            Task(
                title="Low done",
                list_id=task_list.id,
                priority=PriorityEnum.low,
                completed=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}&priority=high&completed=true"
    )

    assert response.status_code == 200
    body = response.json()
    assert [task["title"] for task in body] == ["High done"]


@pytest.mark.auth
def test_priority_filter_still_enforces_ownership(client, db_session, test_user):
    """A user cannot read another user's tasks even with a priority filter."""
    from app.domains.auth.models import User

    other_user = User(
        name="Other User",
        email="other@example.com",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    foreign_list = _seed_list_with_tasks(db_session, other_user.id)

    response = client.get(
        f"/api/v1/tasks?list_id={foreign_list.id}&priority=high"
    )

    assert response.status_code == 404
