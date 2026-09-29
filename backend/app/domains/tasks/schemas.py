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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.obligations.schemas import DerivedObligationStatus
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
    """A card on the Tareas board — a BC task or an obligation shown as a task.

    ``status`` is the platform-owned workflow column (Pendiente/En curso/Esperando/
    Hecho). ``traffic_light`` is the colour derived from ``due_date`` (green/yellow/
    red/orange). ``source`` says whether it is a BC user task or an obligation.
    Obligations carry a ``client`` and have no ``assignee``/``priority``.
    """

    id: str
    title: str
    project: TaskProject
    client: TaskProject | None = None
    assignee: TaskAssignee | None = None
    priority: TaskPriority | None = None
    status: TaskStatus
    traffic_light: DerivedObligationStatus | None = None
    due_date: date | None = None
    source: Literal["task", "obligation"] = "task"


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
