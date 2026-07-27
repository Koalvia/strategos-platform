"""Tests for the read-only dashboard aggregation endpoint (issue #12).

The dashboard domain has no database model and no persistence — it only composes
the customers / projects / obligations / tasks domains, all served from the
fixture-backed ``MockBusinessCentralClient`` (the default DI mode). These tests
cover:

* the summary shape (four KPI tiles + the "Próximas obligaciones" list + the
  per-customer "Facturación" breakdown),
* that each KPI is internally consistent with the underlying domain endpoint's
  count for the mock data (asserted against a frozen reference date for the
  obligation-derived numbers),
* the "Próximas obligaciones" list (upcoming + overdue, ordered by due date), and
* that the endpoint rejects unauthenticated requests.

The obligation-derived numbers are computed against a reference "today"; tests
freeze it by overriding the ``get_reference_date`` dependency so assertions do not
depend on the real clock.
"""

from collections import Counter
from datetime import date

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

SUMMARY_URL = "/api/v1/dashboard/summary"
CUSTOMERS_URL = "/api/v1/customers"
PROJECTS_URL = "/api/v1/projects"
TASKS_URL = "/api/v1/tasks"
OBLIGATIONS_URL = "/api/v1/obligations"

# A fixed "today" the obligation fixtures are laid out around (the date the mock
# dashboard shows): pobl-002..005 are overdue, pobl-006..011 fall inside the
# 7-day window, pobl-001 is filed and pobl-012 is far in the future.
FROZEN_TODAY = date(2026, 7, 5)


@pytest.fixture
def frozen_client(client):
    """The authenticated client with the dashboard reference date frozen."""
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    yield client
    app.dependency_overrides.pop(get_reference_date, None)


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_summary_returns_all_sections(frozen_client):
    """The summary exposes the count KPIs, the two lists and the financial section."""
    resp = frozen_client.get(SUMMARY_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "proyectos_activos",
        "obligaciones_proximas",
        "tareas_pendientes",
        "clientes_activos",
        "proximas_obligaciones",
        "facturacion",
        "unavailable_sections",
    }
    assert set(body["proyectos_activos"]) == {"active", "total"}
    assert set(body["clientes_activos"]) == {"active", "total"}
    assert set(body["tareas_pendientes"]) == {"pending", "total"}
    assert set(body["obligaciones_proximas"]) == {"count"}
    # Nothing fails against the fixture-backed mock client, so every section
    # loaded and none reports as unavailable.
    assert body["unavailable_sections"] == []


@pytest.mark.integration
def test_financial_section_groups_projects_under_customers(frozen_client):
    """The financial section is a per-customer table with projects nested.

    Customers are capped at five rows and ordered by net billing desc; each
    carries its projects (billing, usage cost, hours) as children, with the
    customer's cost/hours rolled up from those projects.
    """
    body = frozen_client.get(SUMMARY_URL).json()

    facturacion = body["facturacion"]
    assert len(facturacion) <= 5
    assert set(facturacion[0]) == {
        "customer_id",
        "customer_name",
        "net_billed",
        "cost",
        "hours",
        "projects",
    }
    net_amounts = [c["net_billed"] for c in facturacion]
    assert net_amounts == sorted(net_amounts, reverse=True)

    # cust-001 tops the list: 1500 + 2000 invoiced − 200 credited = 3300.
    top = facturacion[0]
    assert top["customer_id"] == "cust-001"
    assert top["net_billed"] == 3300.0

    # Its projects are nested underneath, and cost/hours roll up from them.
    assert set(top["projects"][0]) == {
        "project_id",
        "project_name",
        "billed",
        "cost",
        "hours",
    }
    # proj-002 (Gestió laboral) belongs to cust-001: billed 2000, cost 900, 16 h.
    proj_002 = next(p for p in top["projects"] if p["project_id"] == "proj-002")
    assert proj_002 == {
        "project_id": "proj-002",
        "project_name": "Gestió laboral",
        "billed": 2000.0,
        "cost": 900.0,
        "hours": 16.0,
    }
    assert top["cost"] == round(sum(p["cost"] for p in top["projects"]), 2)
    assert top["hours"] == round(sum(p["hours"] for p in top["projects"]), 2)


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
def test_dashboard_build_fetches_billing_lines_once(db_session):
    """One dashboard load fetches the shared invoice/credit-memo lines once each.

    Both billing breakdowns read the same lines; the dashboard fetches them once
    and hands them to the service instead of letting each breakdown re-fetch.
    """
    bc = _CountingBCClient(MockBusinessCentralClient())

    DashboardService(db_session, bc).build_summary(FROZEN_TODAY)

    assert bc.calls["get_sales_invoice_lines"] == 1
    assert bc.calls["get_sales_cr_memo_lines"] == 1


# --------------------------------------------------------------------------- #
# Resilience: one unavailable BC endpoint must not blank the whole panel
# --------------------------------------------------------------------------- #


