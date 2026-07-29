"""HTTP routes for the dashboard (Dashboard) domain.

The dashboard is a read-only aggregation view sourced (transitively) from
Business Central, which is the system of record. It has no persistence of its
own. Every route requires a verified user (and the ``x-api-key`` gateway header,
except under ``TESTING=1``).

Each widget has its own endpoint so the frontend can load them granularly and in
parallel: a Business Central outage behind one widget degrades that widget to
``null`` with a 200 and leaves the others intact.

The obligation-derived KPI/list are computed against a reference "today". That
date is supplied by the :func:`get_reference_date` dependency (the server date by
default) so tests can override it via ``app.dependency_overrides`` and assert the
aggregation deterministically.
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
    ActiveTotalKpi,
    CountKpi,
    CustomerBillingPage,
    PendingTotalKpi,
    ProjectObligationResponse,
)
from .service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_reference_date() -> date:
    """Return the reference "today" used to derive obligation due states."""
    return date.today()


@router.get("/active-projects", response_model=ActiveTotalKpi | None)
def get_active_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return the active and total projects count for the KPI tile."""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = DashboardService(db, bc_client).get_active_projects_kpi()

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /active-projects | start {start_hour} | took {duration:.2f}s")
    return result


@router.get("/active-customers", response_model=ActiveTotalKpi | None)
def get_active_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return the active and total customers count for the KPI tile."""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = DashboardService(db, bc_client).get_active_customers_kpi()

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /active-customers | start {start_hour} | took {duration:.2f}s")
    return result


@router.get("/pending-tasks", response_model=PendingTotalKpi | None)
def get_pending_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return the pending and total tasks count for the KPI tile."""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = DashboardService(db, bc_client).get_pending_tasks_kpi()

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /pending-tasks | start {start_hour} | took {duration:.2f}s")
    return result


@router.get("/upcoming-obligations-count", response_model=CountKpi | None)
def get_upcoming_obligations_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    reference_date: date = Depends(get_reference_date),
):
    """Return how many obligations fall due inside the upcoming window."""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = DashboardService(db, bc_client).get_upcoming_obligations_kpi(reference_date)

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /upcoming-obligations-count | start {start_hour} | took {duration:.2f}s")
    return result


@router.get("/obligations", response_model=list[ProjectObligationResponse] | None)
def get_upcoming_obligations_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
    reference_date: date = Depends(get_reference_date),
):
    """Return the upcoming and overdue obligations, ordered by due date."""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = DashboardService(db, bc_client).get_upcoming_obligations_list(reference_date)

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /obligations | start {start_hour} | took {duration:.2f}s")
    return result


@router.get("/billing", response_model=CustomerBillingPage | None)
def get_billing_summary(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=1, le=100, description="Customer groups per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Return one page of the per-customer billing breakdown (10 per page)."""
    start_time = time.perf_counter()
    start_hour = datetime.now().strftime("%H:%M:%S")

    result = DashboardService(db, bc_client).get_billing(page=page, page_size=page_size)

    duration = time.perf_counter() - start_time
    logger.info(
        f"[Performance] GET /billing (page {page}) | start {start_hour} | took {duration:.2f}s")
    return result
