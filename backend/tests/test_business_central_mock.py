"""Tests for the Business Central integration port, mock client and DI switch.

These cover the seam added by issue #4: a fixture-backed
``MockBusinessCentralClient`` implementing the ``BusinessCentralClient`` port,
plus the ``get_business_central_client`` provider gated on
``settings.BUSINESS_CENTRAL_MODE``. No network or credentials are involved.
"""

import pytest

from app.core.config import settings
from app.core.dependencies import get_business_central_client
from app.integrations.business_central import (
    BusinessCentralClient,
    MockBusinessCentralClient,
)
from app.integrations.business_central.models import (
    BCCustomer,
    BCJobLedgerEntry,
    BCObligation,
    BCProject,
    BCProjectObligation,
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
    TaskStatus,
)


@pytest.fixture
def client() -> MockBusinessCentralClient:
    return MockBusinessCentralClient()


@pytest.mark.unit
def test_mock_implements_port(client):
    """The mock is an instance of the abstract port."""
    assert isinstance(client, BusinessCentralClient)


@pytest.mark.unit
def test_port_defines_all_expected_methods():
    """The port declares one abstract method per BC endpoint, plus the
    paginated ``get_customers_page``/``get_projects_page`` (and the scoped
    ``get_customer_names`` lookup) used by the directory listings."""
    expected = {
        "get_customers",
        "get_customers_page",
        "get_projects",
        "get_projects_page",
        "get_customer_names",
        "get_users",
        "get_user_tasks",
        "get_obligations",
        "get_project_obligations",
        "get_sales_invoice_headers",
        "get_sales_invoice_lines",
        "get_sales_cr_memo_headers",
        "get_sales_cr_memo_lines",
        "get_job_ledger_entries",
        "get_time_sheet_posting_entries",
        "get_resources",
    }
    assert expected <= BusinessCentralClient.__abstractmethods__


@pytest.mark.unit
def test_get_customers_count_type_and_active_split(client):
    """Exactly 14 customers (13 active, 1 inactive), all typed."""
    customers = client.get_customers()
    assert len(customers) == 14
    assert all(isinstance(c, BCCustomer) for c in customers)

    active = [c for c in customers if c.status is CustomerStatus.active]
    inactive = [c for c in customers if c.status is CustomerStatus.inactive]
    assert len(active) == 13
    assert len(inactive) == 1
    assert inactive[0].name == "Clínica Dental Ordino SL"


@pytest.mark.unit
def test_get_customers_page_slices_and_sets_next_cursor(client):
    """A page smaller than the fixture list returns a ``next_cursor``."""
    page = client.get_customers_page(page_size=3)
    assert len(page.items) == 3
    assert page.next_cursor is not None

    next_page = client.get_customers_page(page_size=3, cursor=page.next_cursor)
    assert len(next_page.items) == 3
    assert {c.id for c in page.items}.isdisjoint({c.id for c in next_page.items})


@pytest.mark.unit
def test_get_customers_page_last_page_has_no_next_cursor(client):
    """Once every customer has been returned, ``next_cursor`` is ``None``."""
    page = client.get_customers_page(page_size=100)
    assert len(page.items) == 14
    assert page.next_cursor is None


@pytest.mark.unit
def test_get_customers_page_filters_by_search(client):
    """``search`` matches name or NIF, case-insensitively, across the fixtures."""
    page = client.get_customers_page(search="puigcerdà", page_size=100)
    assert [c.name for c in page.items] == ["Fontaneria Puigcerdà SL"]

    page = client.get_customers_page(search="g567890", page_size=100)
    assert [c.nif for c in page.items] == ["G567890"]


@pytest.mark.unit
def test_get_customers_page_filters_by_status(client):
    """``status`` keeps only customers in that state."""
    page = client.get_customers_page(status=CustomerStatus.inactive, page_size=100)
    assert len(page.items) == 1
    assert page.items[0].name == "Clínica Dental Ordino SL"

    page = client.get_customers_page(status=CustomerStatus.active, page_size=100)
    assert len(page.items) == 13


@pytest.mark.unit
def test_get_users_count_type_and_emails(client):
    """6 users, all typed, keyed by the agreed emails.

    ``BCUser`` has no ``role`` field: role comes from the local ``auth.User``
    row, never from Business Central (see ``app.domains.users.service``).
    """
    users = client.get_users()
    assert len(users) == 6
    assert all(isinstance(u, BCUser) for u in users)
    assert not hasattr(BCUser, "role") and "role" not in BCUser.model_fields

    names = {u.name for u in users}
    assert names == {
        "Marc Solé",
        "Anna Ferrer",
        "Laura Puig",
        "Jordi Vila",
        "Núria Camps",
        "Pol Ribas",
    }
    assert all(u.email.endswith("@estrategos.ad") for u in users)


