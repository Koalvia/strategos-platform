"""Tests for the live Business Central client (issue #39).

The HTTP layer is fully mocked with ``httpx.MockTransport`` — these tests never
touch the real Business Central API and use synthetic fixtures shaped like the
confirmed BC payloads (no real Strategos client data / PII). They cover:

* OAuth2 token acquisition, in-memory caching (reuse across calls) and refresh
  on expiry;
* OData ``@odata.nextLink`` pagination;
* the ``blocked`` / ``partnerType`` / ``jobStatus`` field mappings, including the
  ``_x0020_`` blank-Option case;
* the computed ``active_project_count``;
* the obligations / projectObligations mapping, including the
  ``periodicity``/``dueDateRule`` and ``subject``/``dueDate``/``submissionDate``
  fields BC now provides (and the undated fallback when a date is absent);
* that the still-deferred ``userTasks`` entity returns ``[]`` with a warning
  logged, instead of raising;
* the ``resources``/``customersResources`` mapping behind the visibility scope,
  including its degradation to ``[]`` on a failed read.
"""

import logging
from datetime import date

import httpx
import pytest

from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.obligations.service import derive_status
from app.integrations.business_central.live_client import (
    LiveBusinessCentralClient,
    _encode_offset,
)
from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerResource,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCUser,
    CustomerStatus,
    ProjectStatus,
)

# Dummy, non-secret connection settings — only used to shape the mocked URLs.
_CONFIG = dict(
    tenant_id="test-tenant",
    environment="RESTSTR",
    company_id="test-company",
    client_id="test-client",
    client_secret="test-secret",
    publisher="strategos",
    api_group="integrations",
    api_version="v1.0",
)

_TOKEN_HOST = "login.microsoftonline.com"


