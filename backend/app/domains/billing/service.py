"""Business logic for the billing (Facturación / Costes) domain.

Everything is aggregated **read-only** from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port;
nothing is persisted. The financial model (confirmed with the product owner):

* **Income / billing** = sales-invoice line amounts **minus** credit-memo line
  amounts. Credit memos are *facturas rectificativas* that reduce billing — they
  are never a cost.
* **Cost** = ``jobLedgerEntries`` usage cost (``total_cost_lcy``) only.
* **Hours** = ``timeSheetPostingEntries`` quantity, rolled up per project.

A sales line links to its header on ``document_no``; the header carries the
customer, so per-customer billing needs the header→customer map, while
per-project billing/cost/hours group on the line/entry ``project_id`` (BC
``jobNo``).
"""

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import logger
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomerRef,
    BCJobLedgerEntry,
    BCProject,
    BCSalesCrMemoLine,
    BCSalesInvoiceLine,
    BCTimeSheetPostingEntry,
)

from .schemas import (
    CustomerBillingGroupResponse,
    CustomerBillingResponse,
    ProjectBillingResponse,
)

# Monetary/quantity values are rounded to this many decimals in the responses.
#
# Amounts are aggregated as ``float`` (BC serializes them as JSON numbers and the
# codebase has no ``Decimal`` anywhere). That is fine for these read-only display
# KPIs, but if billing ever needs to reconcile against formal accounting, move to
# ``Decimal`` from the integration layer up (DTO fields, this aggregation, and the
# API schemas) to avoid floating-point drift.
_MONEY_DECIMALS = 2


def _rollup(
    projects: list[ProjectBillingResponse],
    value: Callable[[ProjectBillingResponse], float | None],
) -> float | None:
    """Sum a per-project column up to its customer, propagating unavailability.

    A ``None`` on any child means the column's Business Central source could not
    be read (see :meth:`BillingService._optional_totals`), so the customer total
    is unknown too — summing it as 0.0 would report a total that is simply wrong.

    This only covers customers that *have* project rows. A customer with none
    (billing attributed through its invoice headers but no project-attributed
    lines) has no child to propagate from, so the caller must not call this at
    all when the column's source is unavailable — see the ``*_available`` gates
    in :meth:`BillingService.billing_by_customer_grouped`.
    """
    values = [value(p) for p in projects]
    if any(v is None for v in values):
        return None
    return round(sum(v for v in values if v is not None), _MONEY_DECIMALS)


