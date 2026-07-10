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
* the raw obligations / projectObligations mapping (only the fields BC actually
  exposes today, the rest left unset);
* that the still-deferred ``userTasks`` entity raises ``NotImplementedError``.
"""

import httpx
import pytest

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
def test_obligation_catalog_mapping_leaves_missing_fields_unset():
    """Obligations map ``code``/``description``; BC has no periodicity/rule yet."""
    obligations = [
        {"code": "IRPF", "description": "Impost sobre la renda"},
        {"code": "IGI"},  # description absent -> empty name, still valid
    ]
    client, _ = _build(obligations=obligations)

    result = client.get_obligations()
    assert all(isinstance(o, BCObligation) for o in result)

    irpf = result[0]
    assert irpf.id == "IRPF"
    assert irpf.code == "IRPF"
    assert irpf.name == "Impost sobre la renda"
    # Not provided by BC today -> left unset.
    assert irpf.periodicity is None
    assert irpf.due_date_rule is None

    assert result[1].name == ""


@pytest.mark.unit
def test_project_obligation_link_mapping_leaves_missing_fields_unset():
    """Project-obligation links map only ``systemId``/``jobNo``/``obligationCode``."""
    project_obligations = [
        {
            "systemId": "aaaaaaaa-1111-2222-3333-444444444444",
            "jobNo": "P00011",
            "obligationCode": "IRPF",
        }
    ]
    client, _ = _build(project_obligations=project_obligations)

    result = client.get_project_obligations()
    assert all(isinstance(i, BCProjectObligation) for i in result)

    instance = result[0]
    assert instance.id == "aaaaaaaa-1111-2222-3333-444444444444"
    assert instance.project_id == "P00011"
    assert instance.obligation_id == "IRPF"
    # BC's real projectObligation carries none of these today -> left unset.
    assert instance.subject is None
    assert instance.due_date is None
    assert instance.submission_date is None
    assert instance.status is None


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
