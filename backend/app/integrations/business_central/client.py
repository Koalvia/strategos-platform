"""Business Central client port.

The abstract base class every BC client implementation must satisfy. It defines
one method per Business Central endpoint, each returning typed Pydantic DTOs.
Services depend on this interface (via the DI provider in
``app.core.dependencies``), never on a concrete implementation, so the current
:class:`MockBusinessCentralClient` can be replaced by a live client later without
touching callers.
"""

from abc import ABC, abstractmethod

from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerPage,
    BCJobLedgerEntry,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCProjectPage,
    BCResource,
    BCSalesCrMemoHeader,
    BCSalesCrMemoLine,
    BCSalesInvoiceHeader,
    BCSalesInvoiceLine,
    BCTimeSheetPostingEntry,
    BCUser,
    BCUserTask,
    CustomerStatus,
    ProjectStatus,
)

# Shared defaults for the paginated listings; also used as the routers' default
# query params so the API and the client implementations agree on them.
DEFAULT_CUSTOMERS_PAGE_SIZE = 25
DEFAULT_PROJECTS_PAGE_SIZE = 25


class BusinessCentralClient(ABC):
    """Port mirroring the Business Central REST endpoints Strategos consumes."""

    @abstractmethod
    def get_customers(self) -> list[BCCustomer]:
        """Return all customers (BC ``GET /customers``).

        Used where every customer is genuinely needed (e.g. building an id ->
        name lookup for enrichment elsewhere) — see
        ``get_customers_page`` for the paginated, filtered listing used by the
        customers directory itself.
        """
        raise NotImplementedError

    @abstractmethod
    def get_customers_page(
        self,
        *,
        search: str | None = None,
        status: CustomerStatus | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_CUSTOMERS_PAGE_SIZE,
    ) -> BCCustomerPage:
        """Return one page of customers, optionally filtered by ``search``/``status``.

        ``cursor`` is an opaque continuation token taken from a previous
        page's ``next_cursor``; when given, ``search``/``status``/``page_size``
        are ignored since the cursor already encodes the original query.
        """
        raise NotImplementedError

    @abstractmethod
    def get_projects(self) -> list[BCProject]:
        """Return all projects (BC ``GET /projects``).

        Used where every project is genuinely needed (e.g. building an id ->
        name lookup for enrichment elsewhere) — see ``get_projects_page`` for
        the paginated, filtered listing used by the projects directory itself.
        """
        raise NotImplementedError

    @abstractmethod
    def get_projects_page(
        self,
        *,
        search: str | None = None,
        project_type: str | None = None,
        entity_type: str | None = None,
        status: ProjectStatus | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    ) -> BCProjectPage:
        """Return one page of projects, optionally filtered.

        ``cursor`` is an opaque continuation token taken from a previous
        page's ``next_cursor``; when given, every other filter/``page_size``
        is ignored since the cursor already encodes the original query.
        """
        raise NotImplementedError

    @abstractmethod
    def get_customer_names(self, customer_ids: list[str]) -> dict[str, str]:
        """Return ``{customer_id: name}`` for just the given ids.

        A scoped alternative to ``get_customers()`` for cross-domain
        enrichment (e.g. resolving a page of projects' customer names)
        without paying for a full customer fetch — and, on the live client,
        without the company-wide projects fetch ``get_customers()`` does
        internally to compute ``active_project_count``, which callers that
        only want names never asked for.
        """
        raise NotImplementedError

    @abstractmethod
    def get_users(self) -> list[BCUser]:
        """Return all internal users (BC ``GET /users``)."""
        raise NotImplementedError

    @abstractmethod
    def get_user_tasks(self) -> list[BCUserTask]:
        """Return all user tasks (BC ``GET /userTasks``)."""
        raise NotImplementedError

    @abstractmethod
    def get_obligations(self) -> list[BCObligation]:
        """Return the obligation catalog (BC ``GET /obligations``)."""
        raise NotImplementedError

    @abstractmethod
    def get_project_obligations(self) -> list[BCProjectObligation]:
        """Return all project-obligation instances (BC ``GET /projectObligations``)."""
        raise NotImplementedError

    # -- Billing / Costs -------------------------------------------------------

    @abstractmethod
    def get_sales_invoice_headers(self) -> list[BCSalesInvoiceHeader]:
        """Return all sales-invoice headers (BC ``GET /salesInvoiceHeaders``)."""
        raise NotImplementedError

    @abstractmethod
    def get_sales_invoice_lines(self) -> list[BCSalesInvoiceLine]:
        """Return all sales-invoice lines (BC ``GET /salesInvoiceLines``).

        Each line links to its header on ``document_no``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_sales_cr_memo_headers(self) -> list[BCSalesCrMemoHeader]:
        """Return all sales credit-memo headers (BC ``GET /salesCrMemoHeaders``)."""
        raise NotImplementedError

    @abstractmethod
    def get_sales_cr_memo_lines(self) -> list[BCSalesCrMemoLine]:
        """Return all sales credit-memo lines (BC ``GET /salesCrMemoLines``).

        Each line links to its header on ``document_no``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_job_ledger_entries(self) -> list[BCJobLedgerEntry]:
        """Return job-ledger *usage* entries (BC ``GET /jobLedgerEntries``).

        Scoped to ``entryType eq 'Usage'`` (the cost side of a project).
        """
        raise NotImplementedError

    @abstractmethod
    def get_time_sheet_posting_entries(self) -> list[BCTimeSheetPostingEntry]:
        """Return all time-sheet posting entries (BC ``GET /timeSheetPostingEntries``)."""
        raise NotImplementedError

    @abstractmethod
    def get_resources(self) -> list[BCResource]:
        """Return all billable resources (BC ``GET /resources``)."""
        raise NotImplementedError