class _MutableClock:
    """A hand-cranked monotonic clock so token-expiry can be tested."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _page(rows, next_link=None):
    """An OData collection envelope, optionally advertising a next page."""
    body = {"value": rows}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return body


def _build(
    *,
    customers_pages=None,
    projects=None,
    users=None,
    obligations=None,
    project_obligations=None,
    expires_in=3600,
    clock=None,
):
    """Build a live client wired to a MockTransport plus a request recorder.

    ``customers_pages`` is a list of pages (each a list of rows) so pagination can
    be exercised; ``projects``/``users``/``obligations``/``project_obligations``
    are single-page row lists.
    """
    customers_pages = customers_pages or [[]]
    projects = projects if projects is not None else []
    users = users if users is not None else []
    obligations = obligations if obligations is not None else []
    project_obligations = (
        project_obligations if project_obligations is not None else []
    )
    calls = {
        "token": 0,
        "customers": 0,
        "projects": 0,
        "users": 0,
        "obligations": 0,
        "projectObligations": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == _TOKEN_HOST:
            calls["token"] += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{calls['token']}",
                    "expires_in": expires_in,
                    "token_type": "Bearer",
                },
            )

        # Every entity read must carry the bearer token.
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        path = url.path

        if path.endswith("/customers"):
            calls["customers"] += 1
            page_index = int(url.params.get("page", "0"))
            rows = customers_pages[page_index]
            next_link = None
            if page_index + 1 < len(customers_pages):
                next_link = str(url.copy_set_param("page", str(page_index + 1)))
            return httpx.Response(200, json=_page(rows, next_link))

        if path.endswith("/projects"):
            calls["projects"] += 1
            return httpx.Response(200, json=_page(projects))

        if path.endswith("/users"):
            calls["users"] += 1
            return httpx.Response(200, json=_page(users))

        if path.endswith("/projectObligations"):
            calls["projectObligations"] += 1
            return httpx.Response(200, json=_page(project_obligations))

        if path.endswith("/obligations"):
            calls["obligations"] += 1
            return httpx.Response(200, json=_page(obligations))

        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveBusinessCentralClient(
        **_CONFIG,
        http_client=http_client,
        clock=clock or (lambda: 0.0),
    )
    return client, calls


@pytest.mark.unit
def test_token_acquired_once_and_reused_across_calls():
    """A burst of reads authenticates exactly once."""
    client, calls = _build(users=[{"userSecurityID": "g1", "fullName": "A"}])

    client.get_users()
    client.get_users()

    assert calls["token"] == 1
    assert calls["users"] == 2


@pytest.mark.unit
def test_token_refreshed_after_expiry():
    """Once the cached token lapses, the next call requests a fresh one."""
    clock = _MutableClock()
    client, calls = _build(
        users=[{"userSecurityID": "g1", "fullName": "A"}],
        expires_in=3600,
        clock=clock,
    )

    client.get_users()
    assert calls["token"] == 1

    # Still valid a minute later — no new token.
    clock.advance(60)
    client.get_users()
    assert calls["token"] == 1

    # Past expiry (minus the safety skew) — refresh.
    clock.advance(3600)
    client.get_users()
    assert calls["token"] == 2


@pytest.mark.unit
def test_pagination_follows_next_link():
    """All pages are read by following ``@odata.nextLink`` until exhausted."""
    pages = [
        [{"no": f"C{i:02d}", "name": f"Customer {i}"} for i in range(3)],
        [{"no": f"C{i:02d}", "name": f"Customer {i}"} for i in range(3, 5)],
        [{"no": "C05", "name": "Customer 5"}],
    ]
    client, calls = _build(customers_pages=pages)

    customers = client.get_customers()

    assert calls["customers"] == 3
    assert [c.id for c in customers] == ["C00", "C01", "C02", "C03", "C04", "C05"]
    assert all(isinstance(c, BCCustomer) for c in customers)


def _build_customers_page(
    *,
    customers_rows=None,
    projects_rows=None,
):
    """Build a live client + request recorder for ``get_customers_page`` tests.

    Unlike ``_build`` (which exercises the full-drain ``get_customers``/
    ``get_projects``), this records every request so tests can assert exactly
    what query BC was sent (``$top``/``$skip``/``$filter``) and which paths were hit.
    It ignores the paging window; tests needing real slicing build their own transport.
    """
    customers_rows = customers_rows if customers_rows is not None else []
    projects_rows = projects_rows if projects_rows is not None else []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == _TOKEN_HOST:
            return httpx.Response(
                200,
                json={
                    "access_token": "token-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

        assert request.headers.get("Authorization", "").startswith("Bearer ")
        path = request.url.path

        if path.endswith("/customers"):
            return httpx.Response(200, json={"value": customers_rows})

        if path.endswith("/projects"):
            return httpx.Response(200, json={"value": projects_rows})

        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveBusinessCentralClient(
        **_CONFIG, http_client=http_client, clock=lambda: 0.0
    )
    return client, requests


@pytest.mark.unit
def test_unfiltered_customers_page_is_one_window_and_no_filter():
    """The cheap path: one ``$skip`` window, no ``$filter`` at all.

    ``$top`` is page_size + 1 — the extra row is the probe for "is there more".
    """
    rows = [{"no": "C1", "name": "Acme SL", "vatRegistrationNo": "A1", "blocked": ""}]
    client, requests = _build_customers_page(customers_rows=rows)

    client.get_customers_page(page_size=5)

    params = next(r for r in requests if r.url.path.endswith("/customers")).url.params
    assert params["$top"] == "6"
    assert params["$skip"] == "0"
    assert params["$orderby"] == "no"
    assert params.get("$filter") is None


@pytest.mark.unit
def test_customers_search_is_not_pushed_down_to_bc():
    """Searching must not send a ``$filter``: BC answers 501 to the clause we built.

    An ``or`` of ``contains`` across name and vatRegistrationNo is Not Implemented on
    this API page, which made every search a 500 for the caller.
    """
    client, requests = _build_customers_page(customers_rows=[])

    client.get_customers_page(search="acme", status=CustomerStatus.active)

    for request in requests:
        assert request.url.params.get("$filter") is None


@pytest.mark.unit
def test_customers_search_matches_name_or_nif_case_insensitively():
    """BC's ``contains`` is case-sensitive; matching in memory is not.

    Customer names come back uppercase, so a lowercase search used to find nothing.
    """
    rows = [
        {"no": "C1", "name": "ANDBANK SA", "vatRegistrationNo": "A-700123", "blocked": ""},
        {"no": "C2", "name": "CREDIT ANDORRA", "vatRegistrationNo": "A-800999", "blocked": ""},
    ]
    client, _ = _build_customers_page(customers_rows=rows)

    by_name = client.get_customers_page(search="andbank")
    by_nif = client.get_customers_page(search="a-800")
    no_match = client.get_customers_page(search="zzz")

    assert [c.id for c in by_name.items] == ["C1"]
    assert [c.id for c in by_nif.items] == ["C2"]
    assert no_match.items == []


@pytest.mark.unit
def test_customers_status_filter_is_applied_in_memory():
    """``blocked`` cannot be compared in a ``$filter`` (BC answers 400)."""
    rows = [
        {"no": "C1", "name": "Open", "blocked": ""},
        {"no": "C2", "name": "Blank sentinel", "blocked": "_x0020_"},
        {"no": "C3", "name": "Blocked", "blocked": "All"},
    ]
    client, _ = _build_customers_page(customers_rows=rows)

    active = client.get_customers_page(status=CustomerStatus.active)
    inactive = client.get_customers_page(status=CustomerStatus.inactive)

    # Both blank sentinels count as active, as _clean_option treats them.
    assert [c.id for c in active.items] == ["C1", "C2"]
    assert [c.id for c in inactive.items] == ["C3"]


@pytest.mark.unit
def test_customers_page_scopes_project_count_to_page_customer_ids():
    """``active_project_count`` is computed from a projects query scoped to
    just this page's customer ids, not a company-wide fetch."""
    rows = [
        {"no": "C1", "name": "Acme", "blocked": ""},
        {"no": "C2", "name": "Beta", "blocked": ""},
    ]
    projects = [
        {"no": "P1", "billToCustomerNo": "C1", "status": "Open"},
        {"no": "P2", "billToCustomerNo": "C1", "status": "Completed"},
        {"no": "P3", "billToCustomerNo": "C2", "status": "Open"},
    ]
    client, requests = _build_customers_page(customers_rows=rows, projects_rows=projects)

    page = client.get_customers_page(page_size=2)

    by_id = {c.id: c for c in page.items}
    assert by_id["C1"].active_project_count == 1
    assert by_id["C2"].active_project_count == 1

    projects_request = next(r for r in requests if r.url.path.endswith("/projects"))
    filter_value = projects_request.url.params["$filter"]
    assert "billToCustomerNo eq 'C1'" in filter_value
    assert "billToCustomerNo eq 'C2'" in filter_value


