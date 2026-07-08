"""HTTP routes for the users (Usuarios) directory.

A thin read-only route: identity/login stays in the ``auth`` domain (unchanged),
this router only exposes the "who's who" directory the Usuarios page renders.
Requires a verified user (and the ``x-api-key`` gateway header, except under
``TESTING=1``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client
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
):
    """List the staff directory: name, role, email and active-task count per user.

    Users come from the local ``auth.User`` table (identity stays local); the
    active-task count is each user's number of non-"Hecho" tasks, resolved from
    Business Central's ``userTasks`` by matching the local email to a BC user.
    """
    service = UsersService(db, bc_client)
    return service.list_directory()
