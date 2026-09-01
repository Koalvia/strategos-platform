"""Tests for the read-only obligations (Obligaciones) domain (issue #9).

The domain has no database model — obligations are served from the fixture-backed
``MockBusinessCentralClient`` (the default DI mode). These tests cover:

* the catalog endpoint (count + periodicity mapping),
* the per-project instance mapping (obligation / project / client names),
* the **derived status** (``derive_status``) asserted against a frozen reference
  date for each of Vencido / Próximo / Al día (including a filed instance),
* the ``status`` / ``project_id`` / date-range filters and due-date ordering,
* the ``{items, meta}`` pagination envelope (slicing, the real total behind a
  page, out-of-range windows, and that omitting ``page_size`` still returns the
  complete list),
* the ``/projects`` filter-option endpoint,
* the **Business Central read cost**: which reads a request is allowed to make,
  so the expensive ones cannot creep back in, and
* that the endpoints reject unauthenticated requests.

The instance endpoint derives status against a reference "today". Tests freeze it
by overriding the ``get_reference_date`` dependency so assertions do not depend on
the real clock.
"""

from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.obligations.router import get_reference_date
from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.obligations.service import ObligationsService, derive_status
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.mock_client import MockBusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerPage,
    BCCustomerRef,
    BCCustomerRefPage,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCProjectPage,
    CustomerStatus,
    ProjectStatus,
)
from app.main import app

CATALOG_URL = "/api/v1/obligations/catalog"
OBLIGATIONS_URL = "/api/v1/obligations"
PROJECT_OPTIONS_URL = "/api/v1/obligations/projects"

# A fixed "today" the fixtures are laid out around: pobl-001 (filed) is well past
# due, pobl-002..005 are overdue, several fall inside the 7-day window, and
# pobl-012 (2026-10-31) is far in the future.
FROZEN_TODAY = date(2026, 7, 1)


PAGE_META_KEYS = {
    "page",
    "page_size",
    "total_count",
    "total_pages",
    "has_next",
    "has_prev",
}


def _items(resp) -> list[dict]:
    """The instance rows out of the paginated response envelope."""
    return resp.json()["items"]


@pytest.fixture
def frozen_client(client):
    """The authenticated client with the obligation reference date frozen."""
    app.dependency_overrides[get_reference_date] = lambda: FROZEN_TODAY
    yield client
    app.dependency_overrides.pop(get_reference_date, None)


# --------------------------------------------------------------------------- #
# derive_status (pure unit tests)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_derive_status_overdue_when_past_due_and_unfiled():
    """A past-due, unfiled instance is Vencido."""
    status = derive_status(date(2026, 6, 15), None, FROZEN_TODAY)
    assert status is DerivedObligationStatus.overdue


@pytest.mark.unit
def test_derive_status_upcoming_within_window():
    """An unfiled instance due within 7 days (inclusive) is Próximo."""
    assert derive_status(FROZEN_TODAY, None, FROZEN_TODAY) is DerivedObligationStatus.upcoming
    assert (
        derive_status(date(2026, 7, 8), None, FROZEN_TODAY)
        is DerivedObligationStatus.upcoming
    )


@pytest.mark.unit
def test_derive_status_on_track_when_far_future():
    """An unfiled instance due beyond the window is Al día."""
    assert (
        derive_status(date(2026, 7, 9), None, FROZEN_TODAY)
        is DerivedObligationStatus.on_track
    )


@pytest.mark.unit
def test_derive_status_filed_is_on_track_even_if_past_due():
    """A filed instance is Al día regardless of how far past due it was."""
    status = derive_status(date(2026, 6, 15), date(2026, 6, 10), FROZEN_TODAY)
    assert status is DerivedObligationStatus.on_track


@pytest.mark.unit
def test_derive_status_undated_when_no_due_date():
    """An instance without a due date is Sin fecha, never overdue/upcoming."""
    assert derive_status(None, None, FROZEN_TODAY) is DerivedObligationStatus.undated
    # A due-less instance is undated even if a submission date is somehow present.
    assert (
        derive_status(None, date(2026, 6, 10), FROZEN_TODAY)
        is DerivedObligationStatus.undated
    )


