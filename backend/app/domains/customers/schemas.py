"""Pydantic v2 schemas for the customers (Clientes) domain.

These are the API shapes Strategos exposes to its own frontend. They are mapped
from the Business Central transport DTOs
(:class:`~app.integrations.business_central.models.BCCustomer`) in the service —
the domain has no database model because customers live in Business Central.
"""

from pydantic import BaseModel

from app.integrations.business_central.models import CustomerStatus


class CustomerResponse(BaseModel):
    """A customer as shown in the Clientes directory.

    Field names mirror the columns of ``clientes.png``:
    Cliente/NIF/Tipo/Responsable/Proyectos/Estado. ``id`` is the Business Central
    customer id (``BCCustomer.id``); it is not shown as a column but lets the
    frontend route to a customer's detail screen (``/clientes/{id}``).
    """

    id: str
    name: str
    nif: str
    entity_type: str
    responsible: str
    project_count: int
    status: CustomerStatus


class CustomerPageResponse(BaseModel):
    """One page of the Clientes directory plus an opaque continuation token.

    ``next_cursor`` is ``None`` once there are no more customers to page
    through; otherwise pass it back as the ``cursor`` query param to fetch the
    next page.
    """

    items: list[CustomerResponse]
    next_cursor: str | None = None
