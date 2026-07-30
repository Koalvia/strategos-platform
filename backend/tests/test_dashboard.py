"""Tests for the read-only dashboard aggregation endpoints (issue #12).

The dashboard domain has no database model and no persistence — it only composes
the customers / projects / obligations / tasks / billing domains, all served from
the fixture-backed ``MockBusinessCentralClient`` (the default DI mode). Each
widget has its own endpoint so the frontend can load them granularly and in
parallel; these tests cover:

* the shape of each of the six endpoints,
* that each KPI is internally consistent with the underlying domain endpoint's
  count for the mock data (asserted against a frozen reference date for the
  obligation-derived numbers),
* the "Próximas obligaciones" list (upcoming + overdue, ordered by due date),
* the paginated "Facturación" table — its envelope, its name-ordered paging, the
  per-customer grouping, and that a page reads **only its own customers** out of
  Business Central rather than aggregating the whole company and slicing, and
* that an unavailable Business Central source degrades only its own endpoint —
  to ``null`` with a 200 — while a real ``HTTPException`` still propagates.

The obligation-derived numbers are computed against a reference "today"; tests
freeze it by overriding the ``get_reference_date`` dependency so assertions do not
depend on the real clock.
"""

from collections import Counter
from datetime import date
from math import ceil

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_business_central_client
from app.db.session import get_db
from app.domains.dashboard.router import get_reference_date
from app.domains.dashboard.service import DashboardService
from app.domains.obligations.router import (
    get_reference_date as obligations_reference_date,
)
from app.integrations.business_central.mock_client import MockBusinessCentralClient
from app.main import app

ACTIVE_PROJECTS_URL = "/api/v1/dashboard/active-projects"
ACTIVE_CUSTOMERS_URL = "/api/v1/dashboard/active-customers"
PENDING_TASKS_URL = "/api/v1/dashboard/pending-tasks"
UPCOMING_COUNT_URL = "/api/v1/dashboard/upcoming-obligations-count"
DASHBOARD_OBLIGATIONS_URL = "/api/v1/dashboard/obligations"
BILLING_URL = "/api/v1/dashboard/billing"

DASHBOARD_URLS = [
    ACTIVE_PROJECTS_URL,
    ACTIVE_CUSTOMERS_URL,
    PENDING_TASKS_URL,
    UPCOMING_COUNT_URL,
    DASHBOARD_OBLIGATIONS_URL,
    BILLING_URL,
]

CUSTOMERS_URL = "/api/v1/customers"
PROJECTS_URL = "/api/v1/projects"
TASKS_URL = "/api/v1/tasks"
OBLIGATIONS_URL = "/api/v1/obligations"

# A fixed "today" the obligation fixtures are laid out around (the date the mock
# dashboard shows): pobl-002..005 are overdue, pobl-006..011 fall inside the
# 7-day window, pobl-001 is filed and pobl-012 is far in the future.
FROZEN_TODAY = date(2026, 7, 5)

PAGE_META_KEYS = {
    "page",
    "page_size",
    "total_count",
    "total_pages",
    "has_next",
    "has_prev",
}


@pytest.fixture
def frozen_client(client):
    """The authenticated client with the dashboard reference date frozen."""
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    yield client
    app.dependency_overrides.pop(get_reference_date, None)


def _all_billing_groups(frozen_client):
    """Every billing group in one page, for tests that need the full ordering."""
    return frozen_client.get(BILLING_URL, params={"page_size": 100}).json()["items"]


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.parametrize("url", DASHBOARD_URLS)
def test_every_widget_endpoint_answers(frozen_client, url):
    """Each widget endpoint serves a 200 with a non-null body against the mock.

    Nothing fails behind the fixture-backed client, so every widget loads; this
    also guards the router-to-service wiring, where a renamed service method
    would otherwise only blow up at request time.
    """
    resp = frozen_client.get(url)
    assert resp.status_code == 200
    assert resp.json() is not None


