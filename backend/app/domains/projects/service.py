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

from app.core.visibility import (
    CustomerScope,
    may_see_project,
    users_by_key,
)
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
        user_email: str | None = None,
    ) -> ProjectPageResponse:
        """Return one page of projects, optionally filtered. Filters compose.

        Visible by union: the caller's own customers, or projects where they are the
        technician/responsible. Managers (scope None / sees everything) see all.
        """
        if scope is None or scope.sees_everything:
            page = self.bc_client.get_projects_page(
                search=search,
                project_type=project_type,
                entity_type=entity_type,
                status=status,
                customer_id=customer_id,
                cursor=cursor,
                page_size=page_size,
            )
            items = page.items
            next_cursor = page.next_cursor
            no_assigned_customers = False
        else:
            # Union can't be pushed to BC (technician projects have out-of-scope
            # customers), so read all and filter/paginate here (offset cursor).
            by_key = users_by_key(self.bc_client.get_users())
            visible = [
                p
                for p in self.bc_client.get_projects()
                if may_see_project(p, user_email or "", scope, by_key)
            ]
            visible = self._apply_filters(
                visible, search, project_type, entity_type, status, customer_id
            )
            # A scoped cursor is our own integer offset; ignore a stray non-integer
            # one (e.g. a BC opaque cursor from a manager session) instead of 500ing.
            try:
                offset = int(cursor) if cursor else 0
            except ValueError:
                offset = 0
            items = visible[offset : offset + page_size]
            next_offset = offset + page_size
            next_cursor = str(next_offset) if next_offset < len(visible) else None
            no_assigned_customers = scope.customer_ids == () and not visible

        customer_ids = {p.customer_id for p in items if p.customer_id}
        names_by_id = self.bc_client.get_customer_names(list(customer_ids))
        return ProjectPageResponse(
            items=[self._to_response(p, names_by_id) for p in items],
            next_cursor=next_cursor,
            no_assigned_customers=no_assigned_customers,
        )

    def get_project(
        self,
        project_id: str,
        scope: CustomerScope | None = None,
        user_email: str | None = None,
    ) -> ProjectResponse:
        """Return a single project by id, or 404 if unknown or not visible.

        Visible by union: client in scope, or the caller is technician/responsible.
        """
        for project in self.bc_client.get_projects():
            if project.id != project_id:
                continue
            visible = scope is None or scope.sees(project.customer_id)
            if not visible and user_email:
                visible = may_see_project(
                    project, user_email, scope, users_by_key(self.bc_client.get_users())
                )
            if visible:
                names_by_id = self.bc_client.get_customer_names([project.customer_id])
                return self._to_response(project, names_by_id)
            break
        raise HTTPException(status_code=404, detail="Project not found")

    @staticmethod
    def _apply_filters(
        projects: list[BCProject],
        search: str | None,
        project_type: str | None,
        entity_type: str | None,
        status: ProjectStatus | None,
        customer_id: str | None,
    ) -> list[BCProject]:
        """Apply the same filters as ``get_projects_page`` (used for the union page)."""
        if search:
            needle = search.casefold()
            projects = [p for p in projects if needle in p.name.casefold()]
        if customer_id is not None:
            projects = [p for p in projects if p.customer_id == customer_id]
        if project_type is not None:
            wanted = project_type.casefold()
            projects = [p for p in projects if (p.project_type or "").casefold() == wanted]
        if entity_type is not None:
            wanted = entity_type.casefold()
            projects = [p for p in projects if (p.entity_type or "").casefold() == wanted]
        if status is not None:
            projects = [p for p in projects if p.status is status]
        return projects

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
