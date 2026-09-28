"""Business logic for the tasks (Tareas) domain.

The board mixes two sources: **BC user tasks** (read-only from Business Central)
and **obligations shown as tasks** (each project-obligation instance becomes a
movable card). Both are grouped into the four workflow columns and coloured by a
traffic light derived from their due date.

Local state lives in three small tables: ``task_notes`` (internal notes on a task),
``task_status_overrides`` (workflow column of a BC task) and
``obligation_task_states`` (workflow column of an obligation). BC is never written
back; overrides are overlaid onto the read.

Moving a card is authorized by **customer scope**: a manager (``sees_everything``)
moves anything; anyone else moves only cards whose project belongs to a client in
their scope. "Mine" maps the local user to their BC assignee by email.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.visibility import CustomerScope
from app.domains.auth.models import User
from app.domains.obligations.schemas import ProjectObligationResponse
from app.domains.obligations.service import ObligationsService, derive_status
from app.domains.settings.service import SettingsService
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCProjectObligation,
    BCUserTask,
    TaskStatus,
)

from .models import ObligationTaskState, TaskNote, TaskStatusOverride
from .schemas import TaskAssignee, TaskNoteResponse, TaskProject, TaskResponse


class TasksService:
    """Serve the board (BC tasks + obligations) plus each item's local state."""

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
        :meth:`list_board_cards`. ``scope`` restricts to the caller's clients; the
        ``status`` filter runs after the workflow override is applied.
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
        overrides = self._status_overrides([t.id for t in tasks])
        project_names = {pid: p.name for pid, p in projects_by_id.items()}
        user_names = {u.id: u.name for u in self.bc_client.get_users()}
        responses = [
            self._task_card(t, project_names, user_names, overrides, ref, red, yellow)
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
        users_by_key = self._users_by_key()
        my_email = (user.email or "").casefold()
        my_projects = {
            pid
            for pid, project in projects_by_id.items()
            if self._technician_email(project, users_by_key) == my_email
        }

        def visible(project_id: str) -> bool:
            if scope.sees_everything:
                return True
            project = projects_by_id.get(project_id)
            if project is not None and scope.sees(project.customer_id):
                return True
            return project_id in my_projects

        tasks = [t for t in self.bc_client.get_user_tasks() if visible(t.project_id)]
        overrides = self._status_overrides([t.id for t in tasks])
        project_names = {pid: p.name for pid, p in projects_by_id.items()}
        user_names = {u.id: u.name for u in self.bc_client.get_users()}
        task_cards = [
            self._task_card(t, project_names, user_names, overrides, ref, red, yellow)
            for t in tasks
        ]

        obligations = ObligationsService(
            self.db, self.bc_client
        ).list_project_obligations(reference_date=ref, scope=None)
        obligations = [o for o in obligations if visible(o.project.id)]
        states = self._obligation_states([o.id for o in obligations])
        ob_cards = [
            self._obligation_card(
                o,
                states.get(o.id) or self._initial_status(o),
                self._technician_assignee(projects_by_id.get(o.project.id), users_by_key),
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

    # ---------------------------------------------------------------- writes

    def set_status(
        self,
        item_id: str,
        new_status: TaskStatus,
        source: str,
        user: User,
        scope: CustomerScope,
    ) -> TaskResponse:
        """Move a board card to a new workflow column, persisted platform-native.

        ``source`` selects the store (BC task vs obligation). Authorized by the union
        rule (manager, client in scope, or project technician). 404 if the item is
        unknown, 403 otherwise. The override is upserted (idempotent).
        """
        if source == "obligation":
            return self._set_obligation_status(item_id, new_status, user, scope)
        return self._set_task_status(item_id, new_status, user, scope)

    def _set_task_status(
        self, task_id: str, new_status: TaskStatus, user: User, scope: CustomerScope
    ) -> TaskResponse:
        task = self._get_task(task_id)
        if not self._may_move(task.project_id, user, scope):
            raise HTTPException(
                status_code=403, detail="Not allowed to change this task's status"
            )
        row = (
            self.db.query(TaskStatusOverride)
            .filter(TaskStatusOverride.task_id == task_id)
            .first()
        )
        if row is None:
            self.db.add(
                TaskStatusOverride(
                    task_id=task_id, status=new_status, updated_by=user.id
                )
            )
        else:
            row.status = new_status
            row.updated_by = user.id
        self.db.commit()

        ref = date.today()
        red, yellow = self._thresholds()
        project_names = {p.id: p.name for p in self.bc_client.get_projects()}
        user_names = {u.id: u.name for u in self.bc_client.get_users()}
        return self._task_card(
            task, project_names, user_names, {task_id: new_status}, ref, red, yellow
        )

    def _set_obligation_status(
        self, instance_id: str, new_status: TaskStatus, user: User, scope: CustomerScope
    ) -> TaskResponse:
        instance = self._get_obligation(instance_id)
        if not self._may_move(instance.project_id, user, scope):
            raise HTTPException(
                status_code=403, detail="Not allowed to change this obligation"
            )
        row = (
            self.db.query(ObligationTaskState)
            .filter(ObligationTaskState.bc_obligation_id == instance_id)
            .first()
        )
        if row is None:
            self.db.add(
                ObligationTaskState(
                    bc_obligation_id=instance_id, status=new_status, updated_by=user.id
                )
            )
        else:
            row.status = new_status
            row.updated_by = user.id
        self.db.commit()

        obligation = self._obligation_response(instance_id)
        technician = self._technician_assignee(
            self._get_project(instance.project_id), self._users_by_key()
        )
        return self._obligation_card(obligation, new_status, technician)

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

    def _users_by_key(self) -> dict[str, "object"]:
        """Map each BC user's code and name (casefolded) to the user, for lookups."""
        users_by_key: dict[str, object] = {}
        for bc_user in self.bc_client.get_users():
            if bc_user.user_name:
                users_by_key.setdefault(bc_user.user_name.casefold(), bc_user)
            if bc_user.name:
                users_by_key.setdefault(bc_user.name.casefold(), bc_user)
        return users_by_key

    @staticmethod
    def _technician_email(project, users_by_key: dict) -> str:
        """The email of a project's technician (projectManager code/name), or ''."""
        if project is None or not project.technician:
            return ""
        bc_user = users_by_key.get(project.technician.casefold())
        return (bc_user.email or "").casefold() if bc_user is not None else ""

    def _technician_assignee(self, project, users_by_key: dict) -> TaskAssignee | None:
        """The project's technician as an assignee ref, or None if unresolved."""
        if project is None or not project.technician:
            return None
        bc_user = users_by_key.get(project.technician.casefold())
        if bc_user is None:
            return None
        return TaskAssignee(id=bc_user.id, name=bc_user.name)

    def _may_move(self, project_id: str, user: User, scope: CustomerScope) -> bool:
        """Union rule: manager, client of the project in scope, or its technician."""
        if scope.sees_everything:
            return True
        project = self._get_project(project_id)
        if project is not None and scope.sees(project.customer_id):
            return True
        my_email = (user.email or "").casefold()
        return bool(my_email) and self._technician_email(
            project, self._users_by_key()
        ) == my_email

    def _get_project(self, project_id: str):
        """Return the BC project with ``project_id``, or None."""
        for project in self.bc_client.get_projects():
            if project.id == project_id:
                return project
        return None

    def _obligation_response(self, instance_id: str) -> ProjectObligationResponse:
        """Re-read one obligation (unscoped) to shape its card after a status change."""
        obligations = ObligationsService(
            self.db, self.bc_client
        ).list_project_obligations(reference_date=date.today(), scope=None)
        for obligation in obligations:
            if obligation.id == instance_id:
                return obligation
        raise HTTPException(status_code=404, detail="Obligation not found")

    def _bc_user_id_for(self, user: User) -> str | None:
        """Resolve the BC user id for a local user by matching email."""
        email = (user.email or "").casefold()
        for bc_user in self.bc_client.get_users():
            if bc_user.email.casefold() == email:
                return bc_user.id
        return None

    def _status_overrides(self, task_ids: list[str]) -> dict[str, TaskStatus]:
        """Return ``{task_id: status}`` for BC tasks that have a workflow override."""
        if not task_ids:
            return {}
        rows = (
            self.db.query(TaskStatusOverride)
            .filter(TaskStatusOverride.task_id.in_(task_ids))
            .all()
        )
        return {row.task_id: row.status for row in rows}

    def _obligation_states(self, ids: list[str]) -> dict[str, TaskStatus]:
        """Return ``{obligation_id: status}`` for obligations with a workflow override."""
        if not ids:
            return {}
        rows = (
            self.db.query(ObligationTaskState)
            .filter(ObligationTaskState.bc_obligation_id.in_(ids))
            .all()
        )
        return {row.bc_obligation_id: row.status for row in rows}

    def _get_task(self, task_id: str) -> BCUserTask:
        """Return the BC task with ``task_id``, or raise 404 if unknown."""
        for task in self.bc_client.get_user_tasks():
            if task.id == task_id:
                return task
        raise HTTPException(status_code=404, detail="Task not found")

    def _get_obligation(self, instance_id: str) -> BCProjectObligation:
        """Return the obligation instance with ``instance_id``, or raise 404."""
        for instance in self.bc_client.get_project_obligations():
            if instance.id == instance_id:
                return instance
        raise HTTPException(status_code=404, detail="Obligation not found")

    def _require_task(self, task_id: str) -> None:
        """Raise 404 unless ``task_id`` names a task known to BC."""
        self._get_task(task_id)

    @staticmethod
    def _initial_status(obligation: ProjectObligationResponse) -> TaskStatus:
        """Derive an obligation's starting column: filed -> Hecho, else Pendiente."""
        if obligation.submission_date is not None:
            return TaskStatus.done
        return TaskStatus.pending

    @staticmethod
    def _task_card(
        task: BCUserTask,
        project_names: dict[str, str],
        user_names: dict[str, str],
        overrides: dict[str, TaskStatus],
        reference_date: date,
        red_within_days: int,
        yellow_within_days: int,
    ) -> TaskResponse:
        """Map a BC user task to a board card (workflow override + traffic light)."""
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
            status=overrides.get(task.id, task.status),
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
