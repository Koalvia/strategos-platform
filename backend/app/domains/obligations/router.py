"""HTTP routes for the obligations (Obligaciones) domain.

Read-only: obligations are sourced from Business Central, which is the system of
record. Every route requires a verified user (and the ``x-api-key`` gateway
header, except under ``TESTING=1``). There are no write endpoints — marking an
obligation as filed is out of scope for this round.

The per-project ``status`` is derived against a reference "today". That date is
supplied by the :func:`get_reference_date` dependency (the server date by
default) so tests can override it via ``app.dependency_overrides`` and assert the
derivation deterministically.

The instance listing is **paginated**: it answers with the shared
``{items, meta}`` envelope from ``app.core.schemas`` rather than a bare array, so
the client can page through the result and knows how many matches exist in total.
``GET /obligations`` and ``GET /obligations/projects`` also log their duration, the
same way every dashboard route does, so the cost of a page load stays visible in
the logs.
"""

import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import logger
from app.core.dependencies import get_business_central_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.business_central.client import BusinessCentralClient

from .schemas import (
    DerivedObligationStatus,
    EntityRef,
    ObligationTypeResponse,
    ProjectObligationPage,
)
from .service import ObligationsService

router = APIRouter(prefix="/obligations", tags=["obligations"])


def get_reference_date() -> date:
    """Return the reference "today" used to derive obligation due states."""
    return date.today()


@router.get("/catalog", response_model=list[ObligationTypeResponse])
def list_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return the obligation catalog (type, periodicity and due-date rule)."""
    service = ObligationsService(db, bc_client)
    return service.list_catalog()


@router.get("/projects", response_model=list[EntityRef])
def list_obligation_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return the distinct projects that have obligations, ordered by name.

    This is the option list for the Obligaciones screen's "Proyecto" filter. It
    exists as its own endpoint so that screen does not have to download every
    obligation a second time just to derive the names — which is both expensive
    and, once the table is paginated, wrong: the options would then change with
    the page being viewed.
    """
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = ObligationsService(db, bc_client).list_obligation_projects()

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /obligations/projects | start {start_hour} | took {duration:.2f}s")
    return result


@router.get("", response_model=ProjectObligationPage)
def list_project_obligations(
    status: DerivedObligationStatus | None = None,
    project_id: str | None = None,
    due_after: date | None = None,
    due_before: date | None = None,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int | None = Query(
        None,
        ge=1,
        le=100,
        description="Instances per page; omit to get every match in one page",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    reference_date: date = Depends(get_reference_date),
):
    """List one page of per-project obligation instances, read-only from BC"""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = ObligationsService(db, bc_client).list_project_obligations_page(
        reference_date=reference_date,
        status=status,
        project_id=project_id,
        due_after=due_after,
        due_before=due_before,
        page=page,
        page_size=page_size,
    )

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /obligations (page {page}) | start {start_hour} | took {duration:.2f}s")
    return result
