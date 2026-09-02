"""Live Business Central client.

:class:`LiveBusinessCentralClient` implements the
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
against BC's real REST API (Dynamics 365 Business Central, the Strategos custom
API published by Becentis — see ``docs/postman/``).

``customers``, ``projects``, ``users``, ``resources``, ``customersResources``,
``obligations`` and ``projectObligations`` are wired up: their payloads are BC's
native entities, so this client narrows them down to the transport DTOs.
``obligation`` now carries ``periodicity``
and ``dueDateRule`` and ``projectObligation`` now carries ``subject``, ``dueDate``
and ``submissionDate``, so those fields are mapped through. ``status`` has no BC
source (Strategos derives it), and an instance BC still returns without a
``dueDate`` remains undated (``Sin fecha``). ``userTasks`` is intentionally left
unimplemented (a pending userTasks decision): ``get_user_tasks`` logs a warning
and returns ``[]`` rather than raising, so tasks/users/dashboard features that
depend on it degrade to an empty state instead of failing outright.

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
authenticates once. OData ``{"value": [...]}`` envelopes are unwrapped; this tenant
never sends an ``@odata.nextLink``, so listings page by ``$skip`` (``_offset_page``).
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
    BCCustomerRef,
    BCCustomerRefPage,
    BCCustomerResource,
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

# How many ids go into one ``or``-joined ``$filter`` before it is split across
# requests. Each clause costs ~25 URL-encoded characters, so an unbounded list
# builds a URL Business Central rejects with **HTTP 414 Request-Uri Too Long**
# (a real tenant has hundreds of customers, where the mock fixtures had ~15 and
# never reached the limit). 50 keeps the query string comfortably short.
_MAX_FILTER_IDS = 50

_NOT_IMPLEMENTED_WARNING = (
    "get_user_tasks is not implemented by the live Business Central client "
    "(userTasks is excluded pending a decision on its BC source) — returning "
    "an empty list."
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


# Every listing pages by offset: this tenant never sends an @odata.nextLink, and a
# batched scoped read could not ride one anyway. Base64 only keeps it opaque.
_OFFSET_PREFIX = "offset:"


def _encode_offset(offset: int) -> str:
    """Wrap a page offset as an opaque cursor."""
    return base64.urlsafe_b64encode(f"{_OFFSET_PREFIX}{offset}".encode()).decode()


def _decode_offset(cursor: str | None) -> int:
    """Read an offset cursor, treating anything unexpected as the first page."""
    if not cursor:
        return 0
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception:
        return 0
    if not text.startswith(_OFFSET_PREFIX):
        return 0
    try:
        return max(int(text[len(_OFFSET_PREFIX) :]), 0)
    except ValueError:
        return 0


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

    def _get_all_by_ids(
        self,
        entity: str,
        field: str,
        ids: list[str],
        extra_filter: str | None = None,
    ) -> list[dict]:
        """Read every ``entity`` row whose ``field`` matches one of ``ids``."""
        unique_ids = list(dict.fromkeys(ids))
        rows: list[dict] = []
        for start in range(0, len(unique_ids), _MAX_FILTER_IDS):
            batch = unique_ids[start : start + _MAX_FILTER_IDS]
            id_filter = " or ".join(
                f"{field} eq '{_escape_odata_literal(value)}'" for value in batch
            )
            if extra_filter:
                id_filter = f"({id_filter}) and {extra_filter}"
            rows.extend(self._get_all(entity, filter_clause=id_filter))
        return rows

    def _rows_scoped_by_ids(
        self,
        entity: str,
        field: str,
        ids: list[str] | None,
        extra_filter: str | None = None,
    ) -> list[dict]:
        """Read ``entity`` either whole or scoped to ``ids``."""
        if ids is None:
            return self._get_all(entity, filter_clause=extra_filter)
        if not ids:
            return []
        return self._get_all_by_ids(entity, field, ids, extra_filter=extra_filter)

    def _offset_page(
        self,
        entity: str,
        *,
        offset: int,
        page_size: int,
        extra_filter: str | None = None,
    ) -> tuple[list[dict], bool]:
        """Read one ``$skip``/``$top`` page of ``entity``, plus whether more rows follow.

        ``$orderby`` is required: OData leaves a ``$skip`` window's order undefined, and
        an unstable one repeats or drops rows. One row past the page is the "more" probe.
        """
        params = {
            "$orderby": "no",
            "$skip": str(max(offset, 0)),
            "$top": str(page_size + 1),
        }
        if extra_filter:
            params["$filter"] = extra_filter

        response = self._http.get(
            f"{self._base_url}/{entity}",
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Accept": "application/json",
            },
            params=params,
        )
        response.raise_for_status()
        rows = response.json().get("value", [])
        return rows[:page_size], len(rows) > page_size

    # -- Implemented entities ---------------------------------------------------

    def get_customers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCCustomer]:
        """Return all customers, mapped from BC's native ``customer`` entity.

        ``customer_ids`` scopes both reads — the customers and the projects behind
        ``active_project_count`` — so a scoped call never sweeps the whole company.
        """
        if customer_ids is not None and not customer_ids:
            return []

        active_projects_by_customer: dict[str, int] = {}
        for project in self.get_projects(customer_ids=customer_ids):
            if project.status is ProjectStatus.active:
                active_projects_by_customer[project.customer_id] = (
                    active_projects_by_customer.get(project.customer_id, 0) + 1
                )

        return [
            self._map_customer_row(row, active_projects_by_customer)
            for row in self._rows_scoped_by_ids("customers", "no", customer_ids)
        ]

    def get_customers_page(
        self,
        *,
        search: str | None = None,
        status: CustomerStatus | None = None,
        customer_ids: list[str] | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_CUSTOMERS_PAGE_SIZE,
    ) -> BCCustomerPage:
        """Return one page of customers.

        An unfiltered, unscoped page is one ``$skip`` window. Anything else has to be
        materialized first, because BC rejects those filters — see ``_customer_matches``.
        """
        if customer_ids is not None and not customer_ids:
            return BCCustomerPage(items=[], next_cursor=None)
        if customer_ids or search or status is not None:
            return self._materialized_customers_page(
                search, status, customer_ids, cursor, page_size
            )

        offset = _decode_offset(cursor)
        rows, has_more = self._offset_page(
            "customers", offset=offset, page_size=page_size
        )

        active_counts = self._active_project_counts_for(
            [row["no"] for row in rows]
        )
        customers = [self._map_customer_row(row, active_counts) for row in rows]

        return BCCustomerPage(
            items=customers,
            next_cursor=_encode_offset(offset + page_size) if has_more else None,
        )

    def _materialized_customers_page(
        self,
        search: str | None,
        status: CustomerStatus | None,
        customer_ids: list[str] | None,
        cursor: str | None,
        page_size: int,
    ) -> BCCustomerPage:
        """Read the rows this caller may see, filter them here, then slice one page.

        ``customer_ids`` is read in batches (one clause per id would risk HTTP 414);
        ``None`` reads the table. Sorted by ``no``, matching the ``$orderby`` above.
        """
        rows = sorted(
            (
                row
                for row in self._rows_scoped_by_ids("customers", "no", customer_ids)
                if self._customer_matches(row, search, status)
            ),
            key=lambda row: row.get("no", ""),
        )
        offset = _decode_offset(cursor)
        page_rows = rows[offset : offset + page_size]

        active_counts = self._active_project_counts_for([r["no"] for r in page_rows])
        return BCCustomerPage(
            items=[self._map_customer_row(r, active_counts) for r in page_rows],
            next_cursor=(
                _encode_offset(offset + page_size)
                if offset + page_size < len(rows)
                else None
            ),
        )

    def get_customer_refs_page(
        self, *, page: int, page_size: int, customer_ids: list[str] | None = None
    ) -> BCCustomerRefPage:
        """Return one name-ordered page of customer ids/names, plus the total.

        A ``customer_ids`` scope is read in batches and sliced in memory, so the total is
        the rows actually found rather than the number of ids asked for.
        """
        if customer_ids is not None and not customer_ids:
            return BCCustomerRefPage(items=[], total_count=0)

        if customer_ids:
            rows = self._rows_scoped_by_ids("customers", "no", customer_ids)
            ordered = sorted(rows, key=lambda r: r.get("name", ""))
            start = max(page - 1, 0) * page_size
            window = ordered[start : start + page_size]
            return BCCustomerRefPage(
                items=[
                    BCCustomerRef(id=r["no"], name=r.get("name", "")) for r in window
                ],
                total_count=len(ordered),
            )

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }
        response = self._http.get(
            f"{self._base_url}/customers",
            headers=headers,
            params={
                "$select": "no,name",
                "$orderby": "name",
                "$top": str(page_size),
                "$skip": str(max(page - 1, 0) * page_size),
            },
        )
        response.raise_for_status()
        rows = response.json().get("value", [])

        return BCCustomerRefPage(
            items=[
                BCCustomerRef(id=row["no"], name=row.get("name", "")) for row in rows
            ],
            total_count=self._customer_count(),
        )

    def _customer_count(self) -> int:
        """Return how many customers BC holds, via its ``$count`` endpoint.

        BC prefixes the plain-text body with a UTF-8 BOM (``789`` arrives as
        ``"﻿789"``). ``str.strip()`` does **not** remove it — U+FEFF is not
        whitespace to Python — so the bytes are decoded with ``utf-8-sig``, which
        consumes the BOM, instead of trusting ``response.text``.
        """
        response = self._http.get(
            f"{self._base_url}/customers/$count",
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Accept": "text/plain",
            },
        )
        response.raise_for_status()
        return int(response.content.decode("utf-8-sig").strip())

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

        counts: dict[str, int] = {}
        for row in self._get_all_by_ids("projects", "billToCustomerNo", customer_ids):
            if self._map_project_status(row.get("status")) is ProjectStatus.active:
                customer_id = row.get("billToCustomerNo", "")
                counts[customer_id] = counts.get(customer_id, 0) + 1
        return counts

    def _customer_matches(
        self, row: dict, search: str | None, status: CustomerStatus | None
    ) -> bool:
        """Apply the directory's search/status to one raw row, in memory.

        BC cannot do either: it answers 501 to an ``or`` of ``contains`` across two
        fields and 400 to a ``blocked`` comparison. Matching here is also
        case-insensitive, which ``contains`` is not.
        """
        if search:
            needle = search.casefold()
            haystacks = (row.get("name", ""), row.get("vatRegistrationNo", ""))
            if not any(needle in (value or "").casefold() for value in haystacks):
                return False
        return status is None or self._map_customer_status(row.get("blocked")) is status

    def get_projects(self, *, customer_ids: list[str] | None = None) -> list[BCProject]:
        """Return all projects, mapped from BC's native ``project`` (Job) entity.

        ``project_type``/``entity_type``/``has_certificate``/``certificate_expiry``/
        ``filing_date`` have no BC source and are left unset (see ``BCProject``).

        ``customer_ids`` is pushed down as a ``billToCustomerNo`` filter — the
        same field ``_active_project_counts_for`` scopes on.
        """
        return [
            self._map_project_row(row)
            for row in self._rows_scoped_by_ids(
                "projects", "billToCustomerNo", customer_ids
            )
        ]

    def get_projects_page(
        self,
        *,
        search: str | None = None,
        project_type: str | None = None,
        entity_type: str | None = None,
        status: ProjectStatus | None = None,
        customer_id: str | None = None,
        customer_ids: list[str] | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PROJECTS_PAGE_SIZE,
    ) -> BCProjectPage:
        """Return one page of projects.

        ``project_type``/``entity_type`` have no BC source field, so asking for either
        short-circuits to an empty page, continuations included.
        """
        if project_type or entity_type:
            return BCProjectPage(items=[], next_cursor=None)
        if customer_ids is not None and not customer_ids:
            return BCProjectPage(items=[], next_cursor=None)
        if customer_ids or customer_id or search or status is not None:
            return self._materialized_projects_page(
                search, status, customer_id, customer_ids, cursor, page_size
            )

        offset = _decode_offset(cursor)
        rows, has_more = self._offset_page(
            "projects", offset=offset, page_size=page_size
        )

        return BCProjectPage(
            items=[self._map_project_row(row) for row in rows],
            next_cursor=_encode_offset(offset + page_size) if has_more else None,
        )

    def _materialized_projects_page(
        self,
        search: str | None,
        status: ProjectStatus | None,
        customer_id: str | None,
        customer_ids: list[str] | None,
        cursor: str | None,
        page_size: int,
    ) -> BCProjectPage:
        """Read the projects this caller may see, filter them here, then slice one page.

        A ``customer_id`` narrows the read to that customer — ``billToCustomerNo eq`` is
        the one filter BC does honour — and can never widen the caller's scope.
        """
        wanted = customer_ids
        if customer_id is not None:
            if customer_ids is not None and customer_id not in customer_ids:
                return BCProjectPage(items=[], next_cursor=None)
            wanted = [customer_id]

        rows = sorted(
            (
                row
                for row in self._rows_scoped_by_ids(
                    "projects", "billToCustomerNo", wanted
                )
                if self._project_matches(row, search, status)
            ),
            key=lambda row: row.get("no", ""),
        )
        offset = _decode_offset(cursor)
        page_rows = rows[offset : offset + page_size]

        return BCProjectPage(
            items=[self._map_project_row(r) for r in page_rows],
            next_cursor=(
                _encode_offset(offset + page_size)
                if offset + page_size < len(rows)
                else None
            ),
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

    def _project_matches(
        self, row: dict, search: str | None, status: ProjectStatus | None
    ) -> bool:
        """Apply the directory's search/status to one raw row, in memory.

        BC answers 400 to a ``tolower(status)`` comparison, and its ``contains`` is
        case-sensitive. ``status`` follows ``_map_project_status``: only Completed is
        Inactivo.
        """
        if search and search.casefold() not in (row.get("description") or "").casefold():
            return False
        return status is None or self._map_project_status(row.get("status")) is status

    def get_customer_names(self, customer_ids: list[str]) -> dict[str, str]:
        """Return ``{customer_id: name}`` for just ``customer_ids``.

        A direct, scoped ``/customers`` read — unlike ``get_customers()``,
        this never triggers the company-wide projects fetch used to compute
        ``active_project_count``, since callers here only want names.

        Large id lists are batched (see ``_get_all_by_ids``); a real tenant's
        billing table can reference hundreds of customers at once, which as a
        single ``$filter`` exceeded Business Central's URL limit.
        """
        if not customer_ids:
            return {}

        return {
            row["no"]: row.get("name", "")
            for row in self._get_all_by_ids("customers", "no", customer_ids)
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
                    user_name=(row.get("userName") or "").strip(),
                )
            )
        return users

    def get_customer_resources(self) -> list[BCCustomerResource]:
        """Return the customer/resource assignments, from BC ``customersResources``.

        Degraded to ``[]`` on failure so callers apply their own default.
        """
        try:
            rows = self._get_all("customersResources")
        except httpx.HTTPError:
            logger.warning(
                "Business Central customersResources read failed", exc_info=True
            )
            return []

        return [
            BCCustomerResource(
                customer_id=(row.get("customerNo") or "").strip(),
                resource_id=(row.get("resourceNo") or "").strip(),
            )
            for row in rows
        ]

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

    def get_sales_invoice_headers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCSalesInvoiceHeader]:
        """Return sales-invoice headers from BC's ``salesInvoiceHeaders`` entity.

        The customer comes from ``billToCustomerNo`` — the same field
        ``_map_project_row`` uses to attribute a project to its customer, so the
        dashboard's per-customer table reconciles its invoice totals against its
        nested project rows instead of splitting a customer whose bill-to and
        sell-to differ. (``sellToCustomerNo`` is also available should billing
        ever need the sold-to party instead.)

        ``customer_ids`` is therefore pushed down on ``billToCustomerNo`` too, so
        a scoped read attributes lines exactly as an unscoped one would.
        """
        return [
            BCSalesInvoiceHeader(
                document_no=row["no"],
                customer_id=row.get("billToCustomerNo", ""),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in self._rows_scoped_by_ids(
                "salesInvoiceHeaders", "billToCustomerNo", customer_ids
            )
        ]

    def get_sales_invoice_lines(
        self, *, document_nos: list[str] | None = None
    ) -> list[BCSalesInvoiceLine]:
        """Return sales-invoice lines from BC's ``salesInvoiceLines`` entity.

        ``project_id`` (BC ``jobNo``) is blank on non-project lines; those still
        count toward a customer's billing but not any project's.

        ``document_nos`` is pushed down on ``documentNo``, the field that links a
        line to its header.
        """
        return [
            BCSalesInvoiceLine(
                document_no=row.get("documentNo", ""),
                line_amount=_parse_float(row.get("lineAmount")),
                project_id=_clean_option(row.get("jobNo")) or None,
                line_type=row.get("type"),
                number=row.get("number"),
            )
            for row in self._rows_scoped_by_ids(
                "salesInvoiceLines", "documentNo", document_nos
            )
        ]

    def get_sales_cr_memo_headers(
        self, *, customer_ids: list[str] | None = None
    ) -> list[BCSalesCrMemoHeader]:
        """Return credit-memo headers from BC's ``salesCrMemoHeaders`` entity."""
        return [
            BCSalesCrMemoHeader(
                document_no=row["no"],
                customer_id=row.get("billToCustomerNo", ""),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in self._rows_scoped_by_ids(
                "salesCrMemoHeaders", "billToCustomerNo", customer_ids
            )
        ]

    def get_sales_cr_memo_lines(
        self, *, document_nos: list[str] | None = None
    ) -> list[BCSalesCrMemoLine]:
        """Return credit-memo lines from BC's ``salesCrMemoLines`` entity."""
        return [
            BCSalesCrMemoLine(
                document_no=row.get("documentNo", ""),
                line_amount=_parse_float(row.get("lineAmount")),
                project_id=_clean_option(row.get("jobNo")) or None,
            )
            for row in self._rows_scoped_by_ids(
                "salesCrMemoLines", "documentNo", document_nos
            )
        ]

    def get_job_ledger_entries(
        self, *, project_ids: list[str] | None = None
    ) -> list[BCJobLedgerEntry]:
        """Return job-ledger *usage* entries from BC's ``jobLedgerEntries`` entity.

        Scoped server-side to ``entryType eq 'Usage'`` (the cost side of a
        project) so only cost rows come back.

        ``project_ids`` narrows it further to those projects' entries, ``and``-ed
        onto the usage filter rather than replacing it.

        BC Option values are case-sensitive and the ``'Usage'`` literal is not
        yet verified against the live tenant. If the tenant spells it differently
        (e.g. ``usage``/``USAGE``) the filter matches nothing, project costs
        silently read as zero, and no error is raised — so an empty result is
        logged as a warning to make that case noticeable in production. Only the
        unscoped read warns: a specific set of projects legitimately having no
        usage cost is ordinary, and warning on it would bury the real signal.
        """
        rows = self._rows_scoped_by_ids(
            "jobLedgerEntries",
            "jobNo",
            project_ids,
            extra_filter="entryType eq 'Usage'",
        )
        if not rows and project_ids is None:
            logger.warning(
                "jobLedgerEntries returned no rows for filter "
                "\"entryType eq 'Usage'\"; project costs will be zero. BC Option "
                "values are case-sensitive — if the live tenant spells the value "
                "differently, verify the filter literal."
            )
        return [
            BCJobLedgerEntry(
                # ``entryNo`` (an int), not ``no``: on this entity ``no`` is the
                # resource/item code of the line (e.g. ``"E0020"``), which repeats
                # across every entry that consumed the same resource. ``entryNo``
                # is the entry's own key, which is what ``entry_no`` promises.
                entry_no=str(row["entryNo"]),
                project_id=_clean_option(row.get("jobNo")) or None,
                customer_id=_clean_option(row.get("customerNo")) or None,
                entry_type=row.get("entryType"),
                total_cost_lcy=_parse_float(row.get("totalCostLCY")),
                line_type=row.get("type"),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in rows
        ]

    def get_time_sheet_posting_entries(
        self, *, project_ids: list[str] | None = None
    ) -> list[BCTimeSheetPostingEntry]:
        """Return time-sheet posting entries from BC's ``timeSheetPostingEntries``.

        Unlike the other project-scoped entities, this one carries **no
        ``jobNo``**: the project is referenced by ``documentNo`` (which holds the
        job number, e.g. ``P00011``). It also exposes no resource field at all,
        so ``resource_no`` is left unset — the entity's fields are ``entryNo``,
        ``timeSheetNo``, ``timeSheetLineNo``, ``timeSheetDate``, ``quantity``,
        ``documentNo``, ``postingDate`` and ``description``.

        ``project_ids`` is therefore pushed down on ``documentNo``, not ``jobNo``.
        """
        return [
            BCTimeSheetPostingEntry(
                time_sheet_no=row.get("timeSheetNo", ""),
                project_id=_clean_option(row.get("documentNo")) or None,
                quantity=_parse_float(row.get("quantity")),
                posting_date=_parse_date(row.get("postingDate")),
            )
            for row in self._rows_scoped_by_ids(
                "timeSheetPostingEntries", "documentNo", project_ids
            )
        ]

    def get_resources(self) -> list[BCResource]:
        """Return resource cards from BC's ``resources`` entity."""
        return [
            BCResource(
                id=row["no"],
                name=row.get("name", ""),
                email=(row.get("email") or "").strip(),
                manage_all_customers=bool(row.get("manageAllCustomers", False)),
                unit_cost=_parse_float(row.get("unitCost")),
                unit_price=_parse_float(row.get("unitPrice")),
            )
            for row in self._get_all("resources")
        ]

    # -- Deferred entities ------------------------------------------------------

    def get_user_tasks(self) -> list[BCUserTask]:
        """Return ``[]``: userTasks is excluded pending a decision on its BC source.

        Callers (tasks, users directory, dashboard KPIs) all treat "no tasks"
        as a valid, empty state, so this degrades gracefully instead of
        raising and taking down every feature that touches tasks.
        """
        logger.warning(_NOT_IMPLEMENTED_WARNING)
        return []
