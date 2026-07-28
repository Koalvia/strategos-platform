"""Fixture-backed Business Central client.

:class:`MockBusinessCentralClient` implements the :class:`BusinessCentralClient`
port by reading committed JSON fixtures under ``fixtures/``. It performs no
network I/O and needs no credentials, so downstream product features (#6–#17)
can be built and demoed against a stable contract before real BC access exists.

Fixtures are loaded and validated into the transport DTOs once at import time;
every method returns a fresh copy of the validated list so callers cannot mutate
shared fixture state.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import TypeAdapter

from app.integrations.business_central.client import (
    DEFAULT_CUSTOMERS_PAGE_SIZE,
    DEFAULT_PROJECTS_PAGE_SIZE,
    BusinessCentralClient,
)
from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerPage,
    BCCustomerRef,
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

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(filename: str, model: type) -> list:
    """Read ``fixtures/<filename>`` and validate it into a list of ``model``."""
    raw = json.loads((_FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return TypeAdapter(list[model]).validate_python(raw)


# Validate every fixture once at import so a malformed fixture fails loudly and
# early rather than on the first request.
_CUSTOMERS = _load("customers.json", BCCustomer)
_PROJECTS = _load("projects.json", BCProject)
_USERS = _load("users.json", BCUser)
_USER_TASKS = _load("user_tasks.json", BCUserTask)
_OBLIGATIONS = _load("obligations.json", BCObligation)
_PROJECT_OBLIGATIONS = _load("project_obligations.json", BCProjectObligation)
_SALES_INVOICE_HEADERS = _load("sales_invoice_headers.json", BCSalesInvoiceHeader)
_SALES_INVOICE_LINES = _load("sales_invoice_lines.json", BCSalesInvoiceLine)
_SALES_CR_MEMO_HEADERS = _load("sales_cr_memo_headers.json", BCSalesCrMemoHeader)
_SALES_CR_MEMO_LINES = _load("sales_cr_memo_lines.json", BCSalesCrMemoLine)
# Fixture is pre-filtered to ``entryType == 'Usage'`` rows, mirroring the
# server-side ``$filter`` the live client applies (see get_job_ledger_entries).
_JOB_LEDGER_ENTRIES = _load("job_ledger_entries.json", BCJobLedgerEntry)
_TIME_SHEET_POSTING_ENTRIES = _load(
    "time_sheet_posting_entries.json", BCTimeSheetPostingEntry
)
_RESOURCES = _load("resources.json", BCResource)

_T = TypeVar("_T")


def _filtered(
    rows: list[_T], ids: list[str] | None, key: Callable[[_T], str | None]
) -> list[_T]:
    """Apply the port's shared id-filter contract to a fixture list.

    ``None`` returns every row, an empty list returns none, and otherwise only
    rows whose ``key`` is among ``ids`` — the in-memory equivalent of the
    server-side ``$filter`` the live client pushes down.
    """
    if ids is None:
        return list(rows)
    wanted = set(ids)
    return [row for row in rows if key(row) in wanted]


class MockBusinessCentralClient(BusinessCentralClient):
    """A :class:`BusinessCentralClient` backed by committed JSON fixtures."""

    def get_customers(self) -> list[BCCustomer]:
        return list(_CUSTOMERS)

    def get_customers_page(
        self,
        *,
        search: str | None = None,
        status: CustomerStatus | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_CUSTOMERS_PAGE_SIZE,
    ) -> BCCustomerPage:
        """Paginate the fixture list; ``cursor`` is just a stringified offset."""
        customers = list(_CUSTOMERS)

        if search:
            needle = search.casefold()
            customers = [
                c
                for c in customers
                if needle in c.name.casefold() or needle in c.nif.casefold()
            ]

        if status is not None:
            customers = [c for c in customers if c.status is status]

        offset = int(cursor) if cursor else 0
        page = customers[offset : offset + page_size]
        next_offset = offset + page_size
        next_cursor = str(next_offset) if next_offset < len(customers) else None

        return BCCustomerPage(items=page, next_cursor=next_cursor)

    def get_customer_refs_page(
        self, *, page: int, page_size: int
    ) -> BCCustomerRefPage:
        """Slice the fixture list by name, mirroring BC's ``$orderby``/``$top``/``$skip``."""
        ordered = sorted(_CUSTOMERS, key=lambda c: c.name)
        start = max(page - 1, 0) * page_size
        return BCCustomerRefPage(
            items=[
                BCCustomerRef(id=c.id, name=c.name)
                for c in ordered[start : start + page_size]
            ],
            total_count=len(_CUSTOMERS),
        )

    def get_projects(self, *, customer_ids: list[str] | None = None) -> list[BCProject]:
        return _filtered(_PROJECTS, customer_ids, lambda p: p.customer_id)

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
        """Paginate the fixture list; ``cursor`` is just a stringified offset."""
        projects = list(_PROJECTS)

        if search:
            needle = search.casefold()
            projects = [p for p in projects if needle in p.name.casefold()]

        if customer_id is not None:
            projects = [p for p in projects if p.customer_id == customer_id]

        if project_type is not None:
            wanted = project_type.casefold()
            projects = [
                p for p in projects if (p.project_type or "").casefold() == wanted
            ]

        if entity_type is not None:
            wanted = entity_type.casefold()
            projects = [
                p for p in projects if (p.entity_type or "").casefold() == wanted
            ]

        if status is not None:
            projects = [p for p in projects if p.status is status]

        offset = int(cursor) if cursor else 0
        page = projects[offset : offset + page_size]
        next_offset = offset + page_size
        next_cursor = str(next_offset) if next_offset < len(projects) else None

        return BCProjectPage(items=page, next_cursor=next_cursor)

    def get_customer_names(self, customer_ids: list[str]) -> dict[str, str]:
        wanted = set(customer_ids)
        return {c.id: c.name for c in _CUSTOMERS if c.id in wanted}

    def get_users(self) -> list[BCUser]:
        return list(_USERS)

    def get_user_tasks(self) -> list[BCUserTask]:
        return list(_USER_TASKS)

    def get_obligations(self) -> list[BCObligation]:
        return list(_OBLIGATIONS)

    def get_project_obligations(self) -> list[BCProjectObligation]:
        return list(_PROJECT_OBLIGATIONS)

    # -- Billing / Costs -------------------------------------------------------

    def get_sales_invoice_headers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCSalesInvoiceHeader]:
        return _filtered(_SALES_INVOICE_HEADERS, customer_ids, lambda h: h.customer_id)

    def get_sales_invoice_lines(
        self, *, document_nos: list[str] | None = None
    ) -> list[BCSalesInvoiceLine]:
        return _filtered(_SALES_INVOICE_LINES, document_nos, lambda line: line.document_no)

    def get_sales_cr_memo_headers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCSalesCrMemoHeader]:
        return _filtered(_SALES_CR_MEMO_HEADERS, customer_ids, lambda h: h.customer_id)

    def get_sales_cr_memo_lines(
        self, *, document_nos: list[str] | None = None
    ) -> list[BCSalesCrMemoLine]:
        return _filtered(_SALES_CR_MEMO_LINES, document_nos, lambda line: line.document_no)

    def get_job_ledger_entries(
        self, *, project_ids: list[str] | None = None
    ) -> list[BCJobLedgerEntry]:
        return _filtered(_JOB_LEDGER_ENTRIES, project_ids, lambda e: e.project_id)

    def get_time_sheet_posting_entries(
        self, *, project_ids: list[str] | None = None
    ) -> list[BCTimeSheetPostingEntry]:
        return _filtered(_TIME_SHEET_POSTING_ENTRIES, project_ids, lambda e: e.project_id)

    def get_resources(self) -> list[BCResource]:
        return list(_RESOURCES)