@pytest.mark.unit
def test_customers_page_no_rows_skips_projects_request():
    """An empty page (e.g. a search matching nothing) never queries projects."""
    client, requests = _build_customers_page(customers_rows=[])

    page = client.get_customers_page()

    assert page.items == []
    assert not any(r.url.path.endswith("/projects") for r in requests)


def _customer_rows(count: int) -> list[dict]:
    """``count`` customer rows, ids ordered C001..C0NN."""
    return [
        {"no": f"C{i:03d}", "name": f"Customer {i:03d}", "blocked": ""}
        for i in range(1, count + 1)
    ]


@pytest.mark.unit
def test_customers_page_offers_a_cursor_without_a_next_link():
    """A cursor is offered even though BC sends no ``@odata.nextLink``.

    That is the real tenant's shape, and deriving the cursor from the link left a
    manager stuck on page one — 25 of 789 customers.
    """
    client, _ = _build_customers_page(customers_rows=_customer_rows(6))

    page = client.get_customers_page(page_size=5)

    assert page.next_cursor is not None
    # The 6th row is only a probe for "is there more" — it must not reach the caller.
    assert [c.id for c in page.items] == ["C001", "C002", "C003", "C004", "C005"]


@pytest.mark.unit
def test_customers_page_last_page_has_no_cursor():
    """Exactly a page's worth of rows means there is nothing after it."""
    client, _ = _build_customers_page(customers_rows=_customer_rows(5))

    page = client.get_customers_page(page_size=5)

    assert page.next_cursor is None
    assert len(page.items) == 5


@pytest.mark.unit
def test_customers_page_cursor_advances_the_skip_window():
    """A continuation asks BC for the next window rather than following a link."""
    client, requests = _build_customers_page(customers_rows=_customer_rows(6))

    page = client.get_customers_page(page_size=5)

    requests.clear()
    client.get_customers_page(page_size=5, cursor=page.next_cursor)

    params = next(r for r in requests if r.url.path.endswith("/customers")).url.params
    assert params["$skip"] == "5"
    assert params["$top"] == "6"


@pytest.mark.unit
def test_searched_customers_still_paginate():
    """A filtered listing pages in memory, and its pages do not overlap."""
    rows = [
        {"no": f"C{i:03d}", "name": f"ACME {i:03d}", "blocked": ""} for i in range(1, 8)
    ] + [{"no": "C900", "name": "OTHER", "blocked": ""}]
    client, _ = _build_customers_page(customers_rows=rows)

    first = client.get_customers_page(search="acme", page_size=5)
    second = client.get_customers_page(
        search="acme", page_size=5, cursor=first.next_cursor
    )

    assert [c.id for c in first.items] == ["C001", "C002", "C003", "C004", "C005"]
    assert [c.id for c in second.items] == ["C006", "C007"]
    assert second.next_cursor is None


@pytest.mark.unit
def test_customers_pages_partition_every_row():
    """Walking the cursors covers every row once — no gaps, no repeats.

    The transport honours ``$skip``/``$top``, so this drives the real paging walk.
    """
    all_rows = _customer_rows(23)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _TOKEN_HOST:
            return httpx.Response(
                200,
                json={"access_token": "t", "expires_in": 3600, "token_type": "Bearer"},
            )
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json={"value": []})

        params = request.url.params
        assert params["$orderby"] == "no", "an unordered $skip window can repeat rows"
        skip = int(params["$skip"])
        top = int(params["$top"])
        return httpx.Response(200, json={"value": all_rows[skip : skip + top]})

    client = LiveBusinessCentralClient(
        **_CONFIG,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: 0.0,
    )

    seen: list[str] = []
    cursor, pages = None, 0
    while True:
        page = client.get_customers_page(cursor=cursor, page_size=10)
        seen.extend(c.id for c in page.items)
        cursor = page.next_cursor
        pages += 1
        if cursor is None:
            break

    assert pages == 3
    assert seen == [row["no"] for row in all_rows]
    assert len(seen) == len(set(seen))


