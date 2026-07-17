"""HTTP routes for the customers (Clientes) domain.

Read-only: the directory is sourced from Business Central, which is the system
of record. Every route requires a verified user (and the ``x-api-key`` gateway
header, except under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_bopa_client, get_business_central_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.domains.bopa.schemas import DocumentSearchPage
from app.domains.bopa.service import BopaService
from app.integrations.bopa.client import BopaClient
from app.integrations.business_central.client import (
    DEFAULT_CUSTOMERS_PAGE_SIZE,
    BusinessCentralClient,
)
from app.integrations.business_central.models import CustomerStatus

from .schemas import CustomerPageResponse, CustomerResponse
from .service import CustomersService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=CustomerPageResponse)
def list_customers(
    search: str | None = None,
    status: CustomerStatus | None = None,
    cursor: str | None = None,
    page_size: int = DEFAULT_CUSTOMERS_PAGE_SIZE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """List one page of the firm's customers, sourced read-only from Business Central.

    Optional query params: ``search`` (case-insensitive substring match on name
    or NIF), ``status`` (``Activo`` / ``Inactivo``), ``cursor`` (the
    continuation token from a previous page's ``next_cursor``) and
    ``page_size``.
    """
    service = CustomersService(db, bc_client)
    return service.list_customers(
        search=search, status=status, cursor=cursor, page_size=page_size
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return a single customer by id (404 if unknown)."""
    service = CustomersService(db, bc_client)
    return service.get_customer(customer_id)

@router.get("/{customer_id}/bopa-matches", response_model=DocumentSearchPage)
def get_customer_bopa_matches(
    customer_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Search BOPA documents matching a customer's name, NIF, and projects.

    Finds all BOPA documents whose title or body mentions the customer's
    name, NIF, or any of their associated project names. Results are
    paginated and ordered by article date (most recent first).

    Query params: ``limit`` (1–200, default 50), ``offset`` (default 0).
    Raises 404 if the customer does not exist.
    """
    customers_service = CustomersService(db, bc_client)
    customer = customers_service.get_customer(customer_id)

    # Get projects belonging to this customer
    projects = bc_client.get_projects()
    customer_projects = [p for p in projects if p.customer_id == customer_id]
    project_names = [p.name for p in customer_projects]

    bopa_service = BopaService(db, bopa_client)
    return bopa_service.search_documents_by_client(
        nombre=customer.name,
        nif=customer.nif,
        proyectos=project_names,
        limit=limit,
        offset=offset,
    )

