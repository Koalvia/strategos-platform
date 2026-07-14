"""HTTP routes for the customers (Clientes) domain.

Read-only: the directory is sourced from Business Central, which is the system
of record. Every route requires a verified user (and the ``x-api-key`` gateway
header, except under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
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
