"""Business logic for the tasks (Tareas) domain.

The board mixes two sources: **BC user tasks** (read-only from Business Central)
and **obligations shown as tasks** (each project-obligation instance becomes a
movable card). Both are grouped into the four workflow columns and coloured by a
traffic light derived from their due date.

Local state lives in three small tables: ``task_notes`` (internal notes on a task),
``task_status_overrides`` (workflow column of a BC task) and
``obligation_task_states`` (workflow column of an obligation). BC is never written
back; overrides are overlaid onto the read.

Moving a card is authorized by the union rule: a manager (``sees_everything``)
moves anything; anyone else moves only cards whose project's client is in their
scope or where they are the project's technician/responsible. "Mine" maps the
local user to their BC assignee by email.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.visibility import CustomerScope, may_see_project, users_by_key
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

from .models import (
    BoardCardPosition,
    ObligationTaskState,
    TaskNote,
    TaskStatusOverride,
)
from .schemas import (
    BoardOrderItem,
    TaskAssignee,
    TaskNoteResponse,
    TaskProject,
    TaskResponse,
)


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
        :meth:`list_board_cards`. ``scope`` restricts to the caller's clients only
        (no technician/responsible union) — intentional, as callers here already
        have the project in context. The ``status`` filter runs after the override.
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
        project's client is in scope, or the caller is its technician/responsible."""
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
                self._technician_assignee(projects_by_id.get(o.project.id), by_key),
            )
            for o in obligations
        ]

        cards = task_cards + ob_cards
        # Shared vertical order: positioned cards first (by position), rest after in
        # backend order (stable sort keeps it; per-column order survives regrouping).
        positions = self._card_positions()
        cards.sort(
            key=lambda c: (0, positions[(c.source, c.id)])
            if (c.source, c.id) in positions
            else (1, 0)
        )
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
        rule (manager, client in scope, or project technician/responsible). 404 if the
        item is unknown, 403 otherwise. The override is upserted (idempotent).
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
        self._upsert(
            TaskStatusOverride,
            {"task_id": task_id},
            {"status": new_status, "updated_by": user.id},
        )

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
        self._upsert(
            ObligationTaskState,
            {"bc_obligation_id": instance_id},
            {"status": new_status, "updated_by": user.id},
        )

        # Build the card from the instance already in hand — no second obligations
        # read (avoids re-fetching the whole obligations list just to shape one card).
        return self._obligation_card_from_instance(instance, new_status)

    def reorder_board(
        self, ordered: list[BoardOrderItem], user: User, scope: CustomerScope
    ) -> None:
        """Persist the shared vertical order of a column's cards (position=index).

        All-or-nothing: caller must be able to move every card (union). 404 if a card
        is unknown, 422 if the cards span more than one column.
        """
        if not ordered:
            return
        # Resolve the BC data and lookups once (not per card).
        tasks_by_id = {t.id: t for t in self.bc_client.get_user_tasks()}
        obligations_by_id = {o.id: o for o in self.bc_client.get_project_obligations()}
        projects_by_id = {p.id: p for p in self.bc_client.get_projects()}
        by_key = self._users_by_key()
        overrides = self._status_overrides([i.id for i in ordered if i.source == "task"])
        states = self._obligation_states(
            [i.id for i in ordered if i.source == "obligation"]
        )

        columns_seen: set[TaskStatus] = set()
        for item in ordered:
            if item.source == "obligation":
                instance = obligations_by_id.get(item.id)
                project_id = instance.project_id if instance is not None else None
                column = states.get(item.id) or (
                    TaskStatus.done
                    if instance is not None and instance.submission_date is not None
                    else TaskStatus.pending
                )
            else:
                task = tasks_by_id.get(item.id)
                project_id = task.project_id if task is not None else None
                column = overrides.get(item.id, task.status) if task is not None else None
            if project_id is None:
                raise HTTPException(status_code=404, detail=f"Card {item.id} not found")
            project = projects_by_id.get(project_id)
            if project is None or not may_see_project(
                project, user.email or "", scope, by_key
            ):
                raise HTTPException(
                    status_code=403, detail="Not allowed to reorder this card"
                )
            columns_seen.add(column)

        if len(columns_seen) > 1:
            raise HTTPException(
                status_code=422,
                detail="Reorder payload mixes cards from different columns",
            )

        self._apply_positions(ordered, user.id)

    def _apply_positions(self, ordered: list[BoardOrderItem], user_id: int) -> None:
        """Upsert position=index for each card in one pass; retry once on a race."""
        for attempt in (1, 2):
            existing = {
                (r.source, r.card_id): r
                for r in self.db.query(BoardCardPosition).filter(
                    BoardCardPosition.card_id.in_([i.id for i in ordered])
                )
            }
            for index, item in enumerate(ordered):
                row = existing.get((item.source, item.id))
                if row is None:
                    self.db.add(
                        BoardCardPosition(
                            card_id=item.id,
                            source=item.source,
                            position=index,
                            updated_by=user_id,
                        )
                    )
                else:
                    row.position = index
                    row.updated_by = user_id
            try:
                self.db.commit()
                return
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise

    def _upsert(self, model, where: dict, values: dict) -> None:
        """Insert or update one row (by ``where``); retry once on a concurrent insert."""
        for attempt in (1, 2):
            row = self.db.query(model).filter_by(**where).first()
            if row is None:
                self.db.add(model(**where, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            try:
                self.db.commit()
                return
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise

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

    def _may_move(self, project_id: str, user: User, scope: CustomerScope) -> bool:
        """Union rule: manager, client in scope, or project technician/responsible."""
        if scope.sees_everything:
            return True
        project = self._get_project(project_id)
        if project is None:
            return False
        return may_see_project(project, user.email or "", scope, self._users_by_key())

    def _get_project(self, project_id: str):
        """Return the BC project with ``project_id``, or None."""
        for project in self.bc_client.get_projects():
            if project.id == project_id:
                return project
        return None

    def _obligation_card_from_instance(
        self, instance: BCProjectObligation, workflow_status: TaskStatus
    ) -> TaskResponse:
        """Shape one obligation card from the in-hand instance (no obligations re-read)."""
        ref = date.today()
        red, yellow = self._thresholds()
        project = self._get_project(instance.project_id)
        customer_id = project.customer_id if project is not None else ""
        customer_name = (
            self.bc_client.get_customer_names([customer_id]).get(customer_id, "")
            if customer_id
            else ""
        )
        obligation = next(
            (o for o in self.bc_client.get_obligations() if o.id == instance.obligation_id),
            None,
        )
        title = obligation.name if obligation is not None and obligation.name else instance.obligation_id
        return TaskResponse(
            id=instance.id,
            title=title,
            project=TaskProject(
                id=instance.project_id, name=project.name if project is not None else ""
            ),
            client=TaskProject(id=customer_id, name=customer_name),
            assignee=self._technician_assignee(project, self._users_by_key()),
            priority=None,
            status=workflow_status,
            traffic_light=derive_status(
                instance.due_date, instance.submission_date, ref, red, yellow
            ),
            due_date=instance.due_date,
            source="obligation",
        )

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

    def _card_positions(self) -> dict[tuple[str, str], int]:
        """Return ``{(source, card_id): position}`` for all manually-ordered cards."""
        rows = self.db.query(BoardCardPosition).all()
        return {(row.source, row.card_id): row.position for row in rows}

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
