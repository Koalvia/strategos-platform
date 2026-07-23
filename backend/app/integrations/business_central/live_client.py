"""Live Business Central client.

:class:`LiveBusinessCentralClient` implements the
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
against BC's real REST API (Dynamics 365 Business Central, the Strategos custom
API published by Becentis — see ``docs/postman/``).

``customers``, ``projects``, ``users``, ``obligations`` and ``projectObligations``
are wired up: their payloads are BC's native entities, so this client does the
narrowing down to the transport DTOs. ``obligation`` now carries ``periodicity``
and ``dueDateRule`` and ``projectObligation`` now carries ``subject``, ``dueDate``
and ``submissionDate``, so those fields are mapped through. ``status`` has no BC
source (Strategos derives it), and an instance BC still returns without a
``dueDate`` remains undated (``Sin fecha``). ``userTasks`` is intentionally left
unimplemented (a pending userTasks decision) and raises ``NotImplementedError``.

The billing/costs entities (``salesInvoiceHeaders``/``salesInvoiceLines``,
``salesCrMemoHeaders``/``salesCrMemoLines``, ``jobLedgerEntries``,
``timeSheetPostingEntries``, ``resources``) are mapped here too. Their field
names follow the confirmed spec (see ``docs/postman/``), but — like the
``$filter``-based directory listings above — they have **not** been exercised
against the real BC tenant yet, so treat the amount fields and the
``entryType eq 'Usage'`` option value as pending live verification. The mock
client's fixtures are shaped to the same DTOs and unblock the rest of the stack.

Auth is OAuth2 client-credentials against Azure AD. The access token is cached in
memory and only re-requested once it is close to expiry, so a burst of reads
authenticates once. OData ``{"value": [...]}`` envelopes are unwrapped and
``@odata.nextLink`` is followed until exhausted (the firm has a few hundred
customers/projects, so a single page cannot be assumed).
"""

import base64
import time
from collections.abc import Callable
from datetime import date

import httpx

from app import logger
from app.integrations.business_central.client import (
    DEFAULT_CUSTOMERS_PAGE_SIZE,
    DEFAULT_PROJECTS_PAGE_SIZE,
    BusinessCentralClient,
)
from app.integrations.business_central.models import (
    BCCustomer,
    BCCustomerPage,
    BCJobLedgerEntry,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCProjectPage,
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
)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_SCOPE = "https://api.businesscentral.dynamics.com/.default"
_ROOT = "https://api.businesscentral.dynamics.com/v2.0"

# Refresh the token a little before it actually expires so an in-flight request
# never rides on a token that lapses mid-call.
_EXPIRY_SKEW_SECONDS = 60

# BC represents a blank Option member either as an empty string or as its XML
# escape ``_x0020_`` (a single space). Both mean "no value".
_BLANK_OPTIONS = {"", "_x0020_"}

_NOT_IMPLEMENTED_MSG = (
    "{method} is not implemented by the live Business Central client. "
    "userTasks is excluded from this integration "
    "(see the pending userTasks decision)."
)


def _clean_option(value: str | None) -> str:
    """Normalise a BC Option value, collapsing the blank sentinels to ``\"\"``."""
    text = (value or "").strip()
    return "" if text in _BLANK_OPTIONS else text


def _parse_date(value: str | None) -> date | None:
    """Parse a BC ISO date string to :class:`date`, ``None`` if absent/blank."""
    text = (value or "").strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _parse_float(value) -> float:
    """Coerce a BC monetary/quantity value to ``float``, ``0.0`` if absent/blank.

    BC serializes amounts as JSON numbers, but a missing or empty field defaults
    to ``0.0`` so aggregation never trips over a ``None``.
    """
    if value in (None, ""):
        return 0.0
    return float(value)