class _FailingBCClient(MockBusinessCentralClient):
    """A mock client whose named getters raise, simulating an unavailable entity.

    Mirrors the BOPA suite's ``_FailingFetchClient``: everything else serves the
    normal fixtures, so a test can assert that exactly the affected sections
    degrade and the rest of the summary survives.
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
def test_failing_billing_source_degrades_only_that_section(db_session):
    """An unavailable invoice endpoint nulls facturacion, not the whole summary."""
    bc = _FailingBCClient("get_sales_invoice_lines")

    summary = DashboardService(db_session, bc).build_summary(FROZEN_TODAY)

    assert summary.facturacion is None
    assert summary.unavailable_sections == ["billing"]
    # Every other section still loaded and carries real figures.
    assert summary.clientes_activos.total == 15
    assert summary.proyectos_activos.total == 19
    assert summary.tareas_pendientes.total == 17
    assert summary.obligaciones_proximas.count > 0
    assert summary.proximas_obligaciones


@pytest.mark.integration
def test_failing_projects_source_degrades_its_dependents(db_session):
    """The projects fetch is shared, so its failure also nulls the billing table."""
    bc = _FailingBCClient("get_projects")

    summary = DashboardService(db_session, bc).build_summary(FROZEN_TODAY)

    assert summary.proyectos_activos is None
    assert summary.facturacion is None
    assert set(summary.unavailable_sections) == {"projects", "tasks", "obligations",
                                                "billing"}
    # Customers does not depend on projects in the mock client, so it survives.
    assert summary.clientes_activos.total == 15


@pytest.mark.integration
def test_failing_tasks_source_degrades_only_the_tasks_kpi(db_session):
    """userTasks being unavailable leaves the other three KPI tiles intact."""
    bc = _FailingBCClient("get_user_tasks")

    summary = DashboardService(db_session, bc).build_summary(FROZEN_TODAY)

    assert summary.tareas_pendientes is None
    assert summary.unavailable_sections == ["tasks"]
    assert summary.clientes_activos.total == 15
    assert summary.proyectos_activos.total == 19
    assert summary.facturacion


@pytest.mark.integration
def test_http_exception_from_bc_is_not_masked_as_missing_data(db_session):
    """A deliberate HTTPException propagates instead of degrading to None.

    An auth/404 outcome is a real HTTP result, not an integration outage; masking
    it as "section unavailable" would hide a genuine error from the caller.
    """
    bc = _FailingBCClient(
        "get_customers", error=HTTPException(status_code=403, detail="Forbidden")
    )

    with pytest.raises(HTTPException) as excinfo:
        DashboardService(db_session, bc).build_summary(FROZEN_TODAY)
    assert excinfo.value.status_code == 403


@pytest.mark.integration
def test_summary_endpoint_returns_200_when_a_section_is_unavailable(client):
    """The endpoint degrades to a partial 200 rather than a blanket 500."""
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    app.dependency_overrides[get_business_central_client] = lambda: _FailingBCClient(
        "get_sales_invoice_lines"
    )
    try:
        resp = client.get(SUMMARY_URL)
    finally:
        app.dependency_overrides.pop(get_business_central_client, None)
        app.dependency_overrides.pop(get_reference_date, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["facturacion"] is None
    assert body["unavailable_sections"] == ["billing"]
    assert body["clientes_activos"] == {"active": 14, "total": 15}


# --------------------------------------------------------------------------- #
# KPI consistency with the underlying endpoints
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_clientes_activos_matches_customers_endpoint(frozen_client):
    """clientes_activos == count of Activo customers / total from #7."""
    customers = frozen_client.get(CUSTOMERS_URL).json()["items"]
    active = frozen_client.get(
        CUSTOMERS_URL, params={"status": "Activo"}
    ).json()["items"]
    kpi = frozen_client.get(SUMMARY_URL).json()["clientes_activos"]
    assert kpi == {"active": len(active), "total": len(customers)}
    assert kpi == {"active": 14, "total": 15}


@pytest.mark.integration
def test_proyectos_activos_matches_projects_endpoint(frozen_client):
    """proyectos_activos == count of Activo projects / total from #8."""
    projects = frozen_client.get(PROJECTS_URL).json()["items"]
    active = frozen_client.get(
        PROJECTS_URL, params={"status": "Activo"}
    ).json()["items"]
    kpi = frozen_client.get(SUMMARY_URL).json()["proyectos_activos"]
    assert kpi == {"active": len(active), "total": len(projects)}
    assert kpi == {"active": 18, "total": 19}


@pytest.mark.integration
def test_generated_data_reflected_in_kpis(frozen_client):
    """The generated clients/projects show up in the KPI totals."""
    body = frozen_client.get(SUMMARY_URL).json()
    # 8 original + 6 generated + OEC SLU (cust-015) = 15 customers; the matching
    # projects total 19 (proj-001..019).
    assert body["clientes_activos"]["total"] == 15
    assert body["proyectos_activos"]["total"] == 19


@pytest.mark.integration
def test_tareas_pendientes_counts_unfinished_tasks(frozen_client):
    """tareas_pendientes.pending == tasks not in Hecho; total == all tasks."""
    tasks = frozen_client.get(TASKS_URL).json()
    not_done = [t for t in tasks if t["status"] != "Hecho"]
    kpi = frozen_client.get(SUMMARY_URL).json()["tareas_pendientes"]
    assert kpi == {"pending": len(not_done), "total": len(tasks)}
    assert kpi == {"pending": 15, "total": 17}


@pytest.mark.integration
def test_obligaciones_proximas_counts_upcoming_within_window(frozen_client):
    """obligaciones_proximas.count == instances due within 7 days (Próximo) from #9."""
    app.dependency_overrides[obligations_reference_date] = lambda: FROZEN_TODAY
    try:
        upcoming = frozen_client.get(
            OBLIGATIONS_URL, params={"status": "Próximo"}
        ).json()
    finally:
        app.dependency_overrides.pop(obligations_reference_date, None)
    kpi = frozen_client.get(SUMMARY_URL).json()["obligaciones_proximas"]
    assert kpi == {"count": len(upcoming)}
    assert kpi == {"count": 6}


# --------------------------------------------------------------------------- #
# Próximas obligaciones list
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_proximas_obligaciones_are_upcoming_or_overdue_ordered(frozen_client):
    """The list is the upcoming + overdue instances, ordered by due date."""
    body = frozen_client.get(SUMMARY_URL).json()
    proximas = body["proximas_obligaciones"]
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
def test_summary_requires_authentication(db_session):
    """Without a verified user the summary endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(SUMMARY_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
