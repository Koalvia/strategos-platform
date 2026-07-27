"""Pydantic v2 schemas for the dashboard (Dashboard) domain.

The dashboard is a pure **aggregation** view: it has no data of its own. Its
response is composed by the service from the customers / projects / obligations /
tasks domains, so the two list sections reuse those domains' own response shapes
(:class:`~app.domains.obligations.schemas.ProjectObligationResponse` and
:class:`~app.domains.tasks.schemas.TaskResponse`) rather than redefining them.

Field names mirror the KPI tiles and widgets in ``dashboard.png`` (Proyectos
activos / Obligaciones próximas / Tareas pendientes / Clientes activos, plus the
"Próximas obligaciones" and "Mis tareas de hoy" lists).
"""

from pydantic import BaseModel

from app.domains.billing.schemas import CustomerBillingGroupResponse
from app.domains.obligations.schemas import ProjectObligationResponse


class ActiveTotalKpi(BaseModel):
    """A KPI tile showing how many of a total are currently active."""

    active: int
    total: int


class PendingTotalKpi(BaseModel):
    """A KPI tile showing how many of a total are still pending (not done)."""

    pending: int
    total: int


class CountKpi(BaseModel):
    """A KPI tile that is a single count (obligations due within the window)."""

    count: int


class DashboardSummary(BaseModel):
    """The composed landing-screen summary.

    The four count KPI tiles are firm-wide. ``proximas_obligaciones`` carries the
    upcoming/overdue obligation instances across all projects, ordered by due
    date.

    The financial section is aggregated live from Business Central (see the
    billing domain): ``facturacion`` carries the top customers by net billing,
    each with its projects (billing, usage cost, hours) nested underneath for
    the dashboard's unified accordion table.

    **Every section is nullable.** ``None`` means "could not be loaded from
    Business Central" — a distinct state from an empty list or a zero count,
    which mean the section loaded fine and there is genuinely nothing to show.
    The keys of the sections that failed are listed in ``unavailable_sections``
    so the UI can name them instead of silently rendering a wrong figure. A
    fully healthy summary has every section set and ``unavailable_sections``
    empty.
    """

    proyectos_activos: ActiveTotalKpi | None = None
    obligaciones_proximas: CountKpi | None = None
    tareas_pendientes: PendingTotalKpi | None = None
    clientes_activos: ActiveTotalKpi | None = None
    proximas_obligaciones: list[ProjectObligationResponse] | None = None
    facturacion: list[CustomerBillingGroupResponse] | None = None
    unavailable_sections: list[str] = []