def _encode_cursor(next_link: str) -> str:
    """Wrap a BC ``@odata.nextLink`` as an opaque cursor.

    Callers (the frontend, in particular) never need BC's actual URL shape —
    base64-encoding it keeps the tenant/company/API-group details out of the
    network tab without pretending this is real encryption.
    """
    return base64.urlsafe_b64encode(next_link.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    """Reverse :func:`_encode_cursor` back to BC's absolute ``nextLink`` URL."""
    return base64.urlsafe_b64decode(cursor.encode()).decode()


def _escape_odata_literal(value: str) -> str:
    """Escape a value for interpolation into an OData string literal (``'..'``)."""
    return value.replace("'", "''")


class LiveBusinessCentralClient(BusinessCentralClient):
    """A :class:`BusinessCentralClient` backed by the real Business Central API."""

    def __init__(
        self,
        *,
        tenant_id: str,
        environment: str,
        company_id: str,
        client_id: str,
        client_secret: str,
        publisher: str,
        api_group: str,
        api_version: str,
        http_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tenant_id = tenant_id
        self._environment = environment
        self._company_id = company_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._publisher = publisher
        self._api_group = api_group
        self._api_version = api_version
        self._http = http_client or httpx.Client(timeout=30.0)
        self._clock = clock

        # In-memory token cache, shared across every request this instance serves.
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @classmethod
    def from_settings(cls, settings, **overrides) -> "LiveBusinessCentralClient":
        """Build a client from ``app.core.config.settings`` (BC_* fields)."""
        return cls(
            tenant_id=settings.BC_TENANT_ID,
            environment=settings.BC_ENVIRONMENT,
            company_id=settings.BC_COMPANY_ID,
            client_id=settings.BC_CLIENT_ID,
            client_secret=settings.BC_CLIENT_SECRET,
            publisher=settings.BC_PUBLISHER,
            api_group=settings.BC_API_GROUP,
            api_version=settings.BC_API_VERSION,
            **overrides,
        )

    @property
    def _base_url(self) -> str:
        """The company-scoped API root every entity read hangs off."""
        return (
            f"{_ROOT}/{self._tenant_id}/{self._environment}/api/"
            f"{self._publisher}/{self._api_group}/{self._api_version}/"
            f"companies({self._company_id})"
        )

    # -- OAuth2 -----------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid access token, requesting a new one only when needed."""
        if self._token is not None and self._clock() < self._token_expires_at:
            return self._token

        logger.info("Requesting a new Business Central access token")
        response = self._http.post(
            _TOKEN_URL.format(tenant_id=self._tenant_id),
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": _SCOPE,
            },
        )
        response.raise_for_status()
        payload = response.json()

        self._token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expires_at = self._clock() + expires_in - _EXPIRY_SKEW_SECONDS
        return self._token

    # -- OData reads ------------------------------------------------------------

    def _get_all(self, entity: str, filter_clause: str | None = None) -> list[dict]:
        """Read every row of ``entity``, following ``@odata.nextLink`` pages.

        ``filter_clause`` (an OData ``$filter`` expression) is only applied to
        the first request — once BC hands back a ``nextLink``, that URL
        already carries the full original query string, so re-applying params
        there would be redundant (and could conflict).
        """
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }
        rows: list[dict] = []
        url: str | None = f"{self._base_url}/{entity}"
        params: dict[str, str] | None = (
            {"$filter": filter_clause} if filter_clause else None
        )
        while url:
            response = self._http.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
            params = None
        return rows

    # -- Implemented entities ---------------------------------------------------

    def get_customers(self) -> list[BCCustomer]:
        """Return all customers, mapped from BC's native ``customer`` entity.

        Fetches every project company-wide to compute ``active_project_count``
        — appropriate here since every customer is being returned anyway. Used
        for full id -> name lookups elsewhere (``projects``/``obligations``
        services); the paginated, filtered directory listing is
        ``get_customers_page``.
        """
        active_projects_by_customer: dict[str, int] = {}
        for project in self.get_projects():
            if project.status is ProjectStatus.active:
                active_projects_by_customer[project.customer_id] = (
                    active_projects_by_customer.get(project.customer_id, 0) + 1
                )

        return [
            self._map_customer_row(row, active_projects_by_customer)
            for row in self._get_all("customers")
        ]

    def get_customers_page(
        self,
        *,
        search: str | None = None,
        status: CustomerStatus | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_CUSTOMERS_PAGE_SIZE,
    ) -> BCCustomerPage:
        """Return one page of customers, filtering server-side via OData ``$filter``.

        ``search``/``status`` are translated into a BC ``$filter`` expression
        (see ``_customers_filter``) so the filter covers every customer BC
        holds, not just whatever has already been paged in. This leans on the
        standard OData v4 query capabilities (``$filter``/``contains``) that
        BC's platform exposes for any API page — the same layer that already
        gives us ``@odata.nextLink`` pagination — but it hasn't been exercised
        against the real BC tenant yet, so treat it as pending live
        verification like the other BC specifics noted in this module's
        docstring.

        ``active_project_count`` is computed only for this page's customers
        (via a ``billToCustomerNo`` filter scoped to their ids), not a
        company-wide projects fetch, which is what keeps a page fast.
        """
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }

        if cursor:
            url = _decode_cursor(cursor)
            params = None
        else:
            url = f"{self._base_url}/customers"
            params = {"$top": str(page_size)}
            filter_clause = self._customers_filter(search, status)
            if filter_clause:
                params["$filter"] = filter_clause

        response = self._http.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("value", [])
        next_link = payload.get("@odata.nextLink")

        active_counts = self._active_project_counts_for(
            [row["no"] for row in rows]
        )
        customers = [self._map_customer_row(row, active_counts) for row in rows]

        return BCCustomerPage(
            items=customers,
            next_cursor=_encode_cursor(next_link) if next_link else None,
        )

    def _map_customer_row(
        self, row: dict, active_projects_by_customer: dict[str, int]
    ) -> BCCustomer:
        """Map one BC ``customer`` row to a :class:`BCCustomer`."""
        customer_id = row["no"]
        return BCCustomer(
            id=customer_id,
            name=row.get("name", ""),
            nif=row.get("vatRegistrationNo", ""),
            customer_type=_clean_option(row.get("partnerType")),
            responsible=row.get("salespersonCode", ""),
            active_project_count=active_projects_by_customer.get(customer_id, 0),
            status=self._map_customer_status(row.get("blocked")),
        )

    def _active_project_counts_for(self, customer_ids: list[str]) -> dict[str, int]:
        """Count active projects per customer, scoped to just ``customer_ids``."""
        if not customer_ids:
            return {}

        id_filter = " or ".join(
            f"billToCustomerNo eq '{_escape_odata_literal(cid)}'"
            for cid in customer_ids
        )
        counts: dict[str, int] = {}
        for row in self._get_all("projects", filter_clause=id_filter):
            if self._map_project_status(row.get("status")) is ProjectStatus.active:
                customer_id = row.get("billToCustomerNo", "")
                counts[customer_id] = counts.get(customer_id, 0) + 1
        return counts

    @staticmethod
    def _customers_filter(
        search: str | None, status: CustomerStatus | None
    ) -> str | None:
        """Build the OData ``$filter`` for the customers directory's search/status.

        ``status`` mirrors ``_clean_option``'s dual blank-Option sentinel
        (``""``/``_x0020_``) so "Activo" matches either representation BC may
        send back for an unblocked customer.
        """
        clauses: list[str] = []
        if search:
            needle = _escape_odata_literal(search)
            clauses.append(
                f"(contains(name,'{needle}') or contains(vatRegistrationNo,'{needle}'))"
            )
        if status is CustomerStatus.active:
            clauses.append("(blocked eq '' or blocked eq '_x0020_')")
        elif status is CustomerStatus.inactive:
            clauses.append("(blocked ne '' and blocked ne '_x0020_')")
        return " and ".join(clauses) if clauses else None

    def get_projects(self) -> list[BCProject]:
        """Return all projects, mapped from BC's native ``project`` (Job) entity.

        ``project_type``/``entity_type``/``has_certificate``/``certificate_expiry``/
        ``filing_date`` have no BC source and are left unset (see ``BCProject``).
        """
        return [self._map_project_row(row) for row in self._get_all("projects")]

    def get_projects_page(
        self,
        *,
        search: str | None = None,
        project_type: str | None = None,
        entity_type: str | None = None,
        status: ProjectStatus | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    ) -> BCProjectPage:
        """Return one page of projects, filtering server-side via OData ``$filter``.

        ``search``/``status`` are translated into a BC ``$filter`` expression
        (see ``_projects_filter``), the same "relies on standard OData v4
        query capabilities, pending live verification" caveat as
        ``get_customers_page`` applies here too.

        ``project_type``/``entity_type`` have no BC source field yet (see
        ``BCProject``) — every live row leaves them unset, so a page can never
        match a specific requested value (this mirrors ``get_customers``'s
        existing in-memory filtering, which already excludes every live row
        the same way). Rather than issue a request BC can't filter on and
        that would come back empty anyway, this short-circuits to an empty
        page whenever either is given.
        """
        if not cursor and (project_type or entity_type):
            return BCProjectPage(items=[], next_cursor=None)

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }

        if cursor:
            url = _decode_cursor(cursor)
            params = None
        else:
            url = f"{self._base_url}/projects"
            params = {"$top": str(page_size)}
            filter_clause = self._projects_filter(search, status)
            if filter_clause:
                params["$filter"] = filter_clause

        response = self._http.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("value", [])
        next_link = payload.get("@odata.nextLink")

        return BCProjectPage(
            items=[self._map_project_row(row) for row in rows],
            next_cursor=_encode_cursor(next_link) if next_link else None,
        )

    def _map_project_row(self, row: dict) -> BCProject:
        """Map one BC ``project`` (Job) row to a :class:`BCProject`."""
        return BCProject(
            id=row["no"],
            name=row.get("description", ""),
            customer_id=row.get("billToCustomerNo", ""),
            responsible=row.get("personResponsible", ""),
            technician=row.get("projectManager", ""),
            status=self._map_project_status(row.get("status")),
        )

    @staticmethod
    def _projects_filter(search: str | None, status: ProjectStatus | None) -> str | None:
        """Build the OData ``$filter`` for the projects directory's search/status.

        ``status`` mirrors ``_map_project_status``: only ``Completed`` (case-
        insensitively) means Inactivo, so "Activo" excludes just that value
        rather than matching a specific "Open" one.
        """
        clauses: list[str] = []
        if search:
            needle = _escape_odata_literal(search)
            clauses.append(f"contains(description,'{needle}')")
        if status is ProjectStatus.active:
            clauses.append("tolower(status) ne 'completed'")
        elif status is ProjectStatus.inactive:
            clauses.append("tolower(status) eq 'completed'")
        return " and ".join(clauses) if clauses else None

    def get_customer_names(self, customer_ids: list[str]) -> dict[str, str]:
        """Return ``{customer_id: name}`` for just ``customer_ids``.

        A direct, scoped ``/customers`` read — unlike ``get_customers()``,
        this never triggers the company-wide projects fetch used to compute
        ``active_project_count``, since callers here only want names.
        """
        if not customer_ids:
            return {}

        id_filter = " or ".join(
            f"no eq '{_escape_odata_literal(cid)}'" for cid in customer_ids
        )
        return {
            row["no"]: row.get("name", "")
            for row in self._get_all("customers", filter_clause=id_filter)
        }

    def get_users(self) -> list[BCUser]:
        """Return all internal users, mapped from BC's native ``user`` entity."""
        users: list[BCUser] = []
        for row in self._get_all("users"):
            email = (row.get("contactEmail") or "").strip()
            if not email:
                email = (row.get("authenticationEmail") or "").strip()
            users.append(
                BCUser(
                    id=row["userSecurityID"],
                    name=row.get("fullName", ""),
                    email=email,
                )
            )
        return users

    # -- Status mapping ---------------------------------------------------------

    @staticmethod
    def _map_customer_status(blocked: str | None) -> CustomerStatus:
        """Map BC ``blocked`` to Strategos status.

        A blank ``blocked`` Option (``""``/``_x0020_``) means the customer is not
        blocked → Activo; any other value → Inactivo.
        """
        if _clean_option(blocked) == "":
            return CustomerStatus.active
        return CustomerStatus.inactive

    @staticmethod
    def _map_project_status(status: str | None) -> ProjectStatus:
        """Map BC ``jobStatus`` (Planning/Quote/Open/Completed) to Strategos status.

        ``Completed`` → Inactivo. ``Open`` → Activo. ``Planning``/``Quote`` (and any
        unknown/blank value) are treated as Activo pending product confirmation.
        """
        if _clean_option(status).casefold() == "completed":
            return ProjectStatus.inactive
        return ProjectStatus.active

    def get_obligations(self) -> list[BCObligation]:
        """Return the obligation catalog, mapped from BC's ``obligation`` entity.

        ``periodicity`` and ``due_date_rule`` come from BC's ``periodicity`` and
        ``dueDateRule`` ``DateFormula`` fields (plain strings like ``"1Y"``) — see
        ``BCObligation``.
        """
        obligations: list[BCObligation] = []
        for row in self._get_all("obligations"):
            code = row["code"]
            obligations.append(
                BCObligation(
                    id=code,
                    code=code,
                    name=row.get("description", ""),
                    periodicity=row.get("periodicity"),
                    due_date_rule=row.get("dueDateRule"),
                )
            )
        return obligations

    def get_project_obligations(self) -> list[BCProjectObligation]:
        """Return project-obligation links from BC's ``projectObligation`` entity.

        ``subject``, ``due_date`` and ``submission_date`` come from BC's
        ``subject``/``dueDate``/``submissionDate`` fields — see
        ``BCProjectObligation``. ``status`` has no BC source (Strategos derives
        it); an instance BC returns without a ``dueDate`` stays undated ("sin
        fecha") in the obligations domain.
        """
        instances: list[BCProjectObligation] = []
        for row in self._get_all("projectObligations"):
            instances.append(
                BCProjectObligation(
                    id=row["systemId"],
                    project_id=row.get("jobNo", ""),
                    obligation_id=row.get("obligationCode", ""),
                    subject=row.get("subject"),
                    due_date=_parse_date(row.get("dueDate")),
                    submission_date=_parse_date(row.get("submissionDate")),
                    # BC has not implemented this field yet; ``get`` returns None
                    # until it does, so parsing never fails (see BCProjectObligation).
                    fecha_notificacion=_parse_date(row.get("notificationDate")),
                )
            )
        return instances

    # -- Billing / Costs --------------------------------------------------------

    def get_sales_invoice_headers(self) -> list[BCSalesInvoiceHeader]:
        """Return sales-invoice headers from BC's ``salesInvoiceHeaders`` entity."""
        return [
            BCSalesInvoiceHeader(
                document_no=row["no"],
                customer_id=row.get("sellToCustomerNumber", ""),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in self._get_all("salesInvoiceHeaders")
        ]

    def get_sales_invoice_lines(self) -> list[BCSalesInvoiceLine]:
        """Return sales-invoice lines from BC's ``salesInvoiceLines`` entity.

        ``project_id`` (BC ``jobNo``) is blank on non-project lines; those still
        count toward a customer's billing but not any project's.
        """
        return [
            BCSalesInvoiceLine(
                document_no=row.get("documentNo", ""),
                line_amount=_parse_float(row.get("lineAmount")),
                project_id=_clean_option(row.get("jobNo")) or None,
                line_type=row.get("type"),
                number=row.get("number"),
            )
            for row in self._get_all("salesInvoiceLines")
        ]

    def get_sales_cr_memo_headers(self) -> list[BCSalesCrMemoHeader]:
        """Return credit-memo headers from BC's ``salesCrMemoHeaders`` entity."""
        return [
            BCSalesCrMemoHeader(
                document_no=row["no"],
                customer_id=row.get("sellToCustomerNumber", ""),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in self._get_all("salesCrMemoHeaders")
        ]

    def get_sales_cr_memo_lines(self) -> list[BCSalesCrMemoLine]:
        """Return credit-memo lines from BC's ``salesCrMemoLines`` entity."""
        return [
            BCSalesCrMemoLine(
                document_no=row.get("documentNo", ""),
                line_amount=_parse_float(row.get("lineAmount")),
                project_id=_clean_option(row.get("jobNo")) or None,
            )
            for row in self._get_all("salesCrMemoLines")
        ]

    def get_job_ledger_entries(self) -> list[BCJobLedgerEntry]:
        """Return job-ledger *usage* entries from BC's ``jobLedgerEntries`` entity.

        Scoped server-side to ``entryType eq 'Usage'`` (the cost side of a
        project) so only cost rows come back.

        BC Option values are case-sensitive and the ``'Usage'`` literal is not
        yet verified against the live tenant. If the tenant spells it differently
        (e.g. ``usage``/``USAGE``) the filter matches nothing, project costs
        silently read as zero, and no error is raised — so an empty result is
        logged as a warning to make that case noticeable in production.
        """
        rows = self._get_all(
            "jobLedgerEntries", filter_clause="entryType eq 'Usage'"
        )
        if not rows:
            logger.warning(
                "jobLedgerEntries returned no rows for filter "
                "\"entryType eq 'Usage'\"; project costs will be zero. BC Option "
                "values are case-sensitive — if the live tenant spells the value "
                "differently, verify the filter literal."
            )
        return [
            BCJobLedgerEntry(
                entry_no=row["no"],
                project_id=_clean_option(row.get("jobNo")) or None,
                customer_id=_clean_option(row.get("customerNo")) or None,
                entry_type=row.get("entryType"),
                total_cost_lcy=_parse_float(row.get("totalCostLCY")),
                line_type=row.get("type"),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in rows
        ]

    def get_time_sheet_posting_entries(self) -> list[BCTimeSheetPostingEntry]:
        """Return time-sheet posting entries from BC's ``timeSheetPostingEntries``."""
        return [
            BCTimeSheetPostingEntry(
                time_sheet_no=row.get("timeSheetNo", ""),
                project_id=_clean_option(row.get("jobNo")) or None,
                resource_no=row.get("resourceNo", ""),
                quantity=_parse_float(row.get("quantity")),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in self._get_all("timeSheetPostingEntries")
        ]

    def get_resources(self) -> list[BCResource]:
        """Return billable resources from BC's ``resources`` entity."""
        return [
            BCResource(
                id=row["no"],
                name=row.get("name", ""),
                unit_cost=_parse_float(row.get("unitCost")),
                unit_price=_parse_float(row.get("unitPrice")),
            )
            for row in self._get_all("resources")
        ]

    # -- Deferred entities ------------------------------------------------------

    def get_user_tasks(self) -> list[BCUserTask]:
        raise NotImplementedError(
            _NOT_IMPLEMENTED_MSG.format(method="get_user_tasks")
        )
