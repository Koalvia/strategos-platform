"""Business logic for the dashboard (Dashboard) domain.

The dashboard has **no persistence and no models** — it only composes data the
other domains already serve. It instantiates the obligations, tasks, and billing
services (sharing the same injected DB session and Business Central client).

Each widget method executes independently and defensively using ``_section``
so that an outage or failure in one remote Business Central endpoint only degrades
that specific widget, returning ``None`` without failing the rest of the application.
"""

from collections.abc import Callable
from datetime import date
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import logger
from app.core.pagination import build_paginated_response
from app.core.visibility import CustomerScope
from app.domains.billing.service import BillingService
from app.domains.obligations.schemas import (
    DerivedObligationStatus,
    ProjectObligationResponse,
)
from app.domains.obligations.service import (
    DEFAULT_UPCOMING_WINDOW_DAYS,
    ObligationsService,
)
from app.domains.tasks.service import TasksService
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    CustomerStatus,
    ProjectStatus,
    TaskStatus,
)

from .schemas import ActiveTotalKpi, CountKpi, CustomerBillingPage, PendingTotalKpi

# Log keys naming the Business Central-backed source behind each widget, so a
# degraded widget is identifiable in the logs.
SECTION_CUSTOMERS = "customers"
SECTION_PROJECTS = "projects"
SECTION_TASKS = "tasks"
SECTION_OBLIGATIONS = "obligations"
SECTION_BILLING = "billing"

_T = TypeVar("_T")


class DashboardService:
    """Compose granular dashboard widgets from the other domains' services."""

    def __init__(
        self,
        db: Session,
        bc_client: BusinessCentralClient,
        scope: CustomerScope | None = None,
    ):
        self.bc_client = bc_client
        # None means every customer, matching the BC port's own filter contract.
        self.customer_ids = (
            list(scope.customer_ids)
            if scope and scope.customer_ids is not None
            else None
        )
        self.obligations = ObligationsService(db, bc_client)
        self.tasks = TasksService(db, bc_client)
        self.billing = BillingService(db, bc_client)

    def get_active_projects_kpi(self) -> ActiveTotalKpi | None:
        """Return active and total projects count for the KPI card."""
        projects = self._section(
            SECTION_PROJECTS,
            lambda: self.bc_client.get_projects(customer_ids=self.customer_ids),
        )
        if projects is None:
            return None
        return ActiveTotalKpi(
            active=sum(1 for p in projects if p.status is ProjectStatus.active),
            total=len(projects),
        )

    def get_active_customers_kpi(self) -> ActiveTotalKpi | None:
        """Return active and total customers count for the KPI card."""
        customers = self._section(
            SECTION_CUSTOMERS,
            lambda: self.bc_client.get_customers(customer_ids=self.customer_ids),
        )
        if customers is None:
            return None
        return ActiveTotalKpi(
            active=sum(1 for c in customers if c.status is CustomerStatus.active),
            total=len(customers),
        )

    def get_pending_tasks_kpi(self) -> PendingTotalKpi | None:
        """Return pending and total tasks count for the KPI card."""
        return self._section(SECTION_TASKS, self._build_tasks_kpi)

    def get_upcoming_obligations_kpi(
        self,
        reference_date: date,
        upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
    ) -> CountKpi | None:
        """Return how many obligations fall due inside the upcoming window.

        Overdue instances are deliberately excluded: the tile reads "en los
        próximos N días", so it counts only what is still ahead.
        """
        obligations = self._section(
            SECTION_OBLIGATIONS,
            lambda: self.obligations.list_project_obligations(
                reference_date=reference_date,
                upcoming_within_days=upcoming_within_days,
            ),
        )
        if obligations is None:
            return None
        return CountKpi(
            count=sum(
                1 for o in obligations if o.status is DerivedObligationStatus.upcoming
            )
        )

    def get_upcoming_obligations_list(
        self,
        reference_date: date,
        upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
    ) -> list[ProjectObligationResponse] | None:
        """Return upcoming and overdue obligation instances ordered by due date."""
        obligations = self._section(
            SECTION_OBLIGATIONS,
            lambda: self.obligations.list_project_obligations(
                reference_date=reference_date,
                upcoming_within_days=upcoming_within_days,
            ),
        )
        if obligations is None:
            return None
        return [
            o
            for o in obligations
            if o.status
            in (DerivedObligationStatus.overdue, DerivedObligationStatus.upcoming)
        ]

    def get_billing(
        self, page: int = 1, page_size: int = 10
    ) -> CustomerBillingPage | None:
        """Return one page of the per-customer billing breakdown.

        The page's customers are picked first, then aggregated — so a request
        reads only those customers' invoices, credit memos, projects, costs and
        hours out of Business Central instead of the whole company's. Paging is
        what bounds the work, not just what is displayed.

        That is why customers come back ordered by name: an order Business
        Central can slice natively is a prerequisite for choosing the page before
        knowing anything about its contents. Ordering by net billing (which the
        unscoped ``/billing/by-customer`` still does) would require totalling
        every customer just to decide who belongs on page one.
        """
        customers = self._section(
            SECTION_CUSTOMERS,
            lambda: self.bc_client.get_customer_refs_page(
                page=page, page_size=page_size, customer_ids=self.customer_ids
            ),
        )
        if customers is None:
            return None

        billing = self._section(
            SECTION_BILLING,
            lambda: self.billing.billing_for_customers(customers.items),
        )
        if billing is None:
            return None

        return build_paginated_response(
            billing, customers.total_count, page, page_size
        )

    def _section(self, key: str, compute: Callable[[], _T]) -> _T | None:
        """Run one dashboard section, degrading to ``None`` if it cannot load."""
        try:
            return compute()
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "Dashboard section %r unavailable: Business Central read failed", key
            )
            return None

    def _build_tasks_kpi(self) -> PendingTotalKpi:
        """Count the firm's not-done tasks for the "Tareas pendientes" tile."""
        tasks = self.tasks.list_tasks()
        return PendingTotalKpi(
            pending=sum(1 for t in tasks if t.status is not TaskStatus.done),
            total=len(tasks),
        )

