"""Tests for the recurrence columns added to the Task model (issue #9).

These cover only the data model added in this round: every task defaults to
``RecurrenceEnum.none`` recurrence, ``parent_task_id`` is nullable, and it can
point at another task to mark a generated occurrence. No API or generation
behavior exists yet.
"""

import pytest

from app.domains.lists.models import List as TaskList
from app.domains.tasks.models import RecurrenceEnum, Task


def _seed_list(db_session, user_id):
    task_list = TaskList(name="Inbox", user_id=user_id)
    db_session.add(task_list)
    db_session.commit()
    db_session.refresh(task_list)
    return task_list


@pytest.mark.unit
def test_recurrence_defaults_to_none(db_session, test_user):
    """A task created without a recurrence defaults to ``none``."""
    task_list = _seed_list(db_session, test_user.id)

    task = Task(title="Plain task", list_id=task_list.id)
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    assert task.recurrence == RecurrenceEnum.none
    assert task.parent_task_id is None


@pytest.mark.unit
def test_parent_task_id_links_an_occurrence(db_session, test_user):
    """``parent_task_id`` accepts None and a valid parent task id."""
    task_list = _seed_list(db_session, test_user.id)

    parent = Task(
        title="Weekly standup",
        list_id=task_list.id,
        recurrence=RecurrenceEnum.weekly,
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    occurrence = Task(
        title="Weekly standup",
        list_id=task_list.id,
        parent_task_id=parent.id,
    )
    db_session.add(occurrence)
    db_session.commit()
    db_session.refresh(occurrence)

    assert occurrence.parent_task_id == parent.id
    assert occurrence.parent_task is parent
    assert occurrence in parent.occurrences
