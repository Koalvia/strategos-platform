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
    Cliente/NIF/Tipo/Responsable/Proyectos/Estado.
    """

    name: str
    nif: str
    entity_type: str
    responsible: str
    project_count: int
    status: CustomerStatus
