"""HTTP routes for the projects (Proyectos) domain.

Read-only: projects are sourced from Business Central, which is the system of
record. Every route requires a verified user (and the ``x-api-key`` gateway
header, except under ``TESTING=1``). Only the fitxa **General** section is
served here; the obligation checklist is a separate domain (issue #9).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.business_central.client import (
    DEFAULT_PROJECTS_PAGE_SIZE,
    BusinessCentralClient,
)
from app.integrations.business_central.models import ProjectStatus

from .schemas import ProjectPageResponse, ProjectResponse
from .service import ProjectsService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectPageResponse)
def list_projects(
    search: str | None = None,
    project_type: str | None = None,
    entity_type: str | None = None,
    status: ProjectStatus | None = None,
    customer_id: str | None = None,
    cursor: str | None = None,
    page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """List one page of projects, sourced read-only from Business Central.

    Optional query params (all compose): ``search`` (case-insensitive substring
    match on the project name), ``project_type`` and ``entity_type``
    (case-insensitive exact match), ``status`` (``Activo`` / ``Inactivo``),
    ``customer_id`` (exact match, used by the customer detail screen to list a
    client's own projects), ``cursor`` (the continuation token from a previous
    page's ``next_cursor``) and ``page_size``.
    """
    service = ProjectsService(db, bc_client)
    return service.list_projects(
        search=search,
        project_type=project_type,
        entity_type=entity_type,
        status=status,
        customer_id=customer_id,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return a single project by id (404 if unknown)."""
    service = ProjectsService(db, bc_client)
    return service.get_project(project_id)
