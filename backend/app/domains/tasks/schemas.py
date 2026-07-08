"""Pydantic v2 schemas for the tasks (Tareas) domain.

The task shapes exposed to the frontend are mapped from the Business Central
transport DTO
(:class:`~app.integrations.business_central.models.BCUserTask`) in the service —
there are **no** local columns for title / project / assignee / due date /
priority / status. Field names and the priority / status vocabulary mirror the
task cards in ``tareas.png`` (title, project subtitle, priority badge, due date,
assignee).

The only locally-owned data is the internal note (``task_notes`` table), modelled
by :class:`TaskNoteCreate` / :class:`TaskNoteResponse`.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.business_central.models import TaskPriority, TaskStatus


class TaskProject(BaseModel):
    """The project a task belongs to (id + display name)."""

    id: str
    name: str


class TaskAssignee(BaseModel):
    """The user a task is assigned to (id + display name)."""

    id: str
    name: str


class TaskResponse(BaseModel):
    """A task as shown on the Tareas board, sourced read-only from BC.

    Mirrors a card in ``tareas.png``: title, the project it belongs to, a
    priority badge (Alta / Media / Baja), a due date, the assignee, and the board
    column the card sits in (``status``: Pendiente / En curso / Hecho).
    """

    id: str
    title: str
    project: TaskProject
    assignee: TaskAssignee
    priority: TaskPriority
    status: TaskStatus
    due_date: date


class TaskNoteCreate(BaseModel):
    """Request body to add an internal note to a task."""

    body: str = Field(min_length=1)


class TaskNoteResponse(BaseModel):
    """An internal note left on a task (platform-native, stored locally)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    author_id: int
    body: str
    created_at: datetime
