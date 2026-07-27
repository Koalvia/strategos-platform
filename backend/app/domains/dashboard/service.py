"""Business logic for the dashboard (Dashboard) domain.

The dashboard has **no persistence and no models** — it only composes data the
other domains already serve. It instantiates the obligations and tasks services
(sharing the same injected DB session and Business Central client) and
delegates their numbers/lists to them; the customer and project KPI counts read
``bc_client`` directly instead, since they need the firm-wide total rather than
one page of the (now paginated) customers/projects directory listings.

The obligation-derived numbers depend on a reference "today" (the same one the
obligations domain uses). The router injects the server date; tests freeze it so
the aggregation can be asserted deterministically.

Every section is composed **independently and defensively** (see ``_section``):
Business Central is a remote system whose endpoints may be unavailable, and a
single failing read must not blank the whole panel. A section that cannot be
loaded travels as ``None`` (never as a zero or an empty list, which would be
indistinguishable from real data) and its key is recorded in
``DashboardSummary.unavailable_sections`` so the UI can say what is missing.
"""

from collections.abc import Callable
from datetime import date
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import logger
from app.domains.billing.schemas import CustomerBillingGroupResponse
from app.domains.billing.service import BillingService
from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.obligations.service import (
    DEFAULT_UPCOMING_WINDOW_DAYS,
    ObligationsService,
)
from app.domains.tasks.service import TasksService
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCProject,
    CustomerStatus,
    ProjectStatus,
    TaskStatus,
)

from .schemas import (
    ActiveTotalKpi,
    CountKpi,
    DashboardSummary,
    PendingTotalKpi,
)

# How many customers the dashboard's unified billing table shows (each with all
# its projects nested underneath).
_FINANCIAL_TABLE_LIMIT = 5

#: Section keys reported in ``DashboardSummary.unavailable_sections``. Kept in
#: English (repo language policy); the frontend maps them to its Spanish labels.
SECTION_CUSTOMERS = "customers"
SECTION_PROJECTS = "projects"
SECTION_TASKS = "tasks"
SECTION_OBLIGATIONS = "obligations"
SECTION_BILLING = "billing"

_T = TypeVar("_T")


class DashboardService:
    """Compose the landing-screen summary from the other domains' services."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.bc_client = bc_client
        self.obligations = ObligationsService(db, bc_client)
        self.tasks = TasksService(db, bc_client)
        self.billing = BillingService(db, bc_client)
        self._unavailable: list[str] = []

    def build_summary(
        self,
        reference_date: date,
        upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
    ) -> DashboardSummary:
        """Build the dashboard summary against ``reference_date``.

        KPI tiles are firm-wide. ``proximas_obligaciones`` is the upcoming +
        overdue obligation instances across all projects (everything not "Al
        día"), and ``obligaciones_proximas`` counts just the ones due within the
        next ``upcoming_within_days`` days. Undated instances (``Sin fecha`` — no
        BC due date yet) sit on neither list and are counted nowhere.

        Each section is loaded independently: one unavailable Business Central
        endpoint degrades only the sections that depend on it (see
        ``_section``), leaving the rest of the panel usable.
        """
        self._unavailable = []

        # The KPI needs every customer to count firm-wide, so it reads the full
        # BC list directly rather than through the paginated directory listing
        # (``CustomersService.list_customers``) — the same pattern the
        # projects/obligations services use for their own customer lookups.
        customers = self._section(SECTION_CUSTOMERS, self.bc_client.get_customers)
        clientes_activos = (
            None
            if customers is None
            else ActiveTotalKpi(
                active=sum(1 for c in customers if c.status is CustomerStatus.active),
                total=len(customers),
            )
        )

        # Same reasoning as clientes_activos above: this KPI needs every
        # project to count firm-wide, so it bypasses the paginated directory
        # listing (``ProjectsService.list_projects``) and reads the full BC
        # list directly.
        projects = self._section(SECTION_PROJECTS, self.bc_client.get_projects)
        proyectos_activos = (
            None
            if projects is None
            else ActiveTotalKpi(
                active=sum(1 for p in projects if p.status is ProjectStatus.active),
                total=len(projects),
            )
        )

        tareas_pendientes = self._section(SECTION_TASKS, self._build_tasks_kpi)

        # The obligations service already derives each instance's status and
        # orders the result by due date, so we partition its output rather than
        # re-implementing the window / ordering here.
        obligations = self._section(
            SECTION_OBLIGATIONS,
            lambda: self.obligations.list_project_obligations(
                reference_date=reference_date,
                upcoming_within_days=upcoming_within_days,
            ),
        )
        if obligations is None:
            proximas_obligaciones = None
            obligaciones_proximas = None
        else:
            proximas_obligaciones = [
                o
                for o in obligations
                if o.status
                in (DerivedObligationStatus.overdue, DerivedObligationStatus.upcoming)
            ]
            obligaciones_proximas = CountKpi(
                count=sum(
                    1
                    for o in obligations
                    if o.status is DerivedObligationStatus.upcoming
                )
            )

        # Financial section, aggregated live from Business Central into a single
        # per-customer table with each customer's projects nested underneath
        # (billing, usage cost, hours). It reuses the projects already fetched
        # above for the projects KPI, so a single dashboard load does not
        # re-fetch the same BC endpoint — which also means it cannot be built at
        # all when that fetch failed. Only the top customers by net billing are
        # shown.
        if projects is None:
            facturacion = None
            self._unavailable.append(SECTION_BILLING)
        else:
            facturacion = self._section(
                SECTION_BILLING, lambda: self._build_billing(projects)
            )

        return DashboardSummary(
            proyectos_activos=proyectos_activos,
            obligaciones_proximas=obligaciones_proximas,
            tareas_pendientes=tareas_pendientes,
            clientes_activos=clientes_activos,
            proximas_obligaciones=proximas_obligaciones,
            facturacion=facturacion,
            unavailable_sections=self._unavailable,
        )

    def _section(self, key: str, compute: Callable[[], _T]) -> _T | None:
        """Run one dashboard section, degrading to ``None`` if it cannot load.

        Business Central is remote: an endpoint may be disabled on the tenant, a
        row may fail to map, or the call may time out or 401. Any of those would
        otherwise propagate and take down the *entire* summary, so each section
        is isolated here — the failure is logged with its section key and the
        section reports as unavailable.

        ``None`` is deliberately used rather than a zero/empty fallback: a "0"
        the caller cannot distinguish from a real zero would make the dashboard
        show figures that are simply untrue.

        ``HTTPException`` is re-raised: it is a deliberate HTTP outcome (e.g. a
        404 or an auth failure), not an integration outage, and must not be
        masked as missing data.
        """
        try:
            return compute()
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "Dashboard section %r unavailable: Business Central read failed", key
            )
            self._unavailable.append(key)
            return None

    def _build_tasks_kpi(self) -> PendingTotalKpi:
        """Count the firm's not-done tasks for the "Tareas pendientes" tile."""
        tasks = self.tasks.list_tasks()
        return PendingTotalKpi(
            pending=sum(1 for t in tasks if t.status is not TaskStatus.done),
            total=len(tasks),
        )

    def _build_billing(
        self, projects: list[BCProject]
    ) -> list[CustomerBillingGroupResponse]:
        """Build the per-customer billing table, capped to the top customers."""
        facturacion = self.billing.billing_by_customer_grouped(
            invoice_lines=self.bc_client.get_sales_invoice_lines(),
            cr_memo_lines=self.bc_client.get_sales_cr_memo_lines(),
            projects=projects,
        )
        return facturacion[:_FINANCIAL_TABLE_LIMIT]