# --------------------------------------------------------------------------- #
# Catalog endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_catalog_returns_ten_obligation_types(client):
    """The catalog returns every mock obligation type (10)."""
    resp = client.get(CATALOG_URL)
    assert resp.status_code == 200
    assert len(resp.json()) == 10


@pytest.mark.integration
def test_catalog_fields_and_periodicity(client):
    """Each catalog entry exposes code, name, periodicity and due-date rule."""
    resp = client.get(CATALOG_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == {"code", "name", "periodicity", "due_date_rule"}
    by_code = {o["code"]: o for o in body}
    assert by_code["IRPF"]["periodicity"] == "trimestral"
    assert by_code["CCAA"]["name"] == "Dipòsit de comptes (CCAA)"
    assert by_code["CASS"]["periodicity"] == "mensual"
    assert by_code["IS"]["periodicity"] == "anual"


# --------------------------------------------------------------------------- #
# Instance endpoint: mapping, status, filters, ordering
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_instance_mapping_includes_obligation_project_client_names(frozen_client):
    """Each instance resolves the obligation, project and client display names."""
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    row = next(o for o in _items(resp) if o["id"] == "pobl-002")
    assert set(row) == {
        "id",
        "obligation",
        "project",
        "client",
        "subject",
        "due_date",
        "submission_date",
        "status",
    }
    assert row["obligation"] == {"code": "CCAA", "name": "Dipòsit de comptes (CCAA)"}
    assert row["project"] == {"id": "proj-007", "name": "Comptabilitat fundació"}
    assert row["client"] == {"id": "cust-005", "name": "Fundació Cultural Andorrana"}
    assert row["subject"] is True
    assert row["due_date"] == "2026-06-20"
    assert row["submission_date"] is None
    assert row["status"] == "Vencido"


@pytest.mark.integration
def test_derived_status_across_endpoint(frozen_client):
    """The endpoint derives Vencido / Próximo / Al día for the frozen date."""
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    status_by_id = {o["id"]: o["status"] for o in _items(resp)}
    # Filed, though past due.
    assert status_by_id["pobl-001"] == "Al día"
    # Unfiled and past due.
    assert status_by_id["pobl-002"] == "Vencido"
    # Unfiled, due 2026-07-05 -> within the 7-day window of 2026-07-01.
    assert status_by_id["pobl-006"] == "Próximo"
    # Unfiled, due 2026-10-31 -> far future.
    assert status_by_id["pobl-012"] == "Al día"


@pytest.mark.integration
def test_results_ordered_by_due_date(frozen_client):
    """Instances come back ordered by due date ascending."""
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    due_dates = [o["due_date"] for o in _items(resp)]
    assert due_dates == sorted(due_dates)


@pytest.mark.integration
def test_status_filter(frozen_client):
    """?status= keeps only instances in that derived state."""
    resp = frozen_client.get(OBLIGATIONS_URL, params={"status": "Vencido"})
    assert resp.status_code == 200
    body = _items(resp)
    assert {o["status"] for o in body} == {"Vencido"}
    # pobl-002..005 are overdue; pobl-001 is filed so it drops out.
    assert {o["id"] for o in body} == {"pobl-002", "pobl-003", "pobl-004", "pobl-005"}


@pytest.mark.integration
def test_project_id_filter(frozen_client):
    """?project_id= restricts to a single project's obligations."""
    resp = frozen_client.get(OBLIGATIONS_URL, params={"project_id": "proj-012"})
    assert resp.status_code == 200
    body = _items(resp)
    assert {o["project"]["id"] for o in body} == {"proj-012"}
    assert {o["id"] for o in body} == {"pobl-003", "pobl-005"}


@pytest.mark.integration
def test_due_date_range_filter(frozen_client):
    """?due_after / ?due_before bound the due date (both inclusive) and compose."""
    resp = frozen_client.get(
        OBLIGATIONS_URL,
        params={"due_after": "2026-06-20", "due_before": "2026-07-05"},
    )
    assert resp.status_code == 200
    body = _items(resp)
    assert {o["id"] for o in body} == {
        "pobl-002",
        "pobl-003",
        "pobl-004",
        "pobl-005",
        "pobl-006",
        "pobl-008",
        "pobl-011",
    }


@pytest.mark.integration
def test_filters_compose(frozen_client):
    """status + project_id intersect (all must match)."""
    resp = frozen_client.get(
        OBLIGATIONS_URL,
        params={"status": "Vencido", "project_id": "proj-012"},
    )
    assert resp.status_code == 200
    assert {o["id"] for o in _items(resp)} == {"pobl-003", "pobl-005"}


@pytest.mark.integration
def test_due_before_only_bound(frozen_client):
    """?due_before alone keeps only instances due on or before that date."""
    resp = frozen_client.get(OBLIGATIONS_URL, params={"due_before": "2026-06-30"})
    assert resp.status_code == 200
    # Only the June-due instances (pobl-001..005); July onwards is excluded.
    assert {o["id"] for o in _items(resp)} == {
        "pobl-001",
        "pobl-002",
        "pobl-003",
        "pobl-004",
        "pobl-005",
    }


@pytest.mark.integration
def test_generated_instances_derive_on_track(frozen_client):
    """The generated far-future instances (pobl-013..018) are Al día, never overdue/upcoming."""
    generated = {f"pobl-{n:03d}" for n in range(13, 19)}

    on_track = _items(
        frozen_client.get(OBLIGATIONS_URL, params={"status": "Al día"})
    )
    assert generated <= {o["id"] for o in on_track}

    # None of them fall in the overdue or upcoming buckets.
    for status in ("Vencido", "Próximo"):
        got = _items(frozen_client.get(OBLIGATIONS_URL, params={"status": status}))
        assert generated.isdisjoint({o["id"] for o in got})


@pytest.mark.integration
def test_generated_instance_mapping(frozen_client):
    """A generated instance (pobl-018) resolves its obligation/project/client names.

    Expected names come from the mock BC client (the rows are Faker-generated).
    """
    from app.integrations.business_central.mock_client import (
        MockBusinessCentralClient,
    )

    bc = MockBusinessCentralClient()
    instance = next(i for i in bc.get_project_obligations() if i.id == "pobl-018")
    project = next(p for p in bc.get_projects() if p.id == instance.project_id)
    customer = next(c for c in bc.get_customers() if c.id == project.customer_id)
    obligation = next(
        o for o in bc.get_obligations() if o.id == instance.obligation_id
    )

    row = next(
        o for o in _items(frozen_client.get(OBLIGATIONS_URL)) if o["id"] == "pobl-018"
    )
    assert row["status"] == "Al día"
    assert row["project"] == {"id": project.id, "name": project.name}
    assert row["client"] == {"id": customer.id, "name": customer.name}
    assert row["obligation"] == {"code": obligation.code, "name": obligation.name}


@pytest.mark.integration
def test_invalid_status_is_rejected(client):
    """An unknown status value is rejected by validation (422)."""
    resp = client.get(OBLIGATIONS_URL, params={"status": "Bogus"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_unpaged_request_returns_every_match_in_one_page(frozen_client):
    """Without page_size the whole result set comes back in a single page.

    This is the contract the projects grid and the project detail screen depend
    on, so it is asserted rather than assumed.
    """
    resp = frozen_client.get(OBLIGATIONS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "meta"}

    meta = body["meta"]
    assert set(meta) == PAGE_META_KEYS
    total = meta["total_count"]
    # The fixtures must exceed one page for the paging tests below to bite.
    assert total > 10
    assert len(body["items"]) == total
    assert meta["page"] == 1
    assert meta["page_size"] == total
    assert meta["total_pages"] == 1
    assert meta["has_next"] is False
    assert meta["has_prev"] is False


@pytest.mark.integration
def test_page_is_ignored_when_page_size_is_omitted(frozen_client):
    """?page= alone cannot shrink an unpaged response."""
    unpaged = frozen_client.get(OBLIGATIONS_URL).json()
    resp = frozen_client.get(OBLIGATIONS_URL, params={"page": 3})
    assert resp.status_code == 200
    assert resp.json() == unpaged


@pytest.mark.integration
def test_page_size_slices_and_reports_the_real_total(frozen_client):
    """page_size serves that many rows while meta keeps the unsliced total."""
    total = frozen_client.get(OBLIGATIONS_URL).json()["meta"]["total_count"]

    resp = frozen_client.get(OBLIGATIONS_URL, params={"page_size": 5})
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert len(_items(resp)) == 5
    assert meta["total_count"] == total
    assert meta["total_pages"] == -(-total // 5)  # ceil
    assert meta["has_next"] is True
    assert meta["has_prev"] is False


@pytest.mark.integration
def test_pages_partition_the_result_in_due_date_order(frozen_client):
    """Consecutive pages are consecutive slices of the same ordered list."""
    ordered = [o["id"] for o in _items(frozen_client.get(OBLIGATIONS_URL))]

    first = _items(frozen_client.get(OBLIGATIONS_URL, params={"page_size": 5}))
    second = _items(
        frozen_client.get(OBLIGATIONS_URL, params={"page": 2, "page_size": 5})
    )

    assert [o["id"] for o in first] == ordered[:5]
    assert [o["id"] for o in second] == ordered[5:10]
    # Nothing is lost or repeated across the page boundary.
    assert set(o["id"] for o in first).isdisjoint(o["id"] for o in second)


@pytest.mark.integration
def test_page_past_the_end_is_empty_but_keeps_the_meta(frozen_client):
    """A page beyond the last one is an empty 200, not an error."""
    resp = frozen_client.get(OBLIGATIONS_URL, params={"page": 99, "page_size": 5})
    assert resp.status_code == 200
    assert _items(resp) == []
    meta = resp.json()["meta"]
    assert meta["page"] == 99
    assert meta["total_count"] > 0
    assert meta["has_next"] is False
    assert meta["has_prev"] is True


@pytest.mark.integration
def test_total_count_is_computed_after_status_filtering(frozen_client):
    """The page is cut out of the filtered result, and the total reflects it."""
    resp = frozen_client.get(
        OBLIGATIONS_URL, params={"status": "Vencido", "page_size": 2}
    )
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    # pobl-002..005 are the four overdue instances.
    assert meta["total_count"] == 4
    assert meta["total_pages"] == 2
    assert len(_items(resp)) == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 101},
    ],
)
def test_out_of_range_pagination_params_are_rejected(frozen_client, params):
    """FastAPI rejects out-of-range page windows before the service runs."""
    assert frozen_client.get(OBLIGATIONS_URL, params=params).status_code == 422


# --------------------------------------------------------------------------- #
# Project filter options
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_project_options_are_the_distinct_projects_with_obligations(frozen_client):
    """/projects lists each project that has obligations exactly once, by name."""
    resp = frozen_client.get(PROJECT_OPTIONS_URL)
    assert resp.status_code == 200
    body = resp.json()

    instance_project_ids = {
        o["project"]["id"] for o in _items(frozen_client.get(OBLIGATIONS_URL))
    }
    assert {p["id"] for p in body} == instance_project_ids
    assert len(body) == len(instance_project_ids)
    assert set(body[0]) == {"id", "name"}
    assert [p["name"] for p in body] == sorted(p["name"] for p in body)
    # Names are resolved, not left blank.
    assert all(p["name"] for p in body)


# --------------------------------------------------------------------------- #
# Business Central read cost
#
# The reads below are the whole point of the listing's read order. Measured
# against the live tenant, ``get_customers()`` cost 2.24s (789 rows, plus a second
# company-wide projects sweep it does internally for a field this domain never
# reads) out of a 3.7s request. These tests fail if it comes back.
# --------------------------------------------------------------------------- #


class _CountingBCClient:
    """Wraps a BC client, counting how many times each getter is called."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: Counter[str] = Counter()
        self.customer_name_ids: list[list[str]] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            self.calls[name] += 1
            if name == "get_customer_names":
                self.customer_name_ids.append(list(args[0] if args else kwargs["customer_ids"]))
            return attr(*args, **kwargs)

        return wrapped


def _counting_service(db_session):
    bc = _CountingBCClient(MockBusinessCentralClient())
    return ObligationsService(db_session, bc), bc


@pytest.mark.integration
def test_listing_resolves_client_names_without_reading_every_customer(db_session):
    """Client names come from the scoped read, never from get_customers()."""
    service, bc = _counting_service(db_session)

    rows = service.list_project_obligations(reference_date=FROZEN_TODAY)

    assert bc.calls["get_customers"] == 0
    assert bc.calls["get_customer_names"] == 1
    # The names still resolve — the cheap read is not a downgrade.
    assert all(r.client.name for r in rows)


@pytest.mark.integration
def test_listing_asks_only_for_the_customers_it_mentions(db_session):
    """The scoped read receives the referenced customer ids and nothing else."""
    service, bc = _counting_service(db_session)

    rows = service.list_project_obligations(reference_date=FROZEN_TODAY)

    expected = sorted({r.client.id for r in rows if r.client.id})
    assert bc.customer_name_ids == [expected]
    # Blank ids are dropped rather than sent as a wasted filter clause.
    assert "" not in bc.customer_name_ids[0]


@pytest.mark.integration
def test_project_filter_narrows_the_customer_read_too(db_session):
    """Filtering to one project asks for that project's customer only."""
    service, bc = _counting_service(db_session)

    service.list_project_obligations(
        reference_date=FROZEN_TODAY, project_id="proj-012"
    )

    assert bc.calls["get_customers"] == 0
    assert len(bc.customer_name_ids[0]) == 1


@pytest.mark.integration
def test_a_filter_matching_nothing_skips_every_enrichment_read(db_session):
    """No surviving instances means no catalog, projects or customers read at all."""
    service, bc = _counting_service(db_session)

    assert service.list_project_obligations(
        reference_date=FROZEN_TODAY, project_id="no-such-project"
    ) == []

    assert bc.calls["get_project_obligations"] == 1
    assert bc.calls["get_obligations"] == 0
    assert bc.calls["get_projects"] == 0
    assert bc.calls["get_customer_names"] == 0


@pytest.mark.integration
def test_project_options_read_only_the_two_cheap_sources(db_session):
    """The filter options need the links and the projects — nothing else."""
    service, bc = _counting_service(db_session)

    assert service.list_obligation_projects()

    assert bc.calls["get_project_obligations"] == 1
    assert bc.calls["get_projects"] == 1
    assert bc.calls["get_obligations"] == 0
    assert bc.calls["get_customers"] == 0
    assert bc.calls["get_customer_names"] == 0


@pytest.mark.integration
def test_project_options_are_empty_without_touching_projects(db_session):
    """With no obligation links there is nothing to name, so projects is not read."""
    bc = _CountingBCClient(MockBusinessCentralClient())
    bc._inner.get_project_obligations = lambda: []
    service = ObligationsService(db_session, bc)

    assert service.list_obligation_projects() == []
    assert bc.calls["get_projects"] == 0


# --------------------------------------------------------------------------- #
# Live-shaped data: obligations / links with no dates (issue #40)
# --------------------------------------------------------------------------- #


class _LiveShapedBCClient(BusinessCentralClient):
    """A stand-in BC client shaped like the real (thin) BC payloads.

    Obligations expose only code/name (no periodicity/rule) and project-obligation
    links carry no subject/dates/status — exactly what the live client returns
    today, so we can exercise the ``due_date is None`` path without HTTP mocking.
    """

    def get_customers(self, **kwargs):
        return [
            BCCustomer(
                id="C1",
                name="Acme SL",
                nif="A1",
                customer_type="Company",
                responsible="MS",
                active_project_count=1,
                status=CustomerStatus.active,
            )
        ]

    def get_customers_page(self, **kwargs):
        return BCCustomerPage(items=self.get_customers(), next_cursor=None)

    def get_customer_refs_page(self, **kwargs):
        return BCCustomerRefPage(
            items=[BCCustomerRef(id=c.id, name=c.name) for c in self.get_customers()],
            total_count=len(self.get_customers()),
        )

    def get_projects(self, **kwargs):
        return [
            BCProject(
                id="P1",
                name="Fiscal advisory",
                customer_id="C1",
                responsible="",
                technician="",
                status=ProjectStatus.active,
            )
        ]

    def get_projects_page(self, **kwargs):
        return BCProjectPage(items=self.get_projects(), next_cursor=None)

    def get_customer_names(self, customer_ids):
        wanted = set(customer_ids)
        return {c.id: c.name for c in self.get_customers() if c.id in wanted}

    def get_users(self):
        return []

    def get_customer_resources(self):
        return []

    def get_user_tasks(self):
        return []

    def get_obligations(self):
        return [BCObligation(id="IRPF", code="IRPF", name="IRPF")]

    def get_project_obligations(self):
        return [
            BCProjectObligation(id="po-1", project_id="P1", obligation_id="IRPF")
        ]

    def get_sales_invoice_headers(self):
        return []

    def get_sales_invoice_lines(self):
        return []

    def get_sales_cr_memo_headers(self):
        return []

    def get_sales_cr_memo_lines(self):
        return []

    def get_job_ledger_entries(self):
        return []

    def get_time_sheet_posting_entries(self):
        return []

    def get_resources(self):
        return []


@pytest.mark.unit
def test_catalog_carries_none_periodicity_for_live_shaped_obligation():
    """A live-shaped obligation surfaces with periodicity/rule as None."""
    service = ObligationsService(db=None, bc_client=_LiveShapedBCClient())
    catalog = service.list_catalog()
    assert len(catalog) == 1
    assert catalog[0].code == "IRPF"
    assert catalog[0].periodicity is None
    assert catalog[0].due_date_rule is None


@pytest.mark.unit
def test_undated_instance_does_not_crash_and_is_sin_fecha():
    """A dateless link is mapped to Sin fecha, resolving its display names."""
    service = ObligationsService(db=None, bc_client=_LiveShapedBCClient())
    result = service.list_project_obligations(reference_date=FROZEN_TODAY)
    assert len(result) == 1
    row = result[0]
    assert row.due_date is None
    assert row.subject is None
    assert row.status is DerivedObligationStatus.undated
    # Display names still resolve from the catalog/project/customer.
    assert row.obligation.name == "IRPF"
    assert row.project.name == "Fiscal advisory"
    assert row.client.name == "Acme SL"


@pytest.mark.unit
def test_undated_instances_excluded_from_date_bounded_filters():
    """Undated instances never match a due_after / due_before bound."""
    service = ObligationsService(db=None, bc_client=_LiveShapedBCClient())
    assert service.list_project_obligations(
        reference_date=FROZEN_TODAY, due_after=date(2020, 1, 1)
    ) == []
    assert service.list_project_obligations(
        reference_date=FROZEN_TODAY, due_before=date(2030, 1, 1)
    ) == []
    # ...but a status filter for the undated bucket still returns them.
    undated = service.list_project_obligations(
        reference_date=FROZEN_TODAY, status=DerivedObligationStatus.undated
    )
    assert {r.id for r in undated} == {"po-1"}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


@pytest.mark.auth
def test_catalog_requires_authentication(db_session):
    """Without a verified user the catalog endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(CATALOG_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.auth
def test_instances_require_authentication(db_session):
    """Without a verified user the instances endpoint refuses the request."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as unauth_client:
            resp = unauth_client.get(OBLIGATIONS_URL)
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
