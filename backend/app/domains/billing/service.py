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

from sqlalchemy.orm import Session

from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCProject,
    BCSalesCrMemoLine,
    BCSalesInvoiceLine,
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

        Lines are attributed to a customer through their header
        (``document_no`` → ``customer_id``); a line whose header is missing is
        skipped since it cannot be attributed. Ordered by net billing desc.

        ``invoice_lines``/``cr_memo_lines`` may be passed in when a caller has
        already fetched them (the dashboard aggregates both breakdowns in one
        request and reuses the lines across them); when omitted they are fetched
        from Business Central.
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
        ``billing_by_customer``). Ordered by billing desc.

        ``invoice_lines``/``cr_memo_lines``/``projects`` may be passed in when a
        caller has already fetched them (the dashboard reuses these across its
        two billing breakdowns and its projects KPI); when omitted they are
        fetched from Business Central.
        """
        if invoice_lines is None:
            invoice_lines = self.bc_client.get_sales_invoice_lines()
        if cr_memo_lines is None:
            cr_memo_lines = self.bc_client.get_sales_cr_memo_lines()
        if projects is None:
            projects = self.bc_client.get_projects()

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

        cost: dict[str, float] = {}
        for entry in self.bc_client.get_job_ledger_entries():
            if entry.project_id:
                cost[entry.project_id] = (
                    cost.get(entry.project_id, 0.0) + entry.total_cost_lcy
                )

        hours: dict[str, float] = {}
        for entry in self.bc_client.get_time_sheet_posting_entries():
            if entry.project_id:
                hours[entry.project_id] = (
                    hours.get(entry.project_id, 0.0) + entry.quantity
                )

        project_ids = set(billed) | set(cost) | set(hours)
        names = {p.id: p.name for p in projects}
        results = [
            ProjectBillingResponse(
                project_id=project_id,
                project_name=names.get(project_id, project_id),
                billed=round(billed.get(project_id, 0.0), _MONEY_DECIMALS),
                cost=round(cost.get(project_id, 0.0), _MONEY_DECIMALS),
                hours=round(hours.get(project_id, 0.0), _MONEY_DECIMALS),
            )
            for project_id in project_ids
        ]
        results.sort(key=lambda r: r.billed, reverse=True)
        return results

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
        are the sum over its own projects. Customers are ordered by net billing
        desc and, within each, projects keep the billing-desc order
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
        by_project = self.billing_by_project(
            invoice_lines=invoice_lines,
            cr_memo_lines=cr_memo_lines,
            projects=projects,
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
                cost=round(
                    sum(p.cost for p in projects_by_customer.get(customer_id, [])),
                    _MONEY_DECIMALS,
                ),
                hours=round(
                    sum(p.hours for p in projects_by_customer.get(customer_id, [])),
                    _MONEY_DECIMALS,
                ),
                projects=projects_by_customer.get(customer_id, []),
            )
            for customer_id in customer_ids
        ]
        groups.sort(key=lambda g: g.net_billed, reverse=True)
        return groups