@pytest.mark.integration
def test_kpi_endpoints_expose_their_tile_shape(frozen_client):
    """The four KPI tiles each serve exactly the figures they render."""
    assert set(frozen_client.get(ACTIVE_PROJECTS_URL).json()) == {"active", "total"}
    assert set(frozen_client.get(ACTIVE_CUSTOMERS_URL).json()) == {"active", "total"}
    assert set(frozen_client.get(PENDING_TASKS_URL).json()) == {"pending", "total"}
    assert set(frozen_client.get(UPCOMING_COUNT_URL).json()) == {"count"}


# --------------------------------------------------------------------------- #
# Facturación (paginated)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_billing_returns_a_paginated_envelope(frozen_client):
    """Billing is paged, so the client learns the total instead of a bare list."""
    body = frozen_client.get(BILLING_URL).json()
    assert set(body) == {"items", "meta"}
    meta = body["meta"]
    assert set(meta) == PAGE_META_KEYS

    # Defaults: first page, ten customer groups.
    assert meta["page"] == 1
    assert meta["page_size"] == 10
    assert meta["total_count"] > 0
    assert meta["total_pages"] == ceil(meta["total_count"] / 10)
    assert len(body["items"]) == min(10, meta["total_count"])
    assert meta["has_prev"] is False
    assert meta["has_next"] is (meta["total_pages"] > 1)


@pytest.mark.integration
def test_billing_pages_slice_the_full_ordering(frozen_client):
    """Consecutive pages walk the same customer-name ordering without overlap."""
    everything = _all_billing_groups(frozen_client)
    assert len(everything) >= 2, "fixture needs at least two groups to page"

    first = frozen_client.get(BILLING_URL, params={"page_size": 1}).json()
    second = frozen_client.get(
        BILLING_URL, params={"page": 2, "page_size": 1}
    ).json()

    assert first["items"] == [everything[0]]
    assert second["items"] == [everything[1]]
    assert first["meta"]["has_prev"] is False
    assert first["meta"]["has_next"] is True
    assert second["meta"]["has_prev"] is True
    assert second["meta"]["total_count"] == len(everything)


@pytest.mark.integration
def test_billing_page_beyond_the_last_is_empty_but_still_reports_the_total(
    frozen_client,
):
    """Paging past the end yields no rows, not an error, and keeps the total."""
    total = frozen_client.get(BILLING_URL).json()["meta"]["total_count"]

    body = frozen_client.get(
        BILLING_URL, params={"page": total + 1, "page_size": 1}
    ).json()

    assert body["items"] == []
    assert body["meta"]["total_count"] == total
    assert body["meta"]["has_next"] is False


@pytest.mark.integration
def test_billing_rejects_out_of_range_pagination(frozen_client):
    """page >= 1 and 1 <= page_size <= 100 are enforced by the query params."""
    assert frozen_client.get(BILLING_URL, params={"page": 0}).status_code == 422
    assert frozen_client.get(BILLING_URL, params={"page_size": 0}).status_code == 422
    assert frozen_client.get(BILLING_URL, params={"page_size": 101}).status_code == 422


@pytest.mark.integration
def test_billing_groups_projects_under_customers(frozen_client):
    """The billing table is a per-customer table with projects nested.

    Customers are ordered by name — the order Business Central can slice
    natively, which is what lets a page be fetched rather than sliced out of a
    company-wide aggregation. Each carries its projects (billing, usage cost,
    hours) as children, with the customer's cost/hours rolled up from those.
    """
    facturacion = _all_billing_groups(frozen_client)

    assert set(facturacion[0]) == {
        "customer_id",
        "customer_name",
        "net_billed",
        "cost",
        "hours",
        "projects",
    }
    names = [c["customer_name"] for c in facturacion]
    assert names == sorted(names)

    # cust-001 (Fontaneria Puigcerdà SL): 1500 + 2000 invoiced − 200 credited.
    fontaneria = next(c for c in facturacion if c["customer_id"] == "cust-001")
    assert fontaneria["net_billed"] == 3300.0

    # Its projects are nested underneath, and cost/hours roll up from them.
    assert set(fontaneria["projects"][0]) == {
        "project_id",
        "project_name",
        "billed",
        "cost",
        "hours",
    }
    # proj-002 (Gestió laboral) belongs to cust-001: billed 2000, cost 900, 16 h.
    proj_002 = next(
        p for p in fontaneria["projects"] if p["project_id"] == "proj-002"
    )
    assert proj_002 == {
        "project_id": "proj-002",
        "project_name": "Gestió laboral",
        "billed": 2000.0,
        "cost": 900.0,
        "hours": 16.0,
    }
    assert fontaneria["cost"] == round(
        sum(p["cost"] for p in fontaneria["projects"]), 2
    )
    assert fontaneria["hours"] == round(
        sum(p["hours"] for p in fontaneria["projects"]), 2
    )


