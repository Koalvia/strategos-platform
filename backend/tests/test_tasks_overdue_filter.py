"""Tests for the optional overdue filter on the list-tasks endpoint.

These cover the behavior added by issue #6: ``GET /tasks`` accepts an optional
boolean ``overdue`` query parameter. When ``overdue=true``, only incomplete
tasks whose ``due_date`` is strictly before today (server date) are returned.
Tasks with a null ``due_date`` are never considered overdue, and omitting the
parameter (or passing ``false``) leaves behavior unchanged.
"""

from datetime import date, timedelta

import pytest

from app.domains.lists.models import List as TaskList
from app.domains.tasks.models import Task

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def _seed_list(db_session, user_id):
    """Create a list owned by ``user_id`` with a spread of due dates and states."""
    task_list = TaskList(name="Inbox", user_id=user_id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(
                title="Past pending",
                list_id=task_list.id,
                due_date=YESTERDAY,
                completed=False,
            ),
            Task(
                title="Past done",
                list_id=task_list.id,
                due_date=YESTERDAY,
                completed=True,
            ),
            Task(
                title="Future pending",
                list_id=task_list.id,
                due_date=TOMORROW,
                completed=False,
            ),
            Task(
                title="Today pending",
                list_id=task_list.id,
                due_date=TODAY,
                completed=False,
            ),
            Task(
                title="No due date",
                list_id=task_list.id,
                due_date=None,
                completed=False,
            ),
        ]
    )
    db_session.commit()
    return task_list


@pytest.mark.integration
def test_overdue_returns_only_past_incomplete_tasks(client, db_session, test_user):
    """overdue=true returns only incomplete tasks whose due_date is before today."""
    task_list = _seed_list(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}&overdue=true")

    assert response.status_code == 200
    body = response.json()
    assert {task["title"] for task in body} == {"Past pending"}


@pytest.mark.integration
def test_overdue_excludes_future_due_dates(client, db_session, test_user):
    """A future due_date is never overdue."""
    task_list = _seed_list(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}&overdue=true")

    assert response.status_code == 200
    titles = {task["title"] for task in response.json()}
    assert "Future pending" not in titles
    assert "Today pending" not in titles


@pytest.mark.integration
def test_overdue_excludes_completed_past_tasks(client, db_session, test_user):
    """A past-due but completed task is not overdue."""
    task_list = _seed_list(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}&overdue=true")

    assert response.status_code == 200
    titles = {task["title"] for task in response.json()}
    assert "Past done" not in titles


@pytest.mark.integration
def test_overdue_excludes_null_due_date(client, db_session, test_user):
    """A task with a null due_date is never overdue."""
    task_list = _seed_list(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}&overdue=true")

    assert response.status_code == 200
    titles = {task["title"] for task in response.json()}
    assert "No due date" not in titles


@pytest.mark.integration
def test_overdue_false_leaves_behavior_unchanged(client, db_session, test_user):
    """overdue=false returns every task, just like omitting the parameter."""
    task_list = _seed_list(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}&overdue=false")

    assert response.status_code == 200
    assert {task["title"] for task in response.json()} == {
        "Past pending",
        "Past done",
        "Future pending",
        "Today pending",
        "No due date",
    }


@pytest.mark.integration
def test_overdue_omitted_returns_all_tasks(client, db_session, test_user):
    """Omitting the overdue parameter leaves behavior unchanged."""
    task_list = _seed_list(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}")

    assert response.status_code == 200
    assert {task["title"] for task in response.json()} == {
        "Past pending",
        "Past done",
        "Future pending",
        "Today pending",
        "No due date",
    }


@pytest.mark.integration
def test_overdue_combines_with_priority_filter(client, db_session, test_user):
    """The overdue filter combines with the existing priority filter."""
    from app.domains.tasks.schemas import PriorityEnum

    task_list = TaskList(name="Inbox", user_id=test_user.id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(
                title="Overdue high",
                list_id=task_list.id,
                due_date=YESTERDAY,
                completed=False,
                priority=PriorityEnum.high,
            ),
            Task(
                title="Overdue low",
                list_id=task_list.id,
                due_date=YESTERDAY,
                completed=False,
                priority=PriorityEnum.low,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}&overdue=true&priority=high"
    )

    assert response.status_code == 200
    assert [task["title"] for task in response.json()] == ["Overdue high"]
