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
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import CustomerStatus

from .schemas import CustomerResponse
from .service import CustomersService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    search: str | None = None,
    status: CustomerStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """List the firm's customers, sourced read-only from Business Central.

    Optional query params: ``search`` (case-insensitive substring match on name
    or NIF) and ``status`` (``Activo`` / ``Inactivo``).
    """
    service = CustomersService(db, bc_client)
    return service.list_customers(search=search, status=status)
