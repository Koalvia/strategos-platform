"""Business logic for the tasks (Tareas) domain.

The board mixes two sources: **BC user tasks** (read from Business Central) and
**obligations shown as tasks** (each project-obligation instance becomes a card).
Both are grouped into the four workflow columns and coloured by a traffic light
derived from their due date.

The workflow column is **not persisted**: a BC task shows its BC status and an
obligation its derived column (filed -> Hecho, else Pendiente). Moving a card is a
client-only interaction that survives only in the browser — BC is never written
and there is no local override store, pending BC becoming writable/readable for
``userTasks``.

Local state is limited to ``task_notes`` (internal notes on a task). Visibility of
a card follows **customer scope** plus the project's technician: a manager sees
everything; anyone else sees a card only if its project's client is in their scope
or they are the project's technician. "Mine" maps the local user to their BC
assignee by email.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.visibility import CustomerScope, may_see_project, users_by_key
from app.domains.auth.models import User
from app.domains.obligations.schemas import ProjectObligationResponse
from app.domains.obligations.service import ObligationsService, derive_status
from app.domains.settings.service import SettingsService
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import BCUserTask, TaskStatus

from .models import TaskNote
from .schemas import TaskAssignee, TaskNoteResponse, TaskProject, TaskResponse


class TasksService:
    """Serve the board (BC tasks + obligations) plus each task's local notes."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    # ----------------------------------------------------------------- reads

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        project_id: str | None = None,
        assignee_id: str | None = None,
        scope: CustomerScope | None = None,
    ) -> list[TaskResponse]:
        """Return the BC user tasks (no obligations), optionally filtered.

        Used by "mis tareas" and the dashboard; the board uses
        :meth:`list_board_cards`. ``scope`` restricts to the caller's clients only
        (no technician/responsible union) — intentional, as callers here already
        have the project in context.
        """
        tasks = self.bc_client.get_user_tasks()
        if project_id is not None:
            tasks = [t for t in tasks if t.project_id == project_id]
        if assignee_id is not None:
            tasks = [t for t in tasks if t.assignee_id == assignee_id]

        projects_by_id = {p.id: p for p in self.bc_client.get_projects()}
        if scope is not None and not scope.sees_everything:
            tasks = [
                t for t in tasks
                if (project := projects_by_id.get(t.project_id)) is not None
                and scope.sees(project.customer_id)
            ]

        ref = date.today()
        red, yellow = self._thresholds()
        project_names = {pid: p.name for pid, p in projects_by_id.items()}
        user_names = {u.id: u.name for u in self.bc_client.get_users()}
        responses = [
            self._task_card(t, project_names, user_names, ref, red, yellow)
            for t in tasks
        ]

        if status is not None:
            responses = [r for r in responses if r.status is status]
        return responses

    def list_board_cards(
        self, user: User, scope: CustomerScope, status: TaskStatus | None = None
    ) -> list[TaskResponse]:
        """Return the board (BC tasks + obligations). Visible if manager, or the
        project's client is in scope, or the caller is the project's technician."""
        ref = date.today()
        red, yellow = self._thresholds()
        projects_by_id = {p.id: p for p in self.bc_client.get_projects()}
        by_key = self._users_by_key()
        my_email = (user.email or "").casefold()

        def visible(project_id: str) -> bool:
            # Union rule: manager, client in scope, or project technician/responsible.
            if scope.sees_everything:
                return True
            project = projects_by_id.get(project_id)
            if project is None:
                return False
            return may_see_project(project, my_email, scope, by_key)

        tasks = [t for t in self.bc_client.get_user_tasks() if visible(t.project_id)]
        project_names = {pid: p.name for pid, p in projects_by_id.items()}
        user_names = {u.id: u.name for u in self.bc_client.get_users()}
        task_cards = [
            self._task_card(t, project_names, user_names, ref, red, yellow)
            for t in tasks
        ]

        obligations = ObligationsService(
            self.db, self.bc_client
        ).list_project_obligations(reference_date=ref, scope=None)
        obligations = [o for o in obligations if visible(o.project.id)]
        ob_cards = [
            self._obligation_card(
                o,
                self._initial_status(o),
                self._technician_assignee(projects_by_id.get(o.project.id), by_key),
            )
            for o in obligations
        ]

        cards = task_cards + ob_cards
        if status is not None:
            cards = [c for c in cards if c.status is status]
        return cards

    def list_my_tasks(
        self, user: User, status: TaskStatus | None = None
    ) -> list[TaskResponse]:
        """Return the current user's BC tasks, mapped by email (obligations excluded)."""
        bc_user_id = self._bc_user_id_for(user)
        if bc_user_id is None:
            return []
        return self.list_tasks(status=status, assignee_id=bc_user_id)

    # ---------------------------------------------------------------- notes

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

    # -------------------------------------------------------------- helpers

    def _thresholds(self) -> tuple[int, int]:
        """Return ``(red_within_days, yellow_within_days)`` from the settings store."""
        settings = SettingsService(self.db).get_traffic_light()
        return settings.red_within_days, settings.yellow_within_days

    def _users_by_key(self) -> dict:
        """Map each BC user's code and name (casefolded) to the user, for lookups."""
        return users_by_key(self.bc_client.get_users())

    def _technician_assignee(self, project, users_by_key: dict) -> TaskAssignee | None:
        """The project's technician as an assignee ref, or None if unresolved."""
        if project is None or not project.technician:
            return None
        bc_user = users_by_key.get(project.technician.casefold())
        if bc_user is None:
            return None
        return TaskAssignee(id=bc_user.id, name=bc_user.name)

    def _bc_user_id_for(self, user: User) -> str | None:
        """Resolve the BC user id for a local user by matching email."""
        email = (user.email or "").casefold()
        for bc_user in self.bc_client.get_users():
            if bc_user.email.casefold() == email:
                return bc_user.id
        return None

    def _get_task(self, task_id: str) -> BCUserTask:
        """Return the BC task with ``task_id``, or raise 404 if unknown."""
        for task in self.bc_client.get_user_tasks():
            if task.id == task_id:
                return task
        raise HTTPException(status_code=404, detail="Task not found")

    def _require_task(self, task_id: str) -> None:
        """Raise 404 unless ``task_id`` names a task known to BC."""
        self._get_task(task_id)

    @staticmethod
    def _initial_status(obligation: ProjectObligationResponse) -> TaskStatus:
        """Derive an obligation's column: filed -> Hecho, else Pendiente."""
        if obligation.submission_date is not None:
            return TaskStatus.done
        return TaskStatus.pending

    @staticmethod
    def _task_card(
        task: BCUserTask,
        project_names: dict[str, str],
        user_names: dict[str, str],
        reference_date: date,
        red_within_days: int,
        yellow_within_days: int,
    ) -> TaskResponse:
        """Map a BC user task to a board card (BC status + traffic light)."""
        return TaskResponse(
            id=task.id,
            title=task.title,
            project=TaskProject(
                id=task.project_id, name=project_names.get(task.project_id, "")
            ),
            assignee=TaskAssignee(
                id=task.assignee_id, name=user_names.get(task.assignee_id, "")
            ),
            priority=task.priority,
            status=task.status,
            traffic_light=derive_status(
                task.due_date, None, reference_date, red_within_days, yellow_within_days
            ),
            due_date=task.due_date,
            source="task",
        )

    @staticmethod
    def _obligation_card(
        obligation: ProjectObligationResponse,
        workflow_status: TaskStatus,
        technician: TaskAssignee | None = None,
    ) -> TaskResponse:
        """Map an obligation to a board card; assignee is the project's technician."""
        return TaskResponse(
            id=obligation.id,
            title=obligation.obligation.name or obligation.obligation.code or obligation.id,
            project=TaskProject(id=obligation.project.id, name=obligation.project.name),
            client=TaskProject(id=obligation.client.id, name=obligation.client.name),
            assignee=technician,
            priority=None,
            status=workflow_status,
            traffic_light=obligation.status,
            due_date=obligation.due_date,
            source="obligation",
        )
