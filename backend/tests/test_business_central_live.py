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
* that the still-deferred ``userTasks`` entity raises ``NotImplementedError``.
"""

from datetime import date

import httpx
import pytest

from app.domains.obligations.schemas import DerivedObligationStatus
from app.domains.obligations.service import derive_status
from app.integrations.business_central.live_client import LiveBusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomer,
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
    customers_next_link=None,
    projects_rows=None,
):
    """Build a live client + request recorder for ``get_customers_page`` tests.

    Unlike ``_build`` (which exercises the full-drain ``get_customers``/
    ``get_projects``), this records every request so tests can assert exactly
    what query BC was sent (``$top``/``$filter``) and which paths were hit.
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
            body = {"value": customers_rows}
            if customers_next_link is not None:
                body["@odata.nextLink"] = customers_next_link
            return httpx.Response(200, json=body)

        if path.endswith("/projects"):
            return httpx.Response(200, json={"value": projects_rows})

        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveBusinessCentralClient(
        **_CONFIG, http_client=http_client, clock=lambda: 0.0
    )
    return client, requests


@pytest.mark.unit
def test_customers_page_sends_top_and_combined_filter():
    """A fresh page request carries ``$top`` and a search+status ``$filter``."""
    rows = [{"no": "C1", "name": "Acme SL", "vatRegistrationNo": "A1", "blocked": ""}]
    client, requests = _build_customers_page(customers_rows=rows)

    client.get_customers_page(search="acme", status=CustomerStatus.active, page_size=5)

    customers_request = next(r for r in requests if r.url.path.endswith("/customers"))
    params = customers_request.url.params
    assert params["$top"] == "5"
    assert "contains(name,'acme')" in params["$filter"]
    assert "contains(vatRegistrationNo,'acme')" in params["$filter"]
    assert "blocked eq '' or blocked eq '_x0020_'" in params["$filter"]


@pytest.mark.unit
def test_customers_page_status_inactive_uses_negated_blank_clause():
    """``Inactivo`` negates both blank-Option sentinels, not just one."""
    client, requests = _build_customers_page(customers_rows=[])

    client.get_customers_page(status=CustomerStatus.inactive)

    customers_request = next(r for r in requests if r.url.path.endswith("/customers"))
    assert (
        "blocked ne '' and blocked ne '_x0020_'"
        in customers_request.url.params["$filter"]
    )


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


@pytest.mark.unit
def test_customers_page_cursor_reuses_next_link_exactly():
    """The cursor round-trips to exactly the recorded ``@odata.nextLink``, and
    a continuation request carries no fresh ``$top``/``$filter`` (already
    baked into that URL)."""
    next_link = (
        "https://api.businesscentral.dynamics.com/v2.0/test-tenant/RESTSTR/api/"
        "strategos/integrations/v1.0/companies(test-company)/customers"
        "?$top=5&$skiptoken=abc"
    )
    client, requests = _build_customers_page(
        customers_rows=[{"no": "C1", "name": "Acme", "blocked": ""}],
        customers_next_link=next_link,
    )

    page = client.get_customers_page(search="acme", page_size=5)
    assert page.next_cursor is not None

    requests.clear()
    client.get_customers_page(cursor=page.next_cursor)

    customers_request = next(r for r in requests if r.url.path.endswith("/customers"))
    assert str(customers_request.url) == next_link


def _build_projects_page(
    *,
    projects_rows=None,
    projects_next_link=None,
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
            body = {"value": projects_rows}
            if projects_next_link is not None:
                body["@odata.nextLink"] = projects_next_link
            return httpx.Response(200, json=body)

        if path.endswith("/customers"):
            return httpx.Response(200, json={"value": customers_rows})

        return httpx.Response(404, json={"error": f"unexpected path {path}"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveBusinessCentralClient(
        **_CONFIG, http_client=http_client, clock=lambda: 0.0
    )
    return client, requests


@pytest.mark.unit
def test_projects_page_sends_top_and_combined_filter():
    """A fresh page request carries ``$top`` and a search+status ``$filter``."""
    rows = [{"no": "P1", "description": "Fiscal advisory", "status": "Open"}]
    client, requests = _build_projects_page(projects_rows=rows)

    client.get_projects_page(search="fiscal", status=ProjectStatus.active, page_size=5)

    projects_request = next(r for r in requests if r.url.path.endswith("/projects"))
    params = projects_request.url.params
    assert params["$top"] == "5"
    assert "contains(description,'fiscal')" in params["$filter"]
    assert "tolower(status) ne 'completed'" in params["$filter"]


@pytest.mark.unit
def test_projects_page_status_inactive_matches_completed():
    """``Inactivo`` filters for exactly ``status`` == "completed" (any case)."""
    client, requests = _build_projects_page(projects_rows=[])

    client.get_projects_page(status=ProjectStatus.inactive)

    projects_request = next(r for r in requests if r.url.path.endswith("/projects"))
    assert "tolower(status) eq 'completed'" in projects_request.url.params["$filter"]


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
def test_projects_page_cursor_reuses_next_link_exactly():
    """The cursor round-trips to exactly the recorded ``@odata.nextLink``."""
    next_link = (
        "https://api.businesscentral.dynamics.com/v2.0/test-tenant/RESTSTR/api/"
        "strategos/integrations/v1.0/companies(test-company)/projects"
        "?$top=5&$skiptoken=abc"
    )
    client, requests = _build_projects_page(
        projects_rows=[{"no": "P1", "description": "x", "status": "Open"}],
        projects_next_link=next_link,
    )

    page = client.get_projects_page(search="x", page_size=5)
    assert page.next_cursor is not None

    requests.clear()
    client.get_projects_page(cursor=page.next_cursor)

    projects_request = next(r for r in requests if r.url.path.endswith("/projects"))
    assert str(projects_request.url) == next_link


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
    # Blank contactEmail falls back to authenticationEmail.
    assert result[1].email == "fallback@estrategos.ad"


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
def test_user_tasks_raise_not_implemented():
    """userTasks stays deferred and raises a clear NotImplementedError."""
    client, _ = _build()
    with pytest.raises(NotImplementedError, match="get_user_tasks"):
        client.get_user_tasks()


@pytest.mark.unit
def test_base_url_matches_documented_pattern():
    """The company-scoped base URL matches the confirmed BC pattern."""
    client, _ = _build()
    assert client._base_url == (
        "https://api.businesscentral.dynamics.com/v2.0/test-tenant/RESTSTR/api/"
        "strategos/integrations/v1.0/companies(test-company)"
    )
