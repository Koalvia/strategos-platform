"""HTTP routes for the dashboard (Dashboard) domain.

The dashboard is a read-only aggregation view sourced (transitively) from
Business Central, which is the system of record. It has no persistence of its
own. Every route requires a verified user (and the ``x-api-key`` gateway header,
except under ``TESTING=1``).

The obligation-derived KPI/list are computed against a reference "today". That
date is supplied by the :func:`get_reference_date` dependency (the server date by
default) so tests can override it via ``app.dependency_overrides`` and assert the
aggregation deterministically.
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.business_central.client import BusinessCentralClient

from .schemas import DashboardSummary
from .service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_reference_date() -> date:
    """Return the reference "today" used to derive obligation due states."""
    return date.today()


@router.get("/summary", response_model=DashboardSummary)
def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    reference_date: date = Depends(get_reference_date),
):
    """Return the composed dashboard summary for the current user.

    Four firm-wide KPI tiles (proyectos activos, obligaciones próximas, tareas
    pendientes, clientes activos), the "Próximas obligaciones" list
    (upcoming/overdue instances across all projects, ordered by due date) and the
    current user's "Mis tareas de hoy" list. Every number delegates to the
    underlying customers/projects/obligations/tasks services.
    """
    service = DashboardService(db, bc_client)
    return service.build_summary(current_user, reference_date)
