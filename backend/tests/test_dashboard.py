"""Tests for the read-only dashboard aggregation endpoint (issue #12).

The dashboard domain has no database model and no persistence — it only composes
the customers / projects / obligations / tasks domains, all served from the
fixture-backed ``MockBusinessCentralClient`` (the default DI mode). These tests
cover:

* the summary shape (four KPI tiles + the two list sections),
* that each KPI is internally consistent with the underlying domain endpoint's
  count for the mock data (asserted against a frozen reference date for the
  obligation-derived numbers),
* the "Próximas obligaciones" list (upcoming + overdue, ordered by due date),
* "Mis tareas de hoy" scoped to the current user's unfinished, soon-due tasks, and
* that the endpoint rejects unauthenticated requests.

The obligation-derived numbers are computed against a reference "today"; tests
freeze it by overriding the ``get_reference_date`` dependency so assertions do not
depend on the real clock.
"""

from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
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


@pytest.fixture
def frozen_bc_user_client(db_session):
    """A frozen-date client whose user maps to BC assignee ``usr-anna``.

    "Mis tareas de hoy" resolves the BC assignee by email, so the seeded user's
    email must match a BC user (``anna@estrategos.ad``).
    """
    user = User(
        name="Anna Ferrer",
        email="anna@estrategos.ad",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_verified_user] = lambda: user
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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
        "mis_tareas_de_hoy",
        "facturacion_neta",
        "costes",
        "facturacion_por_cliente",
        "facturacion_por_proyecto",
    }
    assert set(body["proyectos_activos"]) == {"active", "total"}
    assert set(body["clientes_activos"]) == {"active", "total"}
    assert set(body["tareas_pendientes"]) == {"pending", "total"}
    assert set(body["obligaciones_proximas"]) == {"count"}
    assert set(body["facturacion_neta"]) == {"amount"}
    assert set(body["costes"]) == {"amount"}


@pytest.mark.integration
def test_financial_section_aggregates_billing_and_costs(frozen_client):
    """The financial section carries firm totals plus the top breakdown rows.

    Totals come from the billing fixtures: net billing = invoices − credit memos
    = 7000.00 firm-wide; usage cost from the job ledger = 3250.00. The tables are
    capped at five rows and ordered by amount desc.
    """
    body = frozen_client.get(SUMMARY_URL).json()

    assert body["facturacion_neta"] == {"amount": 7000.0}
    assert body["costes"] == {"amount": 3250.0}

    por_cliente = body["facturacion_por_cliente"]
    assert len(por_cliente) <= 5
    assert set(por_cliente[0]) == {"customer_id", "customer_name", "net_billed"}
    # cust-001 tops the list: 1500 + 2000 invoiced − 200 credited = 3300.
    assert por_cliente[0]["customer_id"] == "cust-001"
    assert por_cliente[0]["net_billed"] == 3300.0
    amounts = [c["net_billed"] for c in por_cliente]
    assert amounts == sorted(amounts, reverse=True)

    por_proyecto = body["facturacion_por_proyecto"]
    assert len(por_proyecto) <= 5
    assert set(por_proyecto[0]) == {
        "project_id",
        "project_name",
        "billed",
        "cost",
        "hours",
    }
    # proj-002: billed 2000, usage cost 900, 16 hours logged.
    top = next(p for p in por_proyecto if p["project_id"] == "proj-002")
    assert top == {
        "project_id": "proj-002",
        "project_name": top["project_name"],
        "billed": 2000.0,
        "cost": 900.0,
        "hours": 16.0,
    }


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
    user = User(
        name="Test User",
        email="test@example.com",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )

    DashboardService(db_session, bc).build_summary(user, FROZEN_TODAY)

    assert bc.calls["get_sales_invoice_lines"] == 1
    assert bc.calls["get_sales_cr_memo_lines"] == 1


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
    assert kpi == {"active": 13, "total": 14}


@pytest.mark.integration
def test_proyectos_activos_matches_projects_endpoint(frozen_client):
    """proyectos_activos == count of Activo projects / total from #8."""
    projects = frozen_client.get(PROJECTS_URL).json()["items"]
    active = frozen_client.get(
        PROJECTS_URL, params={"status": "Activo"}
    ).json()["items"]
    kpi = frozen_client.get(SUMMARY_URL).json()["proyectos_activos"]
    assert kpi == {"active": len(active), "total": len(projects)}
    assert kpi == {"active": 17, "total": 18}


@pytest.mark.integration
def test_generated_data_reflected_in_kpis(frozen_client):
    """The generated clients/projects show up in the KPI totals."""
    body = frozen_client.get(SUMMARY_URL).json()
    # 8 original + 6 generated customers; 12 original + 6 generated projects.
    assert body["clientes_activos"]["total"] == 14
    assert body["proyectos_activos"]["total"] == 18


@pytest.mark.integration
def test_tareas_pendientes_counts_unfinished_tasks(frozen_client):
    """tareas_pendientes.pending == tasks not in Hecho; total == all tasks."""
    tasks = frozen_client.get(TASKS_URL).json()
    not_done = [t for t in tasks if t["status"] != "Hecho"]
    kpi = frozen_client.get(SUMMARY_URL).json()["tareas_pendientes"]
    assert kpi == {"pending": len(not_done), "total": len(tasks)}
    assert kpi == {"pending": 13, "total": 15}


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
# Mis tareas de hoy
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_mis_tareas_scoped_to_current_user(frozen_bc_user_client):
    """"Mis tareas de hoy" returns the user's unfinished, soon-due tasks, ordered."""
    body = frozen_bc_user_client.get(SUMMARY_URL).json()
    mis = body["mis_tareas_de_hoy"]
    # Only usr-anna's tasks, none of them Hecho, all due on/before the window end.
    assert {t["assignee"]["id"] for t in mis} == {"usr-anna"}
    assert "Hecho" not in {t["status"] for t in mis}
    # task-015 (Hecho) drops out; task-003/006/011 are due within the window.
    assert [t["id"] for t in mis] == ["task-006", "task-011", "task-003"]
    due_dates = [t["due_date"] for t in mis]
    assert due_dates == sorted(due_dates)


@pytest.mark.integration
def test_mis_tareas_empty_when_no_bc_user_matches(frozen_client):
    """A local user with no matching BC email has no "mis tareas de hoy"."""
    # The default ``test_user`` email (test@example.com) is not a BC user.
    body = frozen_client.get(SUMMARY_URL).json()
    assert body["mis_tareas_de_hoy"] == []


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
