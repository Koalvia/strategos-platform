"""Tests for the billing (Facturación / Costes) domain.

Billing figures are aggregated read-only from Business Central; nothing is
persisted. These tests cover the aggregation math with a small purpose-built BC
client (so the expected numbers are obvious) and the two endpoints against the
fixture-backed mock client (the default DI mode).

Financial model under test:
* net billing = sales-invoice lines − credit-memo lines (credit memos are
  *facturas rectificativas*, never a cost);
* cost = ``jobLedgerEntries`` usage cost only;
* hours = ``timeSheetPostingEntries`` quantity, per project.
"""

from collections import Counter

import pytest

from app.domains.billing.service import BillingService
from app.integrations.business_central.models import (
    BCJobLedgerEntry,
    BCProject,
    BCSalesCrMemoHeader,
    BCSalesCrMemoLine,
    BCSalesInvoiceHeader,
    BCSalesInvoiceLine,
    BCTimeSheetPostingEntry,
    ProjectStatus,
)

BY_CUSTOMER_URL = "/api/v1/billing/by-customer"
BY_PROJECT_URL = "/api/v1/billing/by-project"


class _BillingBCClient:
    """A minimal BC client exposing just the billing/cost getters the service uses."""

    def __init__(
        self,
        *,
        invoice_headers=(),
        invoice_lines=(),
        cr_memo_headers=(),
        cr_memo_lines=(),
        job_ledger=(),
        time_sheets=(),
        projects=(),
    ):
        self._invoice_headers = list(invoice_headers)
        self._invoice_lines = list(invoice_lines)
        self._cr_memo_headers = list(cr_memo_headers)
        self._cr_memo_lines = list(cr_memo_lines)
        self._job_ledger = list(job_ledger)
        self._time_sheets = list(time_sheets)
        self._projects = list(projects)
        # Counts calls per getter so tests can assert what was (not) fetched.
        self.calls: Counter[str] = Counter()

    def get_sales_invoice_headers(self):
        self.calls["invoice_headers"] += 1
        return list(self._invoice_headers)

    def get_sales_invoice_lines(self):
        self.calls["invoice_lines"] += 1
        return list(self._invoice_lines)

    def get_sales_cr_memo_headers(self):
        self.calls["cr_memo_headers"] += 1
        return list(self._cr_memo_headers)

    def get_sales_cr_memo_lines(self):
        self.calls["cr_memo_lines"] += 1
        return list(self._cr_memo_lines)

    def get_job_ledger_entries(self):
        self.calls["job_ledger"] += 1
        return list(self._job_ledger)

    def get_time_sheet_posting_entries(self):
        self.calls["time_sheets"] += 1
        return list(self._time_sheets)

    def get_projects(self):
        self.calls["projects"] += 1
        return list(self._projects)

    def get_customer_names(self, customer_ids):
        # Deterministic stand-in names so the service's enrichment is exercised.
        return {cid: f"Customer {cid}" for cid in customer_ids}


def _project(project_id: str, name: str) -> BCProject:
    return BCProject(
        id=project_id,
        name=name,
        customer_id="cust-x",
        responsible="",
        technician="",
        status=ProjectStatus.active,
    )


@pytest.mark.unit
def test_billing_by_customer_nets_invoices_minus_credit_memos():
    """Net billing subtracts credit-memo lines from invoice lines, per customer."""
    bc = _BillingBCClient(
        invoice_headers=[
            BCSalesInvoiceHeader(document_no="INV-1", customer_id="c1"),
            BCSalesInvoiceHeader(document_no="INV-2", customer_id="c2"),
        ],
        invoice_lines=[
            BCSalesInvoiceLine(document_no="INV-1", line_amount=1000.0),
            BCSalesInvoiceLine(document_no="INV-1", line_amount=500.0),
            BCSalesInvoiceLine(document_no="INV-2", line_amount=300.0),
            # A line whose header is unknown is skipped (cannot attribute).
            BCSalesInvoiceLine(document_no="INV-missing", line_amount=999.0),
        ],
        cr_memo_headers=[BCSalesCrMemoHeader(document_no="CM-1", customer_id="c1")],
        cr_memo_lines=[BCSalesCrMemoLine(document_no="CM-1", line_amount=200.0)],
    )

    result = BillingService(None, bc).billing_by_customer()

    # c1 = 1500 − 200 = 1300; c2 = 300. Ordered by amount desc, names enriched.
    assert [(r.customer_id, r.customer_name, r.net_billed) for r in result] == [
        ("c1", "Customer c1", 1300.0),
        ("c2", "Customer c2", 300.0),
    ]


@pytest.mark.unit
def test_billing_by_project_combines_billing_cost_and_hours():
    """Per project: net billing (invoices − credit memos), usage cost, hours."""
    bc = _BillingBCClient(
        invoice_headers=[BCSalesInvoiceHeader(document_no="INV-1", customer_id="c1")],
        invoice_lines=[
            BCSalesInvoiceLine(document_no="INV-1", line_amount=2000.0, project_id="p1"),
            # Non-project line: counts for the customer, not for any project.
            BCSalesInvoiceLine(document_no="INV-1", line_amount=100.0, project_id=None),
        ],
        cr_memo_headers=[BCSalesCrMemoHeader(document_no="CM-1", customer_id="c1")],
        cr_memo_lines=[
            BCSalesCrMemoLine(document_no="CM-1", line_amount=500.0, project_id="p1"),
        ],
        job_ledger=[
            BCJobLedgerEntry(entry_no="J1", project_id="p1", total_cost_lcy=400.0),
            BCJobLedgerEntry(entry_no="J2", project_id="p1", total_cost_lcy=150.0),
            # A project with cost but no billing still appears.
            BCJobLedgerEntry(entry_no="J3", project_id="p2", total_cost_lcy=300.0),
        ],
        time_sheets=[
            BCTimeSheetPostingEntry(
                time_sheet_no="T1", project_id="p1", resource_no="r1", quantity=8.0
            ),
        ],
        projects=[_project("p1", "Project One"), _project("p2", "Project Two")],
    )

    result = {r.project_id: r for r in BillingService(None, bc).billing_by_project()}

    # p1: billed 2000 − 500 = 1500, cost 550, 8 hours.
    assert (result["p1"].billed, result["p1"].cost, result["p1"].hours) == (
        1500.0,
        550.0,
        8.0,
    )
    assert result["p1"].project_name == "Project One"
    # p2: no billing, cost 300, no hours.
    assert (result["p2"].billed, result["p2"].cost, result["p2"].hours) == (
        0.0,
        300.0,
        0.0,
    )


