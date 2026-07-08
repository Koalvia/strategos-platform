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

from app.domains.obligations.schemas import ProjectObligationResponse
from app.domains.tasks.schemas import TaskResponse


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
    """The composed landing-screen summary for the current user.

    The four KPI tiles are firm-wide; ``mis_tareas_de_hoy`` is scoped to the
    current user (see ``service.DashboardService``). ``proximas_obligaciones``
    carries the upcoming/overdue obligation instances across all projects,
    ordered by due date.
    """

    proyectos_activos: ActiveTotalKpi
    obligaciones_proximas: CountKpi
    tareas_pendientes: PendingTotalKpi
    clientes_activos: ActiveTotalKpi
    proximas_obligaciones: list[ProjectObligationResponse]
    mis_tareas_de_hoy: list[TaskResponse]