class _CountingBCClient:
    """Wraps a BC client, counting how many times each getter is called."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: Counter[str] = Counter()

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            self.calls[name] += 1
            return attr(*args, **kwargs)

        return wrapped


@pytest.mark.integration
def test_billing_fetches_each_business_central_source_once(db_session):
    """One billing request reads each shared BC source once.

    The projects list and the invoice/credit-memo lines are all needed by both
    this service and the billing service underneath it; they are fetched here and
    handed down, rather than re-fetched per breakdown.
    """
    bc = _CountingBCClient(MockBusinessCentralClient())

    DashboardService(db_session, bc).get_billing()

    assert bc.calls["get_projects"] == 1
    assert bc.calls["get_sales_invoice_lines"] == 1
    assert bc.calls["get_sales_cr_memo_lines"] == 1


# --------------------------------------------------------------------------- #
# Resilience: one unavailable BC endpoint must not blank the whole panel
# --------------------------------------------------------------------------- #


class _FailingBCClient(MockBusinessCentralClient):
    """A mock client whose named getters raise, simulating an unavailable entity.

    Mirrors the BOPA suite's ``_FailingFetchClient``: everything else serves the
    normal fixtures, so a test can assert that exactly the affected widgets
    degrade and the rest of the dashboard survives.
    """

    def __init__(self, *failing: str, error: Exception | None = None):
        super().__init__()
        self._failing = set(failing)
        self._error = error or RuntimeError("simulated Business Central failure")

    def __getattribute__(self, name):
        # ``_failing`` itself must be fetched normally to avoid infinite recursion.
        if not name.startswith("_") and name in object.__getattribute__(
            self, "_failing"
        ):

            def fail(*args, **kwargs):
                raise object.__getattribute__(self, "_error")

            return fail
        return object.__getattribute__(self, name)


@pytest.mark.integration
def test_failing_billing_source_degrades_only_the_billing_table(db_session):
    """An unavailable invoice endpoint nulls billing, not the other widgets."""
    service = DashboardService(db_session, _FailingBCClient("get_sales_invoice_lines"))

    assert service.get_billing() is None
    # Every other widget still loads and carries real figures.
    assert service.get_active_customers_kpi().total == 15
    assert service.get_active_projects_kpi().total == 19
    assert service.get_pending_tasks_kpi().total == 17
    assert service.get_upcoming_obligations_kpi(FROZEN_TODAY).count > 0
    assert service.get_upcoming_obligations_list(FROZEN_TODAY)


@pytest.mark.integration
def test_failing_projects_source_degrades_its_dependents(db_session):
    """The projects fetch is shared, so its failure also nulls its dependents."""
    service = DashboardService(db_session, _FailingBCClient("get_projects"))

    assert service.get_active_projects_kpi() is None
    assert service.get_billing() is None
    assert service.get_pending_tasks_kpi() is None
    assert service.get_upcoming_obligations_kpi(FROZEN_TODAY) is None
    assert service.get_upcoming_obligations_list(FROZEN_TODAY) is None
    # Customers does not depend on projects in the mock client, so it survives.
    assert service.get_active_customers_kpi().total == 15


@pytest.mark.integration
def test_failing_tasks_source_degrades_only_the_tasks_kpi(db_session):
    """userTasks being unavailable leaves the other three KPI tiles intact."""
    service = DashboardService(db_session, _FailingBCClient("get_user_tasks"))

    assert service.get_pending_tasks_kpi() is None
    assert service.get_active_customers_kpi().total == 15
    assert service.get_active_projects_kpi().total == 19
    assert service.get_billing() is not None


@pytest.mark.integration
def test_http_exception_from_bc_is_not_masked_as_missing_data(db_session):
    """A deliberate HTTPException propagates instead of degrading to None.

    An auth/404 outcome is a real HTTP result, not an integration outage; masking
    it as "widget unavailable" would hide a genuine error from the caller.
    """
    bc = _FailingBCClient(
        "get_customers", error=HTTPException(status_code=403, detail="Forbidden")
    )

    with pytest.raises(HTTPException) as excinfo:
        DashboardService(db_session, bc).get_active_customers_kpi()
    assert excinfo.value.status_code == 403


@pytest.mark.integration
def test_http_exception_from_an_optional_billing_source_is_not_masked(db_session):
    """A 401 on the cost source surfaces instead of nulling just that column.

    ``jobLedgerEntries`` feeds an *optional* column that normally degrades to
    ``None`` when the tenant lacks the entity. An HTTP outcome is different: bad
    credentials must reach the caller, not hide behind an em dash in the table.
    """
    bc = _FailingBCClient(
        "get_job_ledger_entries",
        error=HTTPException(status_code=401, detail="Unauthorized"),
    )

    with pytest.raises(HTTPException) as excinfo:
        DashboardService(db_session, bc).get_billing()
    assert excinfo.value.status_code == 401


def _get_with_failing_bc(client, url, *failing: str):
    """GET ``url`` with the given BC getters failing and the date frozen."""
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    app.dependency_overrides[get_business_central_client] = lambda: _FailingBCClient(
        *failing
    )
    try:
        return client.get(url)
    finally:
        app.dependency_overrides.pop(get_business_central_client, None)
        app.dependency_overrides.pop(get_reference_date, None)


@pytest.mark.integration
def test_unavailable_widget_endpoint_returns_200_with_null(client):
    """An endpoint degrades to a 200 ``null`` rather than a blanket 500."""
    resp = _get_with_failing_bc(client, BILLING_URL, "get_sales_invoice_lines")
    assert resp.status_code == 200
    assert resp.json() is None

    # Its siblings are unaffected by that source being down.
    sibling = _get_with_failing_bc(
        client, ACTIVE_CUSTOMERS_URL, "get_sales_invoice_lines"
    )
    assert sibling.status_code == 200
    assert sibling.json() == {"active": 14, "total": 15}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("url", "failing"),
    [
        (PENDING_TASKS_URL, "get_user_tasks"),
        (DASHBOARD_OBLIGATIONS_URL, "get_projects"),
    ],
)
def test_degraded_list_and_task_widgets_serialize_as_null(client, url, failing):
    """These two return ``None`` on an outage, so their response model allows it.

    A non-nullable ``response_model`` here would turn a graceful degradation into
    a ``ResponseValidationError`` (500), which is exactly what the tile-level
    "No disponible" copy is meant to avoid.
    """
    resp = _get_with_failing_bc(client, url, failing)
    assert resp.status_code == 200
    assert resp.json() is None


# --------------------------------------------------------------------------- #
# KPI consistency with the underlying endpoints
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_clientes_activos_matches_customers_endpoint(frozen_client):
    """active-customers == count of Activo customers / total from #7."""
    customers = frozen_client.get(CUSTOMERS_URL).json()["items"]
    active = frozen_client.get(CUSTOMERS_URL, params={"status": "Activo"}).json()[
        "items"
    ]
    kpi = frozen_client.get(ACTIVE_CUSTOMERS_URL).json()
    assert kpi == {"active": len(active), "total": len(customers)}
    assert kpi == {"active": 14, "total": 15}


