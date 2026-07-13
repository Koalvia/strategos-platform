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

Auth is OAuth2 client-credentials against Azure AD. The access token is cached in
memory and only re-requested once it is close to expiry, so a burst of reads
authenticates once. OData ``{"value": [...]}`` envelopes are unwrapped and
``@odata.nextLink`` is followed until exhausted (the firm has a few hundred
customers/projects, so a single page cannot be assumed).
"""

import time
from collections.abc import Callable
from datetime import date

import httpx

from app import logger
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomer,
    BCObligation,
    BCProject,
    BCProjectObligation,
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

    def _get_all(self, entity: str) -> list[dict]:
        """Read every row of ``entity``, following ``@odata.nextLink`` pages."""
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }
        rows: list[dict] = []
        url: str | None = f"{self._base_url}/{entity}"
        while url:
            response = self._http.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
        return rows

    # -- Implemented entities ---------------------------------------------------

    def get_customers(self) -> list[BCCustomer]:
        """Return all customers, mapped from BC's native ``customer`` entity."""
        active_projects_by_customer: dict[str, int] = {}
        for project in self.get_projects():
            if project.status is ProjectStatus.active:
                active_projects_by_customer[project.customer_id] = (
                    active_projects_by_customer.get(project.customer_id, 0) + 1
                )

        customers: list[BCCustomer] = []
        for row in self._get_all("customers"):
            customer_id = row["no"]
            customers.append(
                BCCustomer(
                    id=customer_id,
                    name=row.get("name", ""),
                    nif=row.get("vatRegistrationNo", ""),
                    customer_type=_clean_option(row.get("partnerType")),
                    responsible=row.get("salespersonCode", ""),
                    active_project_count=active_projects_by_customer.get(
                        customer_id, 0
                    ),
                    status=self._map_customer_status(row.get("blocked")),
                )
            )
        return customers

    def get_projects(self) -> list[BCProject]:
        """Return all projects, mapped from BC's native ``project`` (Job) entity.

        ``project_type``/``entity_type``/``has_certificate``/``certificate_expiry``/
        ``filing_date`` have no BC source and are left unset (see ``BCProject``).
        """
        projects: list[BCProject] = []
        for row in self._get_all("projects"):
            projects.append(
                BCProject(
                    id=row["no"],
                    name=row.get("description", ""),
                    customer_id=row.get("billToCustomerNo", ""),
                    responsible=row.get("personResponsible", ""),
                    technician=row.get("projectManager", ""),
                    status=self._map_project_status(row.get("status")),
                )
            )
        return projects

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
                )
            )
        return instances

    # -- Deferred entities ------------------------------------------------------

    def get_user_tasks(self) -> list[BCUserTask]:
        raise NotImplementedError(
            _NOT_IMPLEMENTED_MSG.format(method="get_user_tasks")
        )
