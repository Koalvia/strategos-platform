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

from .schemas import CustomerBillingResponse, ProjectBillingResponse

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
