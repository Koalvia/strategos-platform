"""Business logic for the tasks (Tareas) domain.

The service reads tasks read-only from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
(never from fixtures directly), maps the ``BCUserTask`` transport DTOs to
:class:`~app.domains.tasks.schemas.TaskResponse`, and resolves each task's
project and assignee display names from the BC project / user directories.

It also owns the domain's one local table (``task_notes``): the platform-native
internal notes staff leave on a task. Tasks are not written back to BC — BC is
the system of record — so the only writes here are notes.

"Mine" (the dashboard "Mis tareas de hoy" widget) maps the logged-in local user
to their BC assignee by **email**: the local ``User.email`` is matched against
the BC user directory. A local user with no matching BC user simply has no tasks.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domains.auth.models import User
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCUserTask,
    TaskStatus,
)

from .models import TaskNote
from .schemas import TaskAssignee, TaskNoteResponse, TaskProject, TaskResponse


class TasksService:
    """Serve the firm's tasks from Business Central plus their local notes."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        assignee_id: str | None = None,
    ) -> list[TaskResponse]:
        """Return all tasks across the firm, optionally filtered.

        ``status`` keeps only tasks in that board column; ``project_id`` and
        ``assignee_id`` restrict to a single project / assignee. Filters compose
        (all supplied filters must match). Results preserve BC order so the
        frontend can group them by status into the board columns.
        """
        tasks = self.bc_client.get_user_tasks()

        if status is not None:
            tasks = [t for t in tasks if t.status is status]
        if project_id is not None:
            tasks = [t for t in tasks if t.project_id == project_id]
        if assignee_id is not None:
            tasks = [t for t in tasks if t.assignee_id == assignee_id]

        project_names = {p.id: p.name for p in self.bc_client.get_projects()}
        user_names = {u.id: u.name for u in self.bc_client.get_users()}
        return [self._to_response(t, project_names, user_names) for t in tasks]

    def list_my_tasks(
        self, user: User, status: TaskStatus | None = None
    ) -> list[TaskResponse]:
        """Return the current user's tasks (for "Mis tareas de hoy").

        The local user is mapped to their BC assignee by email. If no BC user
        matches, the user has no tasks.
        """
        bc_user_id = self._bc_user_id_for(user)
        if bc_user_id is None:
            return []
        return self.list_tasks(status=status, assignee_id=bc_user_id)

    def add_note(self, task_id: str, author: User, body: str) -> TaskNoteResponse:
        """Add an internal note to a task (404 if the BC task is unknown)."""
        self._require_task(task_id)
        note = TaskNote(task_id=task_id, author_id=author.id, body=body)
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return TaskNoteResponse.model_validate(note)

    def list_notes(self, task_id: str) -> list[TaskNoteResponse]:
        """Return a task's internal notes, oldest first (404 if unknown)."""
        self._require_task(task_id)
        notes = (
            self.db.query(TaskNote)
            .filter(TaskNote.task_id == task_id)
            .order_by(TaskNote.created_at.asc(), TaskNote.id.asc())
            .all()
        )
        return [TaskNoteResponse.model_validate(n) for n in notes]

    def _bc_user_id_for(self, user: User) -> str | None:
        """Resolve the BC user id for a local user by matching email."""
        email = (user.email or "").casefold()
        for bc_user in self.bc_client.get_users():
            if bc_user.email.casefold() == email:
                return bc_user.id
        return None

    def _require_task(self, task_id: str) -> None:
        """Raise 404 unless ``task_id`` names a task known to BC."""
        if not any(t.id == task_id for t in self.bc_client.get_user_tasks()):
            raise HTTPException(status_code=404, detail="Task not found")

    @staticmethod
    def _to_response(
        task: BCUserTask,
        project_names: dict[str, str],
        user_names: dict[str, str],
    ) -> TaskResponse:
        """Map a Business Central user-task DTO to the API response shape."""
        return TaskResponse(
            id=task.id,
            title=task.title,
            project=TaskProject(
                id=task.project_id,
                name=project_names.get(task.project_id, ""),
            ),
            assignee=TaskAssignee(
                id=task.assignee_id,
                name=user_names.get(task.assignee_id, ""),
            ),
            priority=task.priority,
            status=task.status,
            due_date=task.due_date,
        )
