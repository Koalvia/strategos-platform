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
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.domains.auth.models import User
from app.domains.billing.service import BillingService
from app.domains.obligations.schemas import DerivedObligationStatus
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

from .schemas import (
    ActiveTotalKpi,
    CountKpi,
    DashboardSummary,
    PendingTotalKpi,
)

# How many customers the dashboard's unified billing table shows (each with all
# its projects nested underneath).
_FINANCIAL_TABLE_LIMIT = 5


class DashboardService:
    """Compose the landing-screen summary from the other domains' services."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.bc_client = bc_client
        self.obligations = ObligationsService(db, bc_client)
        self.tasks = TasksService(db, bc_client)
        self.billing = BillingService(db, bc_client)

    def build_summary(
        self,
        user: User,
        reference_date: date,
        upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
    ) -> DashboardSummary:
        """Build the dashboard summary for ``user`` against ``reference_date``.

        KPI tiles are firm-wide; ``mis_tareas_de_hoy`` is scoped to ``user``'s BC
        tasks. ``proximas_obligaciones`` is the upcoming + overdue obligation
        instances across all projects (everything not "Al día"), and
        ``obligaciones_proximas`` counts just the ones due within the next
        ``upcoming_within_days`` days. Undated instances (``Sin fecha`` — no BC
        due date yet) sit on neither list and are counted nowhere.
        """
        # The KPI needs every customer to count firm-wide, so it reads the full
        # BC list directly rather than through the paginated directory listing
        # (``CustomersService.list_customers``) — the same pattern the
        # projects/obligations services use for their own customer lookups.
        customers = self.bc_client.get_customers()
        clientes_activos = ActiveTotalKpi(
            active=sum(1 for c in customers if c.status is CustomerStatus.active),
            total=len(customers),
        )

        # Same reasoning as clientes_activos above: this KPI needs every
        # project to count firm-wide, so it bypasses the paginated directory
        # listing (``ProjectsService.list_projects``) and reads the full BC
        # list directly.
        projects = self.bc_client.get_projects()
        proyectos_activos = ActiveTotalKpi(
            active=sum(1 for p in projects if p.status is ProjectStatus.active),
            total=len(projects),
        )

        tasks = self.tasks.list_tasks()
        tareas_pendientes = PendingTotalKpi(
            pending=sum(1 for t in tasks if t.status is not TaskStatus.done),
            total=len(tasks),
        )

        # The obligations service already derives each instance's status and
        # orders the result by due date, so we partition its output rather than
        # re-implementing the window / ordering here.
        obligations = self.obligations.list_project_obligations(
            reference_date=reference_date,
            upcoming_within_days=upcoming_within_days,
        )
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

        # "Mis tareas de hoy": the current user's unfinished tasks due within the
        # same upcoming window (overdue ones included), ordered by due date.
        cutoff = reference_date + timedelta(days=upcoming_within_days)
        mis_tareas_de_hoy = sorted(
            (
                t
                for t in self.tasks.list_my_tasks(user)
                if t.status is not TaskStatus.done and t.due_date <= cutoff
            ),
            key=lambda t: t.due_date,
        )

        # Financial section, aggregated live from Business Central into a single
        # per-customer table with each customer's projects nested underneath
        # (billing, usage cost, hours). The billing breakdowns read the same
        # invoice/credit-memo lines and the projects already fetched above for
        # the projects KPI, so fetch each once and hand them to the service — a
        # single dashboard load does not re-fetch the same BC endpoints. Only the
        # top customers by net billing are shown.
        invoice_lines = self.bc_client.get_sales_invoice_lines()
        cr_memo_lines = self.bc_client.get_sales_cr_memo_lines()
        facturacion = self.billing.billing_by_customer_grouped(
            invoice_lines=invoice_lines,
            cr_memo_lines=cr_memo_lines,
            projects=projects,
        )

        return DashboardSummary(
            proyectos_activos=proyectos_activos,
            obligaciones_proximas=obligaciones_proximas,
            tareas_pendientes=tareas_pendientes,
            clientes_activos=clientes_activos,
            proximas_obligaciones=proximas_obligaciones,
            mis_tareas_de_hoy=mis_tareas_de_hoy,
            facturacion=facturacion[:_FINANCIAL_TABLE_LIMIT],
        )
