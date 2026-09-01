"""HTTP routes for the users (Usuarios) directory.

A thin read-only route: identity/login stays in the ``auth`` domain (unchanged),
this router only exposes the "who's who" directory the Usuarios page renders.
Requires a verified user (and the ``x-api-key`` gateway header, except under
``TESTING=1``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client, get_customer_scope
from app.core.visibility import CustomerScope
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.business_central.client import BusinessCentralClient

from .schemas import UserDirectoryEntry
from .service import UsersService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserDirectoryEntry])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    scope: CustomerScope = Depends(get_customer_scope),
):
    """List the staff directory: name, role, email and active-task count per user.

    The listing is scoped to what the caller may see: the full directory only if
    their BC resource has ``manageAllCustomers``, otherwise just their own row.
    """
    service = UsersService(db, bc_client)
    return service.list_directory(current_user, scope=scope)
