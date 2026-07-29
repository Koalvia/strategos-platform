"""Pydantic v2 schemas for the dashboard (Dashboard) domain.

The dashboard is a pure **aggregation** view: it has no data of its own. Every
widget is served by its own endpoint, and the two list widgets reuse the source
domains' response shapes (:class:`~app.domains.obligations.schemas.ProjectObligationResponse`
and :class:`~app.domains.billing.schemas.CustomerBillingGroupResponse`) rather
than redefining them.

Field names mirror the KPI tiles and widgets in ``dashboard.png`` (Proyectos
activos / Obligaciones próximas / Tareas pendientes / Clientes activos, plus the
"Próximas obligaciones" list and the "Facturación" table).
"""

from pydantic import BaseModel

from app.core.schemas import PaginatedResponse
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


# One page of the "Facturación" table. Uses the shared pagination envelope so the
# client learns the real total instead of receiving a bare, unbounded list it
# cannot page through.
CustomerBillingPage = PaginatedResponse[CustomerBillingGroupResponse]


__all__ = [
    "ActiveTotalKpi",
    "PendingTotalKpi",
    "CountKpi",
    "CustomerBillingPage",
    "ProjectObligationResponse",
    "CustomerBillingGroupResponse",
]