@pytest.mark.integration
def test_proyectos_activos_matches_projects_endpoint(frozen_client):
    """active-projects == count of Activo projects / total from #8."""
    projects = frozen_client.get(PROJECTS_URL).json()["items"]
    active = frozen_client.get(PROJECTS_URL, params={"status": "Activo"}).json()[
        "items"
    ]
    kpi = frozen_client.get(ACTIVE_PROJECTS_URL).json()
    assert kpi == {"active": len(active), "total": len(projects)}
    assert kpi == {"active": 18, "total": 19}


@pytest.mark.integration
def test_generated_data_reflected_in_kpis(frozen_client):
    """The generated clients/projects show up in the KPI totals."""
    # 8 original + 6 generated + OEC SLU (cust-015) = 15 customers; the matching
    # projects total 19 (proj-001..019).
    assert frozen_client.get(ACTIVE_CUSTOMERS_URL).json()["total"] == 15
    assert frozen_client.get(ACTIVE_PROJECTS_URL).json()["total"] == 19


@pytest.mark.integration
def test_tareas_pendientes_counts_unfinished_tasks(frozen_client):
    """pending-tasks.pending == tasks not in Hecho; total == all tasks."""
    tasks = frozen_client.get(TASKS_URL).json()
    not_done = [t for t in tasks if t["status"] != "Hecho"]
    kpi = frozen_client.get(PENDING_TASKS_URL).json()
    assert kpi == {"pending": len(not_done), "total": len(tasks)}
    assert kpi == {"pending": 15, "total": 17}