@pytest.mark.unit
def test_billing_by_project_falls_back_to_id_when_name_unknown():
    """A project id with no matching BC project uses the id as its name."""
    bc = _BillingBCClient(
        job_ledger=[
            BCJobLedgerEntry(entry_no="J1", project_id="ghost", total_cost_lcy=10.0)
        ],
        projects=[],
    )
    result = BillingService(None, bc).billing_by_project()
    assert result[0].project_id == "ghost"
    assert result[0].project_name == "ghost"


@pytest.mark.unit
def test_billing_by_customer_uses_prefetched_lines_without_refetching():
    """Passing lines in skips the line fetches (headers still come from BC)."""
    bc = _BillingBCClient(
        invoice_headers=[BCSalesInvoiceHeader(document_no="INV-1", customer_id="c1")],
        cr_memo_headers=[BCSalesCrMemoHeader(document_no="CM-1", customer_id="c1")],
    )
    result = BillingService(None, bc).billing_by_customer(
        invoice_lines=[BCSalesInvoiceLine(document_no="INV-1", line_amount=1000.0)],
        cr_memo_lines=[BCSalesCrMemoLine(document_no="CM-1", line_amount=200.0)],
    )

    assert result[0].net_billed == 800.0
    assert bc.calls["invoice_lines"] == 0
    assert bc.calls["cr_memo_lines"] == 0
    # Headers are not shareable with the per-project breakdown, so still fetched.
    assert bc.calls["invoice_headers"] == 1
    assert bc.calls["cr_memo_headers"] == 1


@pytest.mark.unit
def test_billing_by_project_uses_prefetched_lines_and_projects_without_refetching():
    """Passing lines/projects in skips those fetches (cost/hours still from BC)."""
    bc = _BillingBCClient(
        job_ledger=[
            BCJobLedgerEntry(entry_no="J1", project_id="p1", total_cost_lcy=400.0)
        ],
    )
    result = {
        r.project_id: r
        for r in BillingService(None, bc).billing_by_project(
            invoice_lines=[
                BCSalesInvoiceLine(
                    document_no="INV-1", line_amount=2000.0, project_id="p1"
                )
            ],
            cr_memo_lines=[],
            projects=[_project("p1", "Project One")],
        )
    }

    assert (result["p1"].billed, result["p1"].cost) == (2000.0, 400.0)
    assert result["p1"].project_name == "Project One"
    assert bc.calls["invoice_lines"] == 0
    assert bc.calls["cr_memo_lines"] == 0
    assert bc.calls["projects"] == 0
    # Cost/hours are not pre-fetched by callers, so they are still fetched once.
    assert bc.calls["job_ledger"] == 1
    assert bc.calls["time_sheets"] == 1


@pytest.mark.unit
def test_billing_methods_fetch_from_bc_when_no_data_passed():
    """With no injected data both methods fetch each of their lines/projects once."""
    bc = _BillingBCClient(
        invoice_headers=[BCSalesInvoiceHeader(document_no="INV-1", customer_id="c1")],
        invoice_lines=[BCSalesInvoiceLine(document_no="INV-1", line_amount=100.0)],
        projects=[_project("p1", "Project One")],
    )
    service = BillingService(None, bc)
    service.billing_by_customer()
    service.billing_by_project()

    assert bc.calls["invoice_lines"] == 2  # once per method (standalone router use)
    assert bc.calls["cr_memo_lines"] == 2
    assert bc.calls["projects"] == 1  # only billing_by_project fetches projects


# --------------------------------------------------------------------------- #
# Endpoints (against the fixture-backed mock client)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_by_customer_endpoint_returns_sorted_net_billing(client):
    """GET /billing/by-customer returns net billing per customer, highest first."""
    resp = client.get(BY_CUSTOMER_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body[0] == {
        "customer_id": "cust-001",
        "customer_name": "Fontaneria Puigcerdà SL",
        "net_billed": 3300.0,
    }
    amounts = [row["net_billed"] for row in body]
    assert amounts == sorted(amounts, reverse=True)


@pytest.mark.integration
def test_by_project_endpoint_returns_billing_cost_hours(client):
    """GET /billing/by-project returns billed/cost/hours per project."""
    resp = client.get(BY_PROJECT_URL)
    assert resp.status_code == 200
    body = resp.json()
    by_id = {row["project_id"]: row for row in body}
    assert by_id["proj-002"] == {
        "project_id": "proj-002",
        "project_name": "Gestió laboral",
        "billed": 2000.0,
        "cost": 900.0,
        "hours": 16.0,
    }
    billed = [row["billed"] for row in body]
    assert billed == sorted(billed, reverse=True)


@pytest.mark.auth
def test_billing_endpoints_require_authentication(db_session):
    """Without a verified user the billing endpoints refuse the request."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            assert unauth_client.get(BY_CUSTOMER_URL).status_code in (401, 403)
            assert unauth_client.get(BY_PROJECT_URL).status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_db, None)