def _build_projects_page(
    *,
    projects_rows=None,
    customers_rows=None,
):
    """Build a live client + request recorder for ``get_projects_page``/
    ``get_customer_names`` tests, mirroring ``_build_customers_page``."""
    projects_rows = projects_rows if projects_rows is not None else []
    customers_rows = customers_rows if customers_rows is not None else []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == _TOKEN_HOST:
            return httpx.Response(
                200,
                json={
                    "access_token": "token-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

        assert request.headers.get("Authorization", "").startswith("Bearer ")
        path = request.url.path

        if path.endswith("/projects"):
            return httpx.Response(200, json={"value": projects_rows})

        if path.endswith("/customers"):
            return httpx.Response(200, json={"value": customers_rows})

        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveBusinessCentralClient(
        **_CONFIG, http_client=http_client, clock=lambda: 0.0
    )
    return client, requests


@pytest.mark.unit
def test_unfiltered_projects_page_is_one_window_and_no_filter():
    """The cheap path: one ``$skip`` window, no ``$filter`` at all."""
    rows = [{"no": "P1", "description": "Fiscal advisory", "status": "Open"}]
    client, requests = _build_projects_page(projects_rows=rows)

    client.get_projects_page(page_size=5)

    params = next(r for r in requests if r.url.path.endswith("/projects")).url.params
    assert params["$top"] == "6"
    assert params["$skip"] == "0"
    assert params["$orderby"] == "no"
    assert params.get("$filter") is None


@pytest.mark.unit
def test_projects_search_and_status_are_applied_in_memory():
    """Neither is pushed down: BC's ``contains`` is case-sensitive and ``tolower`` 400s."""
    rows = [
        {"no": "P1", "description": "FISCAL ADVISORY", "status": "Open"},
        {"no": "P2", "description": "AUDIT", "status": "Completed"},
    ]
    client, requests = _build_projects_page(projects_rows=rows)

    found = client.get_projects_page(search="fiscal", status=ProjectStatus.active)
    completed = client.get_projects_page(status=ProjectStatus.inactive)

    assert [p.id for p in found.items] == ["P1"]
    assert [p.id for p in completed.items] == ["P2"]
    for request in requests:
        assert "contains" not in (request.url.params.get("$filter") or "")
        assert "tolower" not in (request.url.params.get("$filter") or "")


@pytest.mark.unit
def test_projects_page_pushes_customer_id_down_as_an_id_clause():
    """``billToCustomerNo eq`` is the one filter BC honours, so it stays server-side."""
    rows = [{"no": "P1", "description": "Fiscal advisory", "status": "Open"}]
    client, requests = _build_projects_page(projects_rows=rows)

    client.get_projects_page(
        search="fiscal", status=ProjectStatus.active, customer_id="C1"
    )

    clauses = [
        r.url.params.get("$filter")
        for r in requests
        if r.url.path.endswith("/projects")
    ]
    assert clauses == ["billToCustomerNo eq 'C1'"]


@pytest.mark.unit
def test_projects_page_short_circuits_when_type_or_entity_given():
    """``project_type``/``entity_type`` have no BC field, so a page with either
    set returns empty without ever issuing a request."""
    client, requests = _build_projects_page(
        projects_rows=[{"no": "P1", "description": "x", "status": "Open"}]
    )

    page = client.get_projects_page(project_type="Iguala mensual")
    assert page.items == []
    assert page.next_cursor is None
    assert requests == []

    page = client.get_projects_page(entity_type="Societat")
    assert page.items == []
    assert requests == []


@pytest.mark.unit
def test_projects_page_advances_by_skip_without_a_next_link():
    """Projects page by offset too, with no ``nextLink`` in the response."""
    rows = [
        {"no": f"P{i:03d}", "description": f"Project {i}", "status": "Open"}
        for i in range(1, 7)
    ]
    client, requests = _build_projects_page(projects_rows=rows)

    page = client.get_projects_page(page_size=5)
    assert page.next_cursor is not None
    assert len(page.items) == 5

    requests.clear()
    client.get_projects_page(page_size=5, cursor=page.next_cursor)

    params = next(r for r in requests if r.url.path.endswith("/projects")).url.params
    assert params["$skip"] == "5"
    assert params["$top"] == "6"


@pytest.mark.unit
def test_projects_page_unsupported_filter_is_empty_on_a_continuation_too():
    """``project_type`` has no BC field, so no page can claim to honour it.

    The guard used to be skipped when a cursor was present: page 1 empty, page 2 full.
    """
    client, requests = _build_projects_page(
        projects_rows=[{"no": "P1", "description": "x", "status": "Open"}]
    )

    page = client.get_projects_page(project_type="Anything", cursor=_encode_offset(5))

    assert page.items == []
    assert not any(r.url.path.endswith("/projects") for r in requests)


@pytest.mark.unit
def test_get_customer_names_scopes_filter_to_requested_ids():
    """``get_customer_names`` issues a single scoped ``$filter`` and never
    computes ``active_project_count`` (no ``/projects`` request at all)."""
    customers = [
        {"no": "C1", "name": "Acme SL"},
        {"no": "C2", "name": "Beta SL"},
    ]
    client, requests = _build_projects_page(customers_rows=customers)

    names = client.get_customer_names(["C1", "C2"])

    assert names == {"C1": "Acme SL", "C2": "Beta SL"}
    assert not any(r.url.path.endswith("/projects") for r in requests)
    customers_request = next(r for r in requests if r.url.path.endswith("/customers"))
    filter_value = customers_request.url.params["$filter"]
    assert "no eq 'C1'" in filter_value
    assert "no eq 'C2'" in filter_value


@pytest.mark.unit
def test_get_customer_names_empty_ids_issues_no_request():
    """An empty id list short-circuits without any HTTP call."""
    client, requests = _build_projects_page()
    assert client.get_customer_names([]) == {}
    assert requests == []


@pytest.mark.unit
def test_customer_field_mapping_and_status():
    """Customers map from BC ``customer`` fields with the confirmed rules."""
    customers_pages = [
        [
            {
                "no": "C00030",
                "name": "Acme SL",
                "vatRegistrationNo": "A123456",
                "partnerType": "Company",
                "salespersonCode": "MS",
                "blocked": "",  # not blocked -> Activo
            },
            {
                "no": "C00031",
                "name": "Blank Option Co",
                "vatRegistrationNo": "B234567",
                "partnerType": "_x0020_",  # blank Option escape -> normalised away
                "salespersonCode": "AF",
                "blocked": "_x0020_",  # blank Option escape -> still Activo
            },
            {
                "no": "C00032",
                "name": "Blocked Co",
                "vatRegistrationNo": "C345678",
                "partnerType": "Person",
                "salespersonCode": "LP",
                "blocked": "All",  # any non-blank value -> Inactivo
            },
        ]
    ]
    projects = [
        {"no": "P1", "billToCustomerNo": "C00030", "status": "Open"},
        {"no": "P2", "billToCustomerNo": "C00030", "status": "Completed"},
        {"no": "P3", "billToCustomerNo": "C00032", "status": "Open"},
    ]
    client, _ = _build(customers_pages=customers_pages, projects=projects)

    by_id = {c.id: c for c in client.get_customers()}

    acme = by_id["C00030"]
    assert acme.name == "Acme SL"
    assert acme.nif == "A123456"
    assert acme.customer_type == "Company"
    assert acme.responsible == "MS"
    assert acme.status is CustomerStatus.active
    # Only the Open project counts, the Completed one does not.
    assert acme.active_project_count == 1

    blank = by_id["C00031"]
    assert blank.customer_type == ""  # _x0020_ collapsed to blank
    assert blank.status is CustomerStatus.active
    assert blank.active_project_count == 0

    blocked = by_id["C00032"]
    assert blocked.status is CustomerStatus.inactive
    assert blocked.active_project_count == 1


@pytest.mark.unit
def test_project_field_mapping_and_status():
    """Projects map from BC ``project`` fields; absent fields stay unset."""
    projects = [
        {
            "no": "P00011",
            "description": "Fiscal advisory",
            "billToCustomerNo": "C00030",
            "personResponsible": "",
            "projectManager": "",
            "status": "Open",
        },
        {"no": "P2", "description": "Done job", "status": "Completed"},
        {"no": "P3", "description": "Planned job", "status": "Planning"},
        {"no": "P4", "description": "Quoted job", "status": "Quote"},
    ]
    client, _ = _build(projects=projects)

    by_id = {p.id: p for p in client.get_projects()}
    assert all(isinstance(p, BCProject) for p in by_id.values())

    open_project = by_id["P00011"]
    assert open_project.name == "Fiscal advisory"
    assert open_project.customer_id == "C00030"
    assert open_project.responsible == ""
    assert open_project.technician == ""
    assert open_project.status is ProjectStatus.active
    # No BC source -> left unset.
    assert open_project.project_type is None
    assert open_project.entity_type is None
    assert open_project.has_certificate is None
    assert open_project.certificate_expiry is None
    assert open_project.filing_date is None

    assert by_id["P2"].status is ProjectStatus.inactive
    assert by_id["P3"].status is ProjectStatus.active
    assert by_id["P4"].status is ProjectStatus.active


@pytest.mark.unit
def test_user_field_mapping_with_email_fallback():
    """Users map from BC ``user`` fields, falling back to authenticationEmail."""
    users = [
        {
            "userSecurityID": "11111111-1111-1111-1111-111111111111",
            "userName": "AGUSTINA",
            "fullName": "Contact Email User",
            "contactEmail": "contact@estrategos.ad",
            "authenticationEmail": "auth@estrategos.ad",
        },
        {
            "userSecurityID": "22222222-2222-2222-2222-222222222222",
            "fullName": "Fallback User",
            "contactEmail": "",
            "authenticationEmail": "fallback@estrategos.ad",
        },
    ]
    client, _ = _build(users=users)

    result = client.get_users()
    assert all(isinstance(u, BCUser) for u in result)
    assert result[0].id == "11111111-1111-1111-1111-111111111111"
    assert result[0].name == "Contact Email User"
    assert result[0].email == "contact@estrategos.ad"
    # userName is the code userSetups is keyed by; absent, it stays blank.
    assert result[0].user_name == "AGUSTINA"
    # Blank contactEmail falls back to authenticationEmail.
    assert result[1].email == "fallback@estrategos.ad"
    assert result[1].user_name == ""


@pytest.mark.unit
def test_obligation_catalog_mapping():
    """Obligations map ``code``/``description``/``periodicity``/``dueDateRule``.

    BC serializes the ``periodicity``/``dueDateRule`` ``DateFormula`` values as
    plain strings (``"1Y"``/``"5Y"``); absent fields stay unset.
    """
    obligations = [
        {
            "code": "IRPF",
            "description": "Impost sobre la renda",
            "periodicity": "1Y",
            "dueDateRule": "5Y",
        },
        {"code": "IGI"},  # description/periodicity/rule absent -> unset, still valid
    ]
    client, _ = _build(obligations=obligations)

    result = client.get_obligations()
    assert all(isinstance(o, BCObligation) for o in result)

    irpf = result[0]
    assert irpf.id == "IRPF"
    assert irpf.code == "IRPF"
    assert irpf.name == "Impost sobre la renda"
    # Raw DateFormula strings, mapped verbatim.
    assert irpf.periodicity == "1Y"
    assert irpf.due_date_rule == "5Y"

    igi = result[1]
    assert igi.name == ""
    assert igi.periodicity is None
    assert igi.due_date_rule is None


@pytest.mark.unit
def test_project_obligation_link_mapping():
    """Project-obligation links map subject/dueDate/submissionDate through.

    Uses the confirmed IRPF/P00011 shape: a filed obligation (``submissionDate``
    present) is no longer undated — ``derive_status`` classifies it ``on_track``.
    """
    project_obligations = [
        {
            "systemId": "aaaaaaaa-1111-2222-3333-444444444444",
            "jobNo": "P00011",
            "obligationCode": "IRPF",
            "subject": False,
            "dueDate": "2026-07-31",
            "submissionDate": "2026-07-01",
        }
    ]
    client, _ = _build(project_obligations=project_obligations)

    result = client.get_project_obligations()
    assert all(isinstance(i, BCProjectObligation) for i in result)

    instance = result[0]
    assert instance.id == "aaaaaaaa-1111-2222-3333-444444444444"
    assert instance.project_id == "P00011"
    assert instance.obligation_id == "IRPF"
    assert instance.subject is False
    assert instance.due_date == date(2026, 7, 31)
    assert instance.submission_date == date(2026, 7, 1)
    # No BC source for status.
    assert instance.status is None

    # A filed instance with a due date is no longer "sin fecha".
    status = derive_status(
        instance.due_date,
        instance.submission_date,
        reference_date=date(2026, 7, 13),
    )
    assert status is DerivedObligationStatus.on_track


@pytest.mark.unit
def test_project_obligation_without_due_date_stays_undated():
    """An instance BC returns without a ``dueDate`` remains undated."""
    project_obligations = [
        {
            "systemId": "bbbbbbbb-1111-2222-3333-444444444444",
            "jobNo": "P00012",
            "obligationCode": "IGI",
        }
    ]
    client, _ = _build(project_obligations=project_obligations)

    instance = client.get_project_obligations()[0]
    assert instance.subject is None
    assert instance.due_date is None
    assert instance.submission_date is None

    status = derive_status(
        instance.due_date,
        instance.submission_date,
        reference_date=date(2026, 7, 13),
    )
    assert status is DerivedObligationStatus.undated


@pytest.mark.unit
def test_user_tasks_returns_empty_list_and_logs_warning(caplog):
    """userTasks stays deferred: returns [] and logs a warning, doesn't raise."""
    client, _ = _build()

    with caplog.at_level(logging.WARNING):
        tasks = client.get_user_tasks()

    assert tasks == []
    assert any(
        "get_user_tasks" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )


@pytest.mark.unit
def test_base_url_matches_documented_pattern():
    """The company-scoped base URL matches the confirmed BC pattern."""
    client, _ = _build()
    assert client._base_url == (
        "https://api.businesscentral.dynamics.com/v2.0/test-tenant/RESTSTR/api/"
        "strategos/integrations/v1.0/companies(test-company)"
    )


# --------------------------------------------------------------------------- #
# Billing / Costs
# --------------------------------------------------------------------------- #


def _build_billing(**rows_by_entity):
    """Build a live client + request recorder returning rows per entity.

    Keys are BC entity names (``salesInvoiceHeaders`` etc.); each value is the
    row list that entity's read should return. An entity with no rows configured
    answers 404, which is how failed-read paths are exercised.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == _TOKEN_HOST:
            return httpx.Response(
                200,
                json={
                    "access_token": "token-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

        assert request.headers.get("Authorization", "").startswith("Bearer ")
        entity = request.url.path.rsplit("/", 1)[-1]
        if entity in rows_by_entity:
            return httpx.Response(200, json=_page(rows_by_entity[entity]))
        return httpx.Response(404, json={"error": f"unexpected path {request.url.path}"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveBusinessCentralClient(
        **_CONFIG, http_client=http_client, clock=lambda: 0.0
    )
    return client, requests


@pytest.mark.unit
def test_sales_invoice_header_and_line_mapping():
    """Headers map no/customer/postingDate; lines map amount/jobNo/type/number.

    The customer comes from ``billToCustomerNo`` — the same field projects are
    attributed by — so ``sellToCustomerNo`` is present here and deliberately
    ignored.
    """
    client, _ = _build_billing(
        salesInvoiceHeaders=[
            {
                "no": "INV-1",
                "billToCustomerNo": "C1",
                "sellToCustomerNo": "C9",
                "postingDate": "2026-01-15",
            }
        ],
        salesInvoiceLines=[
            {
                "documentNo": "INV-1",
                "lineAmount": 1000.5,
                "jobNo": "P1",
                "type": "Resource",
                "number": "RES-01",
            },
            # Non-project line: blank jobNo collapses to project_id None.
            {"documentNo": "INV-1", "lineAmount": 300, "jobNo": "", "type": "G/L Account"},
        ],
    )

    header = client.get_sales_invoice_headers()[0]
    assert header.document_no == "INV-1"
    assert header.customer_id == "C1"
    assert header.posting_date == date(2026, 1, 15)

    lines = client.get_sales_invoice_lines()
    assert lines[0].document_no == "INV-1"
    assert lines[0].line_amount == 1000.5
    assert lines[0].project_id == "P1"
    assert lines[0].line_type == "Resource"
    assert lines[0].number == "RES-01"
    assert lines[1].project_id is None


@pytest.mark.unit
def test_sales_cr_memo_mapping():
    """Credit-memo headers and lines map like invoices (amount subtracts later)."""
    client, _ = _build_billing(
        salesCrMemoHeaders=[
            {
                "no": "CM-1",
                "billToCustomerNo": "C1",
                "sellToCustomerNo": "C9",
                "postingDate": "2026-02-20",
            }
        ],
        salesCrMemoLines=[{"documentNo": "CM-1", "lineAmount": 200.0, "jobNo": "P1"}],
    )

    header = client.get_sales_cr_memo_headers()[0]
    assert (header.document_no, header.customer_id) == ("CM-1", "C1")
    line = client.get_sales_cr_memo_lines()[0]
    assert (line.document_no, line.line_amount, line.project_id) == ("CM-1", 200.0, "P1")


@pytest.mark.unit
def test_job_ledger_entries_send_usage_filter_and_map_cost():
    """The job-ledger read is scoped server-side to ``entryType eq 'Usage'``."""
    client, requests = _build_billing(
        jobLedgerEntries=[
            {
                # ``entryNo`` identifies the entry; ``no`` is the consumed
                # resource's code, which repeats across entries.
                "entryNo": 150,
                "no": "E0020",
                "jobNo": "P1",
                "customerNo": "C1",
                "entryType": "Usage",
                "totalCostLCY": 400.0,
                "type": "Resource",
                "postingDate": "2026-01-20",
            }
        ]
    )

    entries = client.get_job_ledger_entries()

    ledger_request = next(
        r for r in requests if r.url.path.endswith("/jobLedgerEntries")
    )
    assert ledger_request.url.params["$filter"] == "entryType eq 'Usage'"

    entry = entries[0]
    # BC sends entryNo as a JSON number; the DTO carries it as a string.
    assert entry.entry_no == "150"
    assert entry.project_id == "P1"
    assert entry.customer_id == "C1"
    assert entry.total_cost_lcy == 400.0
    assert entry.line_type == "Resource"
    assert entry.posting_date == date(2026, 1, 20)


@pytest.mark.unit
def test_job_ledger_entries_empty_result_logs_warning(caplog):
    """An empty usage result is logged (case-sensitive filter may miss rows)."""
    client, _ = _build_billing(jobLedgerEntries=[])

    with caplog.at_level(logging.WARNING):
        entries = client.get_job_ledger_entries()

    assert entries == []
    assert any(
        "jobLedgerEntries returned no rows" in r.getMessage()
        and r.levelno == logging.WARNING
        for r in caplog.records
    )


@pytest.mark.unit
def test_job_ledger_entries_with_rows_logs_no_warning(caplog):
    """A non-empty usage result does not log the empty-result warning."""
    client, _ = _build_billing(
        jobLedgerEntries=[{"entryNo": 150, "jobNo": "P1", "entryType": "Usage"}]
    )

    with caplog.at_level(logging.WARNING):
        client.get_job_ledger_entries()

    assert not any(
        "jobLedgerEntries returned no rows" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.unit
def test_time_sheet_and_resource_mapping():
    """Time-sheet entries and resources map their quantity/cost/price fields.

    ``timeSheetPostingEntries`` carries no ``jobNo``: the project number arrives
    in ``documentNo``. It exposes no resource field either, so ``resource_no``
    stays unset.
    """
    client, _ = _build_billing(
        timeSheetPostingEntries=[
            {
                "timeSheetNo": "TS-1",
                "documentNo": "P1",
                "quantity": 8.0,
                "postingDate": "2026-01-20",
            }
        ],
        resources=[{"no": "RES-01", "name": "Marc Solé", "unitCost": 25.0, "unitPrice": 60.0}],
    )

    ts = client.get_time_sheet_posting_entries()[0]
    assert (ts.time_sheet_no, ts.project_id, ts.resource_no, ts.quantity) == (
        "TS-1",
        "P1",
        "",
        8.0,
    )

    resource = client.get_resources()[0]
    assert (resource.id, resource.name, resource.unit_cost, resource.unit_price) == (
        "RES-01",
        "Marc Solé",
        25.0,
        60.0,
    )


# --------------------------------------------------------------------------- #
# Identity and assignments (resources / customersResources)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_resource_mapping_carries_email_and_permission():
    """Resources map ``email`` and ``manageAllCustomers`` alongside the cost fields."""
    client, _ = _build_billing(
        resources=[
            {
                "no": "E0017",
                "name": "AOURAGHE , Maanan",
                "email": "maanan@strategos.ad",
                "manageAllCustomers": True,
                "unitCost": 25.0,
                "unitPrice": 60.0,
            },
            # A blank email and a missing flag are the live tenant's common case.
            {"no": "E0029", "name": "SOLER JORBA, Mireia", "email": ""},
        ]
    )

    resources = client.get_resources()
    assert [(r.id, r.email, r.manage_all_customers) for r in resources] == [
        ("E0017", "maanan@strategos.ad", True),
        ("E0029", "", False),
    ]


@pytest.mark.unit
def test_customer_resources_mapping_ignores_odata_metadata():
    """Assignments map ``customerNo``/``resourceNo``; the etag is not mapped."""
    client, _ = _build_billing(
        customersResources=[
            {"@odata.etag": "W/\"abc\"", "resourceNo": "E0017", "customerNo": "C00030"},
            {"@odata.etag": "W/\"def\"", "resourceNo": "E0019", "customerNo": "C00040"},
        ]
    )

    assignments = client.get_customer_resources()
    assert all(isinstance(a, BCCustomerResource) for a in assignments)
    assert [(a.resource_id, a.customer_id) for a in assignments] == [
        ("E0017", "C00030"),
        ("E0019", "C00040"),
    ]


@pytest.mark.unit
def test_customer_resources_read_failure_degrades_to_empty(caplog):
    """A failing read logs and returns ``[]`` instead of raising.

    The caller then applies its own default rather than the whole screen 500-ing.
    """
    # No ``customersResources`` rows configured, so the mock transport answers 404.
    client, _ = _build_billing()

    with caplog.at_level(logging.WARNING):
        assert client.get_customer_resources() == []

    assert "customersResources" in caplog.text


def _clause_count(request, field: str) -> int:
    """How many ``field eq '...'`` clauses one request's $filter carries."""
    return (request.url.params.get("$filter") or "").count(f"{field} eq ")


@pytest.mark.unit
def test_customer_scope_is_pushed_into_the_odata_filter():
    """A scoped page asks BC for just those ids instead of filtering after the fact."""
    client, requests = _build_billing(customers=[], projects=[])

    client.get_customers_page(customer_ids=["C00030", "C00040"], page_size=10)
    assert _clause_count(requests[-1], "no") == 2

    client.get_projects_page(customer_ids=["C00030"], page_size=10)
    assert _clause_count(requests[-1], "billToCustomerNo") == 1


@pytest.mark.unit
def test_scoped_pages_batch_their_ids_and_never_build_one_giant_filter():
    """A scope larger than the filter budget is split, so BC cannot answer HTTP 414.

    This is the regression test for the unbatched page filters: one ``or``-joined
    clause per id built a URL Business Central rejects once a user had >50 customers.
    """
    ids = [f"C{i:05d}" for i in range(120)]
    entity_requests = lambda rs, name: [  # noqa: E731
        r for r in rs if r.url.path.endswith(f"/{name}")
    ]

    client, requests = _build_billing(customers=[], projects=[])
    client.get_customers_page(customer_ids=ids, page_size=10)
    reads = entity_requests(requests, "customers")
    assert len(reads) == 3  # ceil(120 / 50)
    assert all(_clause_count(r, "no") <= 50 for r in reads)

    client, requests = _build_billing(customers=[], projects=[])
    client.get_projects_page(customer_ids=ids, page_size=10)
    reads = entity_requests(requests, "projects")
    assert len(reads) == 3
    assert all(_clause_count(r, "billToCustomerNo") <= 50 for r in reads)

    client, requests = _build_billing(customers=[])
    client.get_customer_refs_page(page=1, page_size=10, customer_ids=ids)
    reads = entity_requests(requests, "customers")
    assert len(reads) == 3
    assert all(_clause_count(r, "no") <= 50 for r in reads)


@pytest.mark.unit
def test_scoped_pages_partition_their_rows_without_gaps_or_repeats():
    """Paging a scoped read in memory neither drops nor duplicates a row."""
    rows = [{"no": f"C{i:03d}", "name": f"Customer {i}"} for i in range(7)]
    ids = [r["no"] for r in rows]

    client, _ = _build_billing(customers=rows, projects=[])
    first = client.get_customers_page(customer_ids=ids, page_size=3)
    assert [c.id for c in first.items] == ["C000", "C001", "C002"]
    assert first.next_cursor is not None

    second = client.get_customers_page(
        customer_ids=ids, page_size=3, cursor=first.next_cursor
    )
    assert [c.id for c in second.items] == ["C003", "C004", "C005"]

    third = client.get_customers_page(
        customer_ids=ids, page_size=3, cursor=second.next_cursor
    )
    assert [c.id for c in third.items] == ["C006"]
    assert third.next_cursor is None


@pytest.mark.unit
def test_scoped_refs_page_totals_the_rows_found_not_the_ids_asked_for():
    """An id pointing at a deleted customer must not inflate the total."""
    client, _ = _build_billing(
        customers=[{"no": "C001", "name": "Beta"}, {"no": "C002", "name": "Alpha"}]
    )

    page = client.get_customer_refs_page(
        page=1, page_size=10, customer_ids=["C001", "C002", "C404"]
    )
    assert page.total_count == 2
    # Still name-ordered, which the billing table depends on.
    assert [r.name for r in page.items] == ["Alpha", "Beta"]


@pytest.mark.unit
def test_unscoped_page_asks_bc_for_one_window_not_the_whole_table():
    """A manager's page is a single ``$skip``/``$top`` window with no ``$filter``.

    Replaces an assertion that this path rode ``nextLink`` — it pinned the bug.
    """
    client, requests = _build_billing(customers=[])

    client.get_customers_page(page_size=25)
    params = requests[-1].url.params
    assert params.get("$top") == "26"
    assert params.get("$skip") == "0"
    assert params.get("$orderby") == "no"
    assert params.get("$filter") is None


@pytest.mark.unit
def test_empty_customer_scope_never_reaches_business_central():
    """An empty scope is an empty page, decided without an HTTP request."""
    client, requests = _build_billing()

    assert client.get_customers_page(customer_ids=[]).items == []
    assert client.get_projects_page(customer_ids=[]).items == []
    assert client.get_customers(customer_ids=[]) == []
    assert client.get_customer_refs_page(page=1, page_size=10, customer_ids=[]).items == []

    # Only the token request, if any — no entity read went out.
    assert [r for r in requests if r.url.host != _TOKEN_HOST] == []