@pytest.mark.unit
def test_get_projects_count_type_and_active_split(client):
    """18 projects, one inactive (belonging to the inactive customer)."""
    projects = client.get_projects()
    assert len(projects) == 18
    assert all(isinstance(p, BCProject) for p in projects)

    active = [p for p in projects if p.status is ProjectStatus.active]
    assert len(active) == 17


@pytest.mark.unit
def test_get_projects_page_slices_and_sets_next_cursor(client):
    """A page smaller than the fixture list returns a ``next_cursor``."""
    page = client.get_projects_page(page_size=5)
    assert len(page.items) == 5
    assert page.next_cursor is not None

    next_page = client.get_projects_page(page_size=5, cursor=page.next_cursor)
    assert len(next_page.items) == 5
    assert {p.id for p in page.items}.isdisjoint({p.id for p in next_page.items})


@pytest.mark.unit
def test_get_projects_page_last_page_has_no_next_cursor(client):
    """Once every project has been returned, ``next_cursor`` is ``None``."""
    page = client.get_projects_page(page_size=100)
    assert len(page.items) == 18
    assert page.next_cursor is None


@pytest.mark.unit
def test_get_projects_page_filters_by_search(client):
    """``search`` matches the project name, case-insensitively."""
    page = client.get_projects_page(search="LABORAL", page_size=100)
    assert [p.name for p in page.items] == ["Gestió laboral"]


@pytest.mark.unit
def test_get_projects_page_filters_by_type_and_entity(client):
    """``project_type``/``entity_type`` match case-insensitively, exact value."""
    page = client.get_projects_page(project_type="iguala trimestral", page_size=100)
    assert {p.id for p in page.items} == {"proj-003", "proj-004", "proj-011"}

    page = client.get_projects_page(entity_type="Persona física", page_size=100)
    assert {p.id for p in page.items} == {"proj-003", "proj-004"}


@pytest.mark.unit
def test_get_projects_page_filters_by_status(client):
    """``status`` keeps only projects in that state."""
    page = client.get_projects_page(status=ProjectStatus.inactive, page_size=100)
    assert [p.id for p in page.items] == ["proj-012"]


@pytest.mark.unit
def test_get_customer_names_returns_only_requested_ids(client):
    """``get_customer_names`` scopes the lookup to just the given ids."""
    names = client.get_customer_names(["cust-001", "cust-005"])
    assert names == {
        "cust-001": "Fontaneria Puigcerdà SL",
        "cust-005": "Fundació Cultural Andorrana",
    }


@pytest.mark.unit
def test_get_customer_names_empty_ids_returns_empty_dict(client):
    """An empty id list returns an empty dict, no error."""
    assert client.get_customer_names([]) == {}


@pytest.mark.unit
def test_get_obligations_catalog(client):
    """The 10 obligation types are present."""
    obligations = client.get_obligations()
    assert len(obligations) == 10
    assert all(isinstance(o, BCObligation) for o in obligations)

    names = {o.name for o in obligations}
    assert names == {
        "Dipòsit de comptes (CCAA)",
        "IS",
        "IRPF",
        "IGI",
        "IRNR",
        "Bonificació IIEA",
        "Bonificació ITP/IGI",
        "Treballador per compte propi (CASS)",
        "Generació de factures",
        "Generació d'informes",
    }


@pytest.mark.unit
def test_get_user_tasks_count_type_and_status_split(client):
    """15 tasks split 10 pending / 3 in progress / 2 done, matching the board."""
    tasks = client.get_user_tasks()
    assert len(tasks) == 15
    assert all(isinstance(t, BCUserTask) for t in tasks)

    by_status = {status: 0 for status in TaskStatus}
    for task in tasks:
        by_status[task.status] += 1
    assert by_status[TaskStatus.pending] == 10
    assert by_status[TaskStatus.in_progress] == 3
    assert by_status[TaskStatus.done] == 2


@pytest.mark.unit
def test_get_project_obligations_type(client):
    """Project-obligation instances are present and typed."""
    instances = client.get_project_obligations()
    assert len(instances) >= 6
    assert all(isinstance(i, BCProjectObligation) for i in instances)


