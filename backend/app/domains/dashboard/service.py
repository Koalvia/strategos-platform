"""Business logic for the dashboard (Dashboard) domain.

The dashboard has **no persistence and no models** — it only composes data the
other domains already serve. This service instantiates the customers, projects,
obligations and tasks services (all sharing the same injected DB session and
Business Central client) and delegates every number and list to them, so the KPI
tiles stay internally consistent with the underlying endpoints and no filtering
or status logic is duplicated here.

The obligation-derived numbers depend on a reference "today" (the same one the
obligations domain uses). The router injects the server date; tests freeze it so
the aggregation can be asserted deterministically.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.domains.auth.models import User
from app.domains.customers.service import CustomersService
from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.obligations.service import (
    DEFAULT_UPCOMING_WINDOW_DAYS,
    ObligationsService,
)
from app.domains.projects.service import ProjectsService
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


class DashboardService:
    """Compose the landing-screen summary from the other domains' services."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.customers = CustomersService(db, bc_client)
        self.projects = ProjectsService(db, bc_client)
        self.obligations = ObligationsService(db, bc_client)
        self.tasks = TasksService(db, bc_client)

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
        customers = self.customers.list_customers()
        clientes_activos = ActiveTotalKpi(
            active=sum(1 for c in customers if c.status is CustomerStatus.active),
            total=len(customers),
        )

        projects = self.projects.list_projects()
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

        return DashboardSummary(
            proyectos_activos=proyectos_activos,
            obligaciones_proximas=obligaciones_proximas,
            tareas_pendientes=tareas_pendientes,
            clientes_activos=clientes_activos,
            proximas_obligaciones=proximas_obligaciones,
            mis_tareas_de_hoy=mis_tareas_de_hoy,
        )
