"""Business logic for the customers (Clientes) domain.

The service reads customers read-only from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
(never from fixtures directly) and maps the transport DTOs to
:class:`~app.domains.customers.schemas.CustomerResponse`. The optional
``search`` / ``status`` filters and pagination are delegated to the BC client
(``get_customers_page``) rather than applied here, since the client is the
one place that knows how to push them down to BC (or, for the mock, filter
the fixtures) — see ``get_customers_page`` on each implementation.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.visibility import CustomerScope
from app.integrations.business_central.client import (
    DEFAULT_CUSTOMERS_PAGE_SIZE,
    BusinessCentralClient,
)
from app.integrations.business_central.models import BCCustomer, CustomerStatus

from .schemas import CustomerPageResponse, CustomerResponse


class CustomersService:
    """Serve the firm's customer directory from Business Central."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_customers(
        self,
        search: str | None = None,
        status: CustomerStatus | None = None,
        scope: CustomerScope | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_CUSTOMERS_PAGE_SIZE,
    ) -> CustomerPageResponse:
        """Return one page of customers, optionally filtered by ``search``/``status``.

        ``scope`` limits the page to the caller's own customers; omitting it
        returns every customer.
        """
        page = self.bc_client.get_customers_page(
            search=search,
            status=status,
            customer_ids=list(scope.customer_ids) if scope and scope.customer_ids is not None else None,
            cursor=cursor,
            page_size=page_size,
        )
        return CustomerPageResponse(
            items=[self._to_response(c) for c in page.items],
            next_cursor=page.next_cursor,
            no_assigned_customers=bool(scope and scope.customer_ids == ()),
        )

    def get_customer(
        self, customer_id: str, scope: CustomerScope | None = None
    ) -> CustomerResponse:
        """Return a single customer by id, or raise 404 if it does not exist.

        A customer outside ``scope`` is a 404 too: the URL must not reveal what the
        listing hides.
        """
        if scope and scope.customer_ids is not None:
            if customer_id not in scope.customer_ids:
                raise HTTPException(status_code=404, detail="Customer not found")

        # Scoped to the one id: no reason to read the whole table to find one row.
        for customer in self.bc_client.get_customers(customer_ids=[customer_id]):
            if customer.id == customer_id:
                return self._to_response(customer)
        raise HTTPException(status_code=404, detail="Customer not found")

    @staticmethod
    def _to_response(customer: BCCustomer) -> CustomerResponse:
        """Map a Business Central customer DTO to the API response shape."""
        return CustomerResponse(
            id=customer.id,
            name=customer.name,
            nif=customer.nif,
            entity_type=customer.customer_type,
            responsible=customer.responsible,
            project_count=customer.active_project_count,
            status=customer.status,
        )
