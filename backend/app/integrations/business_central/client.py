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
    BCCustomerRefPage,
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

# Several readers below take an optional list of ids that scopes the read
# server-side. They all follow the same contract:
#
# * ``None``  -> every row (the historical behaviour, so existing callers that
#                pass nothing are unaffected).
# * ``[]``    -> no rows, returned without reading from Business Central at all.
#
# The empty-list case matters: treating it as "no filter" would silently turn a
# scoped read back into a company-wide one, which is exactly what these
# parameters exist to avoid.


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
        """Return one page of customers, optionally filtered by ``search``/``status``."""
        raise NotImplementedError

    @abstractmethod
    def get_customer_refs_page(
        self, *, page: int, page_size: int
    ) -> BCCustomerRefPage:
        """Return one name-ordered page of customer identities, plus the total.
        Ordering by name is what makes such a page cheap to build: a caller can
        pick its customers *before* aggregating anything about them (see
        ``BillingService.billing_for_customers``) instead of having to aggregate
        every customer just to discover which ones the page contains.
        """
        raise NotImplementedError

    @abstractmethod
    def get_projects(self, *, customer_ids: list[str] | None = None) -> list[BCProject]:
        """Return all projects (BC ``GET /projects``).

        Used where every project is genuinely needed (e.g. building an id ->
        name lookup for enrichment elsewhere) — see ``get_projects_page`` for
        the paginated, filtered listing used by the projects directory itself.

        ``customer_ids`` scopes the read to those customers' projects, following
        the shared filter contract above.
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
        customer_id: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    ) -> BCProjectPage:
        """Return one page of projects, optionally filtered.

        ``customer_id`` is pushed down as part of the query (not applied after
        the fact), so a customer's projects are found regardless of how many
        total projects the page window would otherwise cover. Known
        limitation: if a single customer had more projects than ``page_size``,
        only the first page would come back — there is no cursor support yet
        for combining a customer filter with pagination across pages.

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
        """Return all user tasks (BC ``GET /userTasks``).

        The live implementation currently returns ``[]`` (userTasks is
        excluded pending a decision on its BC source) rather than fetching
        real data — callers must treat an empty result as valid, not an error.
        """
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
    def get_sales_invoice_headers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCSalesInvoiceHeader]:
        """Return all sales-invoice headers (BC ``GET /salesInvoiceHeaders``).

        ``customer_ids`` scopes the read to invoices billed to those customers,
        following the shared filter contract above.
        """
        raise NotImplementedError

    @abstractmethod
    def get_sales_invoice_lines(
        self, *, document_nos: list[str] | None = None
    ) -> list[BCSalesInvoiceLine]:
        """Return all sales-invoice lines (BC ``GET /salesInvoiceLines``).

        Each line links to its header on ``document_no``. ``document_nos`` scopes
        the read to those documents' lines, following the shared filter contract
        above — the way to read only one set of customers' lines is to fetch
        their headers first and pass the document numbers through.
        """
        raise NotImplementedError

    @abstractmethod
    def get_sales_cr_memo_headers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCSalesCrMemoHeader]:
        """Return all sales credit-memo headers (BC ``GET /salesCrMemoHeaders``).

        ``customer_ids`` scopes the read to credit memos billed to those
        customers, following the shared filter contract above.
        """
        raise NotImplementedError

    @abstractmethod
    def get_sales_cr_memo_lines(
        self, *, document_nos: list[str] | None = None
    ) -> list[BCSalesCrMemoLine]:
        """Return all sales credit-memo lines (BC ``GET /salesCrMemoLines``).

        Each line links to its header on ``document_no``. ``document_nos`` scopes
        the read as in ``get_sales_invoice_lines``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_job_ledger_entries(
        self, *, project_ids: list[str] | None = None
    ) -> list[BCJobLedgerEntry]:
        """Return job-ledger *usage* entries (BC ``GET /jobLedgerEntries``).

        Scoped to ``entryType eq 'Usage'`` (the cost side of a project).
        ``project_ids`` narrows that further to those projects' entries,
        following the shared filter contract above.
        """
        raise NotImplementedError

    @abstractmethod
    def get_time_sheet_posting_entries(
        self, *, project_ids: list[str] | None = None
    ) -> list[BCTimeSheetPostingEntry]:
        """Return all time-sheet posting entries (BC ``GET /timeSheetPostingEntries``).

        ``project_ids`` scopes the read to those projects' entries, following the
        shared filter contract above. Note this entity carries no ``jobNo``: the
        project is referenced by ``documentNo`` (see the live implementation).
        """
        raise NotImplementedError

    @abstractmethod
    def get_resources(self) -> list[BCResource]:
        """Return all billable resources (BC ``GET /resources``)."""
        raise NotImplementedError
