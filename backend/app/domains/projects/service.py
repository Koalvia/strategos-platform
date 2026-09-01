"""Business logic for the projects (Proyectos) domain.

The service reads projects read-only from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
(never from fixtures directly), maps the transport DTOs to
:class:`~app.domains.projects.schemas.ProjectResponse`, and resolves each
project's customer name from BC. The optional ``search`` / ``project_type`` /
``entity_type`` / ``status`` filters and pagination are delegated to the BC
client (``get_projects_page``) rather than applied here — see that method on
each implementation.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.visibility import CustomerScope
from app.integrations.business_central.client import (
    DEFAULT_PROJECTS_PAGE_SIZE,
    BusinessCentralClient,
)
from app.integrations.business_central.models import BCProject, ProjectStatus

from .schemas import ProjectCustomer, ProjectPageResponse, ProjectResponse


class ProjectsService:
    """Serve the firm's projects from Business Central."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_projects(
        self,
        search: str | None = None,
        project_type: str | None = None,
        entity_type: str | None = None,
        status: ProjectStatus | None = None,
        customer_id: str | None = None,
        scope: CustomerScope | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    ) -> ProjectPageResponse:
        """Return one page of projects, optionally filtered. Filters compose.

        ``scope`` limits the page to the projects of the caller's own customers;
        omitting it returns every project.
        """
        page = self.bc_client.get_projects_page(
            search=search,
            project_type=project_type,
            entity_type=entity_type,
            status=status,
            customer_id=customer_id,
            customer_ids=list(scope.customer_ids) if scope and scope.customer_ids is not None else None,
            cursor=cursor,
            page_size=page_size,
        )
        items = page.items
        customer_ids = {p.customer_id for p in items if p.customer_id}
        names_by_id = self.bc_client.get_customer_names(list(customer_ids))
        return ProjectPageResponse(
            items=[self._to_response(p, names_by_id) for p in items],
            next_cursor=page.next_cursor,
            no_assigned_customers=bool(scope and scope.customer_ids == ()),
        )

    def get_project(
        self, project_id: str, scope: CustomerScope | None = None
    ) -> ProjectResponse:
        """Return a single project by id, or raise 404 if it does not exist.

        A project whose customer falls outside ``scope`` is a 404 too.
        """
        # Narrowed to the caller's customers, so a scoped lookup never sweeps the
        # whole table; a manager's scope is None and reads everything as before.
        scoped_ids = (
            list(scope.customer_ids)
            if scope and scope.customer_ids is not None
            else None
        )
        for project in self.bc_client.get_projects(customer_ids=scoped_ids):
            if project.id == project_id:
                names_by_id = self.bc_client.get_customer_names([project.customer_id])
                return self._to_response(project, names_by_id)
        raise HTTPException(status_code=404, detail="Project not found")

    @staticmethod
    def _to_response(
        project: BCProject, names_by_id: dict[str, str]
    ) -> ProjectResponse:
        """Map a Business Central project DTO to the API response shape."""
        return ProjectResponse(
            id=project.id,
            name=project.name,
            customer=ProjectCustomer(
                id=project.customer_id,
                name=names_by_id.get(project.customer_id, ""),
            ),
            project_type=project.project_type,
            entity_type=project.entity_type,
            responsible=project.responsible,
            technician=project.technician,
            has_certificate=project.has_certificate,
            certificate_expiry=project.certificate_expiry,
            filing_date=project.filing_date,
            status=project.status,
        )