@pytest.mark.unit
def test_ids_are_unique_across_each_collection(client):
    """Every entity has a stable, unique string id."""
    for items in (
        client.get_customers(),
        client.get_projects(),
        client.get_users(),
        client.get_user_tasks(),
        client.get_obligations(),
        client.get_project_obligations(),
    ):
        ids = [item.id for item in items]
        assert all(isinstance(i, str) and i for i in ids)
        assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_fixture_cross_references_resolve(client):
    """Every foreign key in the fixtures points at an existing entity."""
    customer_ids = {c.id for c in client.get_customers()}
    project_ids = {p.id for p in client.get_projects()}
    user_ids = {u.id for u in client.get_users()}
    obligation_ids = {o.id for o in client.get_obligations()}

    for project in client.get_projects():
        assert project.customer_id in customer_ids

    for task in client.get_user_tasks():
        assert task.project_id in project_ids
        assert task.assignee_id in user_ids

    for instance in client.get_project_obligations():
        assert instance.project_id in project_ids
        assert instance.obligation_id in obligation_ids


@pytest.mark.unit
def test_active_project_count_matches_active_projects(client):
    """Each customer's declared active_project_count matches its active projects."""
    projects = client.get_projects()
    for customer in client.get_customers():
        active = [
            p
            for p in projects
            if p.customer_id == customer.id and p.status is ProjectStatus.active
        ]
        # The inactive customer's single project is inactive, so its active count
        # is a display value that need not match; assert only for active customers.
        if customer.status is CustomerStatus.active:
            assert customer.active_project_count == len(active)


@pytest.mark.unit
def test_returned_lists_are_isolated_copies(client):
    """Mutating a returned list does not corrupt shared fixture state."""
    first = client.get_customers()
    first.clear()
    assert len(client.get_customers()) == 14


@pytest.mark.unit
def test_billing_getters_load_and_type_fixtures(client):
    """The seven billing/cost getters load their fixtures into the right DTOs."""
    invoice_headers = client.get_sales_invoice_headers()
    invoice_lines = client.get_sales_invoice_lines()
    cr_memo_headers = client.get_sales_cr_memo_headers()
    cr_memo_lines = client.get_sales_cr_memo_lines()
    job_ledger = client.get_job_ledger_entries()
    time_sheets = client.get_time_sheet_posting_entries()
    resources = client.get_resources()

    assert all(isinstance(h, BCSalesInvoiceHeader) for h in invoice_headers)
    assert all(isinstance(line, BCSalesInvoiceLine) for line in invoice_lines)
    assert all(isinstance(h, BCSalesCrMemoHeader) for h in cr_memo_headers)
    assert all(isinstance(line, BCSalesCrMemoLine) for line in cr_memo_lines)
    assert all(isinstance(e, BCJobLedgerEntry) for e in job_ledger)
    assert all(isinstance(e, BCTimeSheetPostingEntry) for e in time_sheets)
    assert all(isinstance(r, BCResource) for r in resources)

    # The job-ledger fixture is pre-filtered to usage entries (the cost side).
    assert job_ledger and all(e.entry_type == "Usage" for e in job_ledger)

    # A line ties back to its header on document_no, and a non-project line
    # (blank jobNo) is represented as project_id None.
    header_nos = {h.document_no for h in invoice_headers}
    assert all(line.document_no in header_nos for line in invoice_lines)
    assert any(line.project_id is None for line in invoice_lines)


@pytest.mark.unit
def test_billing_getters_return_isolated_copies(client):
    """Mutating a returned billing list does not corrupt shared fixture state."""
    first = client.get_sales_invoice_lines()
    count = len(first)
    first.clear()
    assert len(client.get_sales_invoice_lines()) == count


@pytest.mark.unit
def test_di_provider_returns_mock_in_mock_mode():
    """The DI provider returns the mock client when mode is 'mock'."""
    assert settings.BUSINESS_CENTRAL_MODE == "mock"
    provided = get_business_central_client()
    assert isinstance(provided, MockBusinessCentralClient)
    assert isinstance(provided, BusinessCentralClient)


@pytest.mark.unit
def test_di_provider_rejects_unknown_mode(monkeypatch):
    """An unsupported mode fails loudly rather than silently misbehaving."""
    monkeypatch.setattr(settings, "BUSINESS_CENTRAL_MODE", "bogus")
    with pytest.raises(RuntimeError):
        get_business_central_client()


@pytest.mark.unit
def test_di_provider_returns_live_in_live_mode(monkeypatch):
    """The DI provider returns the live client when mode is 'live'."""
    from app.core.dependencies import _live_business_central_client
    from app.integrations.business_central import LiveBusinessCentralClient

    _live_business_central_client.cache_clear()
    monkeypatch.setattr(settings, "BUSINESS_CENTRAL_MODE", "live")
    try:
        provided = get_business_central_client()
        assert isinstance(provided, LiveBusinessCentralClient)
        assert isinstance(provided, BusinessCentralClient)
        # Cached: the same instance is reused across requests.
        assert get_business_central_client() is provided
    finally:
        _live_business_central_client.cache_clear()
