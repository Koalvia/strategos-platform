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
        cursor: str | None = None,
        page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    ) -> ProjectPageResponse:
        """Return one page of projects, optionally filtered.

        ``search`` matches the project name as a case-insensitive substring;
        ``project_type`` and ``entity_type`` match their field as a
        case-insensitive exact value (the two "Todos" dropdowns in
        ``proyectos.png``); ``status`` keeps only projects in that state;
        ``customer_id`` keeps only projects belonging to that customer (an exact
        match on ``BCProject.customer_id``, applied here rather than pushed down
        to the BC page — mirroring the obligations domain's ``project_id``
        filter); ``cursor`` continues a previous page (see
        ``ProjectPageResponse.next_cursor``). Filters compose (all supplied
        filters must match).
        """
        page = self.bc_client.get_projects_page(
            search=search,
            project_type=project_type,
            entity_type=entity_type,
            status=status,
            cursor=cursor,
            page_size=page_size,
        )
        items = page.items
        if customer_id is not None:
            items = [p for p in items if p.customer_id == customer_id]
        customer_ids = {p.customer_id for p in items if p.customer_id}
        names_by_id = self.bc_client.get_customer_names(list(customer_ids))
        return ProjectPageResponse(
            items=[self._to_response(p, names_by_id) for p in items],
            next_cursor=page.next_cursor,
        )

    def get_project(self, project_id: str) -> ProjectResponse:
        """Return a single project by id, or raise 404 if it does not exist."""
        for project in self.bc_client.get_projects():
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
