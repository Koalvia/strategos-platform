"""Tests for the optional due-date range filter on the list-tasks endpoint.

These cover the behavior added by issue #5: ``GET /tasks`` accepts optional
``due_after`` and ``due_before`` date query parameters, combines them into a
closed range, excludes tasks without a ``due_date`` when either bound is set,
and still combines with the existing ``completed`` filter.
"""

from datetime import date

import pytest

from app.domains.lists.models import List as TaskList
from app.domains.tasks.models import Task


def _seed_list_with_due_dates(db_session, user_id):
    """Create a list owned by ``user_id`` with tasks across a span of dates."""
    task_list = TaskList(name="Inbox", user_id=user_id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(title="Jan", list_id=task_list.id, due_date=date(2026, 1, 15)),
            Task(title="Feb", list_id=task_list.id, due_date=date(2026, 2, 15)),
            Task(title="Mar", list_id=task_list.id, due_date=date(2026, 3, 15)),
            Task(title="No due date", list_id=task_list.id, due_date=None),
        ]
    )
    db_session.commit()
    return task_list


@pytest.mark.integration
def test_due_after_returns_tasks_on_or_after_bound(client, db_session, test_user):
    """GET /tasks?due_after=<d> returns only tasks with due_date >= d."""
    task_list = _seed_list_with_due_dates(db_session, test_user.id)

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}&due_after=2026-02-15"
    )

    assert response.status_code == 200
    body = response.json()
    assert {task["title"] for task in body} == {"Feb", "Mar"}


@pytest.mark.integration
def test_due_before_returns_tasks_on_or_before_bound(client, db_session, test_user):
    """GET /tasks?due_before=<d> returns only tasks with due_date <= d."""
    task_list = _seed_list_with_due_dates(db_session, test_user.id)

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}&due_before=2026-02-15"
    )

    assert response.status_code == 200
    body = response.json()
    assert {task["title"] for task in body} == {"Jan", "Feb"}


@pytest.mark.integration
def test_due_after_and_before_express_closed_range(client, db_session, test_user):
    """Both bounds combine into an inclusive closed range."""
    task_list = _seed_list_with_due_dates(db_session, test_user.id)

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}"
        "&due_after=2026-02-01&due_before=2026-02-28"
    )

    assert response.status_code == 200
    body = response.json()
    assert [task["title"] for task in body] == ["Feb"]


@pytest.mark.integration
def test_null_due_date_excluded_when_bound_provided(client, db_session, test_user):
    """Tasks with a null due_date are excluded when either bound is set."""
    task_list = _seed_list_with_due_dates(db_session, test_user.id)

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}&due_after=2026-01-01"
    )

    assert response.status_code == 200
    body = response.json()
    assert "No due date" not in {task["title"] for task in body}
    assert {task["title"] for task in body} == {"Jan", "Feb", "Mar"}


@pytest.mark.integration
def test_due_date_filters_omitted_returns_all_tasks(client, db_session, test_user):
    """When both bounds are omitted, tasks with a null due_date are still returned."""
    task_list = _seed_list_with_due_dates(db_session, test_user.id)

    response = client.get(f"/api/v1/tasks?list_id={task_list.id}")

    assert response.status_code == 200
    body = response.json()
    assert {task["title"] for task in body} == {"Jan", "Feb", "Mar", "No due date"}


@pytest.mark.integration
def test_due_date_combines_with_completed_filter(client, db_session, test_user):
    """The due-date range filter combines with the existing completed filter."""
    task_list = TaskList(name="Inbox", user_id=test_user.id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)

    db_session.add_all(
        [
            Task(
                title="Feb done",
                list_id=task_list.id,
                due_date=date(2026, 2, 10),
                completed=True,
            ),
            Task(
                title="Feb pending",
                list_id=task_list.id,
                due_date=date(2026, 2, 20),
                completed=False,
            ),
            Task(
                title="Mar done",
                list_id=task_list.id,
                due_date=date(2026, 3, 10),
                completed=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/tasks?list_id={task_list.id}"
        "&due_before=2026-02-28&completed=true"
    )

    assert response.status_code == 200
    body = response.json()
    assert [task["title"] for task in body] == ["Feb done"]
