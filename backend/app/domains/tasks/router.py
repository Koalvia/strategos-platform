"""HTTP routes for the tasks (Tareas) domain.

Tasks are sourced read-only from Business Central, which is the system of record,
so this round exposes no task create/update from the platform. The only writes
are platform-native internal **notes** on a task (the domain's one local table).
Every route requires a verified user (and the ``x-api-key`` gateway header,
except under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client
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
):
    """List tasks across the firm, sourced read-only from Business Central.

    Each task carries its title, the project it belongs to, the assignee, a
    priority (Alta / Media / Baja) and a status (Pendiente / En curso / Hecho)
    the frontend groups into board columns. Optional query params (all compose):
    ``status``, ``project_id`` and ``assignee_id``.
    """
    service = TasksService(db, bc_client)
    return service.list_tasks(
        status=status, project_id=project_id, assignee_id=assignee_id
    )


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
