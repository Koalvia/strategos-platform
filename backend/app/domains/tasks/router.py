"""HTTP routes for the tasks (Tareas) domain.

Task fields (title / project / assignee / priority / due date) are sourced
read-only from Business Central, which is the system of record. The platform owns
internal **notes** on a task. The board's workflow column is not persisted yet
(moving a card is a client-only interaction until BC can be the store). Every
route requires a verified user (and the ``x-api-key`` gateway header, except
under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client, get_customer_scope
from app.core.visibility import CustomerScope
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import TaskStatus

from .schemas import TaskNoteCreate, TaskNoteResponse, TaskResponse
from .service import TasksService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    status: TaskStatus | None = None,
    project_id: str | None = None,
    assignee_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    scope: CustomerScope = Depends(get_customer_scope),
):
    """List BC user tasks (no obligations), scoped by client.

    Used by the project detail view and "mis tareas". Each card carries its workflow
    ``status`` and a traffic-light colour derived from its due date. Optional query
    params compose: ``status``, ``project_id`` and ``assignee_id``. Scoped to the
    caller's clients (a manager sees all). The Tareas board uses ``GET /tasks/board``.
    """
    service = TasksService(db, bc_client)
    return service.list_tasks(
        status=status, project_id=project_id, assignee_id=assignee_id, scope=scope
    )


@router.get("/board", response_model=list[TaskResponse])
def list_board(
    status: TaskStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    scope: CustomerScope = Depends(get_customer_scope),
):
    """The Tareas board: BC tasks + obligations shown as tasks, scoped by client.

    Each card carries its workflow column (``status``), a traffic-light colour from
    its due date, and a ``source`` (task/obligation). Visible under the union rule:
    manager, client in scope, or project technician. ``status`` narrows to a column.
    """
    service = TasksService(db, bc_client)
    return service.list_board_cards(current_user, scope, status=status)


@router.get("/mine", response_model=list[TaskResponse])
def list_my_tasks(
    status: TaskStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """List the current user's tasks (the dashboard "Mis tareas de hoy" widget).

    The logged-in local user is mapped to their BC assignee by email; a user with
    no matching BC user has no tasks. ``status`` narrows to one board column.
    """
    service = TasksService(db, bc_client)
    return service.list_my_tasks(current_user, status=status)


@router.get("/{task_id}/notes", response_model=list[TaskNoteResponse])
def list_task_notes(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """List a task's internal notes, oldest first (404 if the task is unknown)."""
    service = TasksService(db, bc_client)
    return service.list_notes(task_id)


@router.post("/{task_id}/notes", response_model=TaskNoteResponse, status_code=201)
def add_task_note(
    task_id: str,
    data: TaskNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Add an internal note to a task (404 if the task is unknown)."""
    service = TasksService(db, bc_client)
    return service.add_note(task_id, current_user, data.body)
