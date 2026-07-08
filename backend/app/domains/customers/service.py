"""Business logic for the customers (Clientes) domain.

The service reads customers read-only from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
(never from fixtures directly), maps the transport DTOs to
:class:`~app.domains.customers.schemas.CustomerResponse`, and applies the
optional ``search`` / ``status`` filters in memory (the dataset is small).
"""

from sqlalchemy.orm import Session

from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import BCCustomer, CustomerStatus

from .schemas import CustomerResponse


class CustomersService:
    """Serve the firm's customer directory from Business Central."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_customers(
        self,
        search: str | None = None,
        status: CustomerStatus | None = None,
    ) -> list[CustomerResponse]:
        """Return all customers, optionally filtered by ``search`` and ``status``.

        ``search`` matches the customer name **or** NIF as a case-insensitive
        substring; ``status`` keeps only customers in that state.
        """
        customers = self.bc_client.get_customers()

        if search:
            needle = search.casefold()
            customers = [
                c
                for c in customers
                if needle in c.name.casefold() or needle in c.nif.casefold()
            ]

        if status is not None:
            customers = [c for c in customers if c.status is status]

        return [self._to_response(c) for c in customers]

    @staticmethod
    def _to_response(customer: BCCustomer) -> CustomerResponse:
        """Map a Business Central customer DTO to the API response shape."""
        return CustomerResponse(
            name=customer.name,
            nif=customer.nif,
            entity_type=customer.customer_type,
            responsible=customer.responsible,
            project_count=customer.active_project_count,
            status=customer.status,
        )