@pytest.mark.integration
def test_obligaciones_proximas_counts_upcoming_within_window(frozen_client):
    """upcoming-obligations-count == instances due within 7 days (Próximo), from #9.

    Overdue instances are excluded on purpose — the tile reads "en los próximos
    7 días" — even though the list endpoint below includes them.
    """
    app.dependency_overrides[obligations_reference_date] = lambda: FROZEN_TODAY
    try:
        # The obligations endpoint answers with the {items, meta} envelope; the
        # dashboard's own routes still return bare lists.
        upcoming = frozen_client.get(
            OBLIGATIONS_URL, params={"status": "Próximo"}
        ).json()["items"]
    finally:
        app.dependency_overrides.pop(obligations_reference_date, None)
    kpi = frozen_client.get(UPCOMING_COUNT_URL).json()
    assert kpi == {"count": len(upcoming)}
    assert kpi == {"count": 6}


# --------------------------------------------------------------------------- #
# Próximas obligaciones list
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_proximas_obligaciones_are_upcoming_or_overdue_ordered(frozen_client):
    """The list is the upcoming + overdue instances, ordered by due date."""
    proximas = frozen_client.get(DASHBOARD_OBLIGATIONS_URL).json()
    # Only Vencido / Próximo (never Al día).
    assert {o["status"] for o in proximas} == {"Vencido", "Próximo"}
    # pobl-002..005 (overdue) + pobl-006..011 (upcoming) = 10 instances.
    assert {o["id"] for o in proximas} == {
        "pobl-002",
        "pobl-003",
        "pobl-004",
        "pobl-005",
        "pobl-006",
        "pobl-007",
        "pobl-008",
        "pobl-009",
        "pobl-010",
        "pobl-011",
    }
    due_dates = [o["due_date"] for o in proximas]
    assert due_dates == sorted(due_dates)
    # Reuses the obligations domain shape (obligation / project / client refs).
    assert set(proximas[0]) == {
        "id",
        "obligation",
        "project",
        "client",
        "subject",
        "due_date",
        "submission_date",
        "status",
    }


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


@pytest.mark.auth
@pytest.mark.parametrize("url", DASHBOARD_URLS)
def test_dashboard_endpoints_require_authentication(db_session, url):
    """Without a verified user every dashboard endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(url)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