class BillingService:
    """Aggregate the firm's billing and costs from Business Central."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        # ``db`` is accepted for signature symmetry with the other domains'
        # services (and the DI wiring); billing never touches the database.
        self.db = db
        self.bc_client = bc_client

    def billing_by_customer(
        self,
        *,
        invoice_lines: list[BCSalesInvoiceLine] | None = None,
        cr_memo_lines: list[BCSalesCrMemoLine] | None = None,
    ) -> list[CustomerBillingResponse]:
        """Return net billing per customer (invoices minus credit memos).
        when omitted they are fetched from Business Central.
        """
        if invoice_lines is None:
            invoice_lines = self.bc_client.get_sales_invoice_lines()
        if cr_memo_lines is None:
            cr_memo_lines = self.bc_client.get_sales_cr_memo_lines()

        invoice_customer = {
            h.document_no: h.customer_id
            for h in self.bc_client.get_sales_invoice_headers()
        }
        cr_memo_customer = {
            h.document_no: h.customer_id
            for h in self.bc_client.get_sales_cr_memo_headers()
        }

        net_by_customer: dict[str, float] = {}
        for line in invoice_lines:
            customer_id = invoice_customer.get(line.document_no)
            if customer_id:
                net_by_customer[customer_id] = (
                    net_by_customer.get(customer_id, 0.0) + line.line_amount
                )
        for line in cr_memo_lines:
            customer_id = cr_memo_customer.get(line.document_no)
            if customer_id:
                net_by_customer[customer_id] = (
                    net_by_customer.get(customer_id, 0.0) - line.line_amount
                )

        names = self.bc_client.get_customer_names(list(net_by_customer))
        results = [
            CustomerBillingResponse(
                customer_id=customer_id,
                customer_name=names.get(customer_id, customer_id),
                net_billed=round(net, _MONEY_DECIMALS),
            )
            for customer_id, net in net_by_customer.items()
        ]
        results.sort(key=lambda r: r.net_billed, reverse=True)
        return results

    def billing_by_project(
        self,
        *,
        invoice_lines: list[BCSalesInvoiceLine] | None = None,
        cr_memo_lines: list[BCSalesCrMemoLine] | None = None,
        projects: list[BCProject] | None = None,
    ) -> list[ProjectBillingResponse]:
        """Return net billing, usage cost and logged hours per project.
        Groups on the line/entry ``project_id`` (BC ``jobNo``); lines with no
        project are excluded from the per-project billing (they still count in
        ``billing_by_customer``). Ordered by billing desc. When omitted they are
        fetched from Business Central.
        """
        if invoice_lines is None:
            invoice_lines = self.bc_client.get_sales_invoice_lines()
        if cr_memo_lines is None:
            cr_memo_lines = self.bc_client.get_sales_cr_memo_lines()
        if projects is None:
            projects = self.bc_client.get_projects()

        rows, _, _ = self._project_rows(invoice_lines, cr_memo_lines, projects)
        return rows

    def _project_rows(
        self,
        invoice_lines: list[BCSalesInvoiceLine],
        cr_memo_lines: list[BCSalesCrMemoLine],
        projects: list[BCProject],
    ) -> tuple[list[ProjectBillingResponse], bool, bool]:
        """Build the per-project rows, reporting which optional sources loaded.

        Backs :meth:`billing_by_project` (which needs only the rows) and
        :meth:`billing_by_customer_grouped`, which needs the two availability
        flags as well: a customer with no project rows has no child ``None`` to
        propagate, so it cannot infer a column's unavailability from the rows.
        """
        billed: dict[str, float] = {}
        for line in invoice_lines:
            if line.project_id:
                billed[line.project_id] = (
                    billed.get(line.project_id, 0.0) + line.line_amount
                )
        for line in cr_memo_lines:
            if line.project_id:
                billed[line.project_id] = (
                    billed.get(line.project_id, 0.0) - line.line_amount
                )

        # Cost and hours each come from their own BC entity, which may not be
        # enabled on the tenant. When one is unavailable its column degrades to
        # ``None`` (see ``_optional_totals``) rather than to 0.0, which would be
        # indistinguishable from a project that genuinely has no cost/hours.
        cost = self._optional_totals(
            "jobLedgerEntries",
            self.bc_client.get_job_ledger_entries,
            lambda entry: entry.total_cost_lcy,
        )
        hours = self._optional_totals(
            "timeSheetPostingEntries",
            self.bc_client.get_time_sheet_posting_entries,
            lambda entry: entry.quantity,
        )

        project_ids = set(billed) | set(cost or {}) | set(hours or {})
        names = {p.id: p.name for p in projects}
        results = [
            ProjectBillingResponse(
                project_id=project_id,
                project_name=names.get(project_id, project_id),
                billed=round(billed.get(project_id, 0.0), _MONEY_DECIMALS),
                cost=(
                    None
                    if cost is None
                    else round(cost.get(project_id, 0.0), _MONEY_DECIMALS)
                ),
                hours=(
                    None
                    if hours is None
                    else round(hours.get(project_id, 0.0), _MONEY_DECIMALS)
                ),
            )
            for project_id in project_ids
        ]
        results.sort(key=lambda r: r.billed, reverse=True)
        return results, cost is not None, hours is not None

    def _optional_totals(
        self,
        entity: str,
        fetch: Callable[[], list[BCJobLedgerEntry] | list[BCTimeSheetPostingEntry]],
        amount: Callable[[BCJobLedgerEntry | BCTimeSheetPostingEntry], float],
    ) -> dict[str, float] | None:
        """Total ``amount`` per project id, or ``None`` if ``entity`` is unavailable.

        The cost and hours columns each depend on their own Business Central
        entity. Those may be absent or disabled on a given tenant, so a failure
        to read one degrades just that column instead of failing the whole
        billing aggregation. ``None`` (rather than an empty dict) is returned so
        callers can tell "this column could not be loaded" apart from "every
        project genuinely totals zero".

        ``HTTPException`` is re-raised rather than degraded: it is a deliberate
        HTTP outcome (e.g. a 404 or an auth failure), not an integration outage,
        and must not be masked as a missing column. This mirrors
        ``DashboardService._section``, which wraps this call from the outside.
        """
        try:
            entries = fetch()
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "Billing source %s unavailable; its column will report as missing",
                entity,
            )
            return None

        totals: dict[str, float] = {}
        for entry in entries:
            if entry.project_id:
                totals[entry.project_id] = (
                    totals.get(entry.project_id, 0.0) + amount(entry)
                )
        return totals

    def billing_by_customer_grouped(
        self,
        *,
        invoice_lines: list[BCSalesInvoiceLine] | None = None,
        cr_memo_lines: list[BCSalesCrMemoLine] | None = None,
        projects: list[BCProject] | None = None,
    ) -> list[CustomerBillingGroupResponse]:
        """Return each customer with its per-project billing nested underneath.

        Folds :meth:`billing_by_customer` and :meth:`billing_by_project` into one
        hierarchical result for the dashboard's unified accordion table: the
        customer is the parent (authoritative net billing) and its projects the
        children (billing, usage cost, hours). Each customer's ``cost``/``hours``
        are the sum over its own projects, or ``None`` when that column's
        Business Central source could not be read — including for a customer with
        no project rows at all, which is why the availability flags come straight
        from :meth:`_project_rows`. Customers are ordered by net billing desc
        and, within each, projects keep the billing-desc order
        :meth:`billing_by_project` already applies.

        A customer appears if it has net billing **or** at least one project with
        billing/cost/hours, so customers whose only activity is unbilled project
        cost are not dropped. A project whose ``jobNo`` matches no known project
        (so its customer is unknown) is grouped under ``"" / "Sin cliente"``
        rather than silently discarded.

        ``invoice_lines``/``cr_memo_lines``/``projects`` may be passed in when a
        caller has already fetched them (the dashboard shares them across its KPI
        and this table); when omitted they are fetched from Business Central.
        """
        if invoice_lines is None:
            invoice_lines = self.bc_client.get_sales_invoice_lines()
        if cr_memo_lines is None:
            cr_memo_lines = self.bc_client.get_sales_cr_memo_lines()
        if projects is None:
            projects = self.bc_client.get_projects()

        by_customer = self.billing_by_customer(
            invoice_lines=invoice_lines, cr_memo_lines=cr_memo_lines
        )
        # ``_project_rows`` rather than ``billing_by_project`` because the
        # customer rollups need to know whether the cost/hours sources loaded,
        # not just whether any project row happened to carry a ``None``.
        by_project, cost_available, hours_available = self._project_rows(
            invoice_lines, cr_memo_lines, projects
        )

        net_by_customer = {c.customer_id: c.net_billed for c in by_customer}
        project_customer = {p.id: p.customer_id for p in projects}

        # Group the per-project rows under their owning customer. A project with
        # no known owner lands under the "" key (surfaced as "Sin cliente").
        projects_by_customer: dict[str, list[ProjectBillingResponse]] = {}
        for project in by_project:
            customer_id = project_customer.get(project.project_id, "")
            projects_by_customer.setdefault(customer_id, []).append(project)

        # A customer qualifies if it has net billing or at least one project.
        customer_ids = set(net_by_customer) | set(projects_by_customer)

        # Reuse the names billing_by_customer already resolved; only look up the
        # ones that appear solely through a project (rare) to avoid re-fetching.
        names = {c.customer_id: c.customer_name for c in by_customer}
        missing = [cid for cid in customer_ids if cid and cid not in names]
        if missing:
            names.update(self.bc_client.get_customer_names(missing))

        groups = [
            CustomerBillingGroupResponse(
                customer_id=customer_id,
                customer_name=(
                    names.get(customer_id, customer_id)
                    if customer_id
                    else "Sin cliente"
                ),
                net_billed=round(
                    net_by_customer.get(customer_id, 0.0), _MONEY_DECIMALS
                ),
                cost=(
                    _rollup(
                        projects_by_customer.get(customer_id, []), lambda p: p.cost
                    )
                    if cost_available
                    else None
                ),
                hours=(
                    _rollup(
                        projects_by_customer.get(customer_id, []), lambda p: p.hours
                    )
                    if hours_available
                    else None
                ),
                projects=projects_by_customer.get(customer_id, []),
            )
            for customer_id in customer_ids
        ]
        groups.sort(key=lambda g: g.net_billed, reverse=True)
        return groups

    def billing_for_customers(
        self, customer_refs: list[BCCustomerRef]
    ) -> list[CustomerBillingGroupResponse]:
        """Return the same grouped breakdown for **only** the given customers.

        The page-scoped counterpart to :meth:`billing_by_customer_grouped`. That
        method aggregates the whole company because it has to: it orders by net
        billing, and nobody can name the top ten billers without totalling
        everyone first. This one is handed its customers up front (see
        ``BusinessCentralClient.get_customer_refs_page``), so every Business
        Central read below is filtered down to them, and the cost of a page stops
        scaling with the size of the ledger.

        The reads cascade — headers for these customers give both the
        ``document_no`` → customer map *and* the exact documents whose lines to
        ask for; the customers' projects give the ids to scope cost and hours to:

        1. ``salesInvoiceHeaders`` / ``salesCrMemoHeaders`` by ``customer_ids``
        2. ``salesInvoiceLines`` / ``salesCrMemoLines`` by those document numbers
        3. ``projects`` by ``customer_ids``
        4. ``jobLedgerEntries`` / ``timeSheetPostingEntries`` by those project ids

        Groups come back in ``customer_refs`` order (the caller's, already
        name-ordered) and names come from the refs, so no name lookup is needed.

        Three differences from the company-wide method, all consequences of
        working from an authoritative customer list rather than from whatever the
        ledger happens to mention:

        * A customer with no activity at all is still returned, reading ``0.0``,
          instead of being absent.
        * Every one of the customer's projects gets a row, not just those with
          billing/cost/hours — so some rows read ``0.0`` too.
        * A project's ``billed`` counts only lines on **that customer's own**
          invoices. Grouping purely by ``jobNo`` (as the company-wide method
          does) can file an amount invoiced to another customer under this one,
          which is not a number a per-customer table should show.

        There is likewise no ``"Sin cliente"`` bucket: customers are enumerated
        authoritatively here, and a line whose ``jobNo`` matches none of the
        customer's projects still counts in that customer's net through its
        header.
        """
        if not customer_refs:
            return []

        customer_ids = [ref.id for ref in customer_refs]

        invoice_headers = self.bc_client.get_sales_invoice_headers(
            customer_ids=customer_ids
        )
        cr_memo_headers = self.bc_client.get_sales_cr_memo_headers(
            customer_ids=customer_ids
        )
        invoice_lines = self.bc_client.get_sales_invoice_lines(
            document_nos=[header.document_no for header in invoice_headers]
        )
        cr_memo_lines = self.bc_client.get_sales_cr_memo_lines(
            document_nos=[header.document_no for header in cr_memo_headers]
        )

        projects = self.bc_client.get_projects(customer_ids=customer_ids)
        project_ids = [project.id for project in projects]

        # Same degrade-per-column contract as the company-wide path: a tenant
        # without one of these entities reports that column as unknown rather
        # than as zero. With no projects on the page both reads short-circuit to
        # an empty result (see the port's filter contract), so the totals are a
        # genuine 0.0 rather than an unverifiable one.
        cost = self._optional_totals(
            "jobLedgerEntries",
            lambda: self.bc_client.get_job_ledger_entries(project_ids=project_ids),
            lambda entry: entry.total_cost_lcy,
        )
        hours = self._optional_totals(
            "timeSheetPostingEntries",
            lambda: self.bc_client.get_time_sheet_posting_entries(
                project_ids=project_ids
            ),
            lambda entry: entry.quantity,
        )

        document_customer = {
            **{h.document_no: h.customer_id for h in invoice_headers},
            **{h.document_no: h.customer_id for h in cr_memo_headers},
        }

        # One pass over both line sets: credit memos are the same amounts with
        # the opposite sign, feeding the customer's net and its project's billing
        # at once.
        net_by_customer: dict[str, float] = {}
        billed_by_project: dict[str, float] = {}
        for lines, sign in ((invoice_lines, 1.0), (cr_memo_lines, -1.0)):
            for line in lines:
                amount = sign * line.line_amount
                customer_id = document_customer.get(line.document_no)
                if customer_id:
                    net_by_customer[customer_id] = (
                        net_by_customer.get(customer_id, 0.0) + amount
                    )
                if line.project_id:
                    billed_by_project[line.project_id] = (
                        billed_by_project.get(line.project_id, 0.0) + amount
                    )

        rows_by_customer: dict[str, list[ProjectBillingResponse]] = {}
        for project in projects:
            rows_by_customer.setdefault(project.customer_id, []).append(
                ProjectBillingResponse(
                    project_id=project.id,
                    project_name=project.name,
                    billed=round(
                        billed_by_project.get(project.id, 0.0), _MONEY_DECIMALS
                    ),
                    cost=(
                        None
                        if cost is None
                        else round(cost.get(project.id, 0.0), _MONEY_DECIMALS)
                    ),
                    hours=(
                        None
                        if hours is None
                        else round(hours.get(project.id, 0.0), _MONEY_DECIMALS)
                    ),
                )
            )
        # Billing desc within each customer, matching billing_by_project's order.
        for rows in rows_by_customer.values():
            rows.sort(key=lambda row: row.billed, reverse=True)

        return [
            CustomerBillingGroupResponse(
                customer_id=ref.id,
                customer_name=ref.name,
                net_billed=round(net_by_customer.get(ref.id, 0.0), _MONEY_DECIMALS),
                cost=(
                    _rollup(rows_by_customer.get(ref.id, []), lambda p: p.cost)
                    if cost is not None
                    else None
                ),
                hours=(
                    _rollup(rows_by_customer.get(ref.id, []), lambda p: p.hours)
                    if hours is not None
                    else None
                ),
                projects=rows_by_customer.get(ref.id, []),
            )
            for ref in customer_refs
        ]
