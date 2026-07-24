"""Business Central transport DTOs.

These Pydantic v2 models mirror the JSON returned by BC's REST endpoints. They
are deliberately kept separate from each domain's API ``schemas.py``: they are
transport objects for the integration layer, not the shapes Strategos exposes to
its own frontend.

Enum *members* are English for readability; their *values* preserve the exact
Catalan/Spanish vocabulary that Business Central uses so fixtures (and, later,
the live API payloads) validate without translation.
"""

from datetime import date
from enum import Enum

from pydantic import BaseModel


class CustomerStatus(str, Enum):
    """Whether a customer is currently active."""

    active = "Activo"
    inactive = "Inactivo"


class ProjectStatus(str, Enum):
    """Whether a project is currently active."""

    active = "Activo"
    inactive = "Inactivo"


class TaskStatus(str, Enum):
    """Board column a user task sits in."""

    pending = "Pendiente"
    in_progress = "En curso"
    done = "Hecho"


class TaskPriority(str, Enum):
    """User-task priority."""

    high = "Alta"
    medium = "Media"
    low = "Baja"


class ObligationStatus(str, Enum):
    """Due state of a project-obligation instance."""

    overdue = "Vencido"
    upcoming = "Próximo"
    pending = "Pendiente"


class Periodicity(str, Enum):
    """How often a catalog obligation recurs."""

    monthly = "mensual"
    quarterly = "trimestral"
    biannual = "semestral"
    annual = "anual"


class BCCustomer(BaseModel):
    """A customer of the advisory firm (BC ``GET /customers``).

    Mapped from BC's native ``customer`` entity by the live client. A few fields
    are approximations of the original curated concept, kept as free-form strings
    because the real ERP payload is coarser than first assumed:

    * ``customer_type`` comes from BC ``partnerType`` (only ``Company``/``Person``/
      blank), not the finer Societat/Persona física/Indivís/... categories.
    * ``responsible`` is the raw BC ``salespersonCode``, not a resolved person name
      (no code→name lookup table exists yet).
    """

    id: str
    name: str
    nif: str
    customer_type: str
    responsible: str
    active_project_count: int
    status: CustomerStatus


class BCCustomerPage(BaseModel):
    """One page of customers plus an opaque continuation token.

    ``next_cursor`` wraps BC's own ``@odata.nextLink`` for the query that
    produced this page (see ``LiveBusinessCentralClient.get_customers_page``);
    it is ``None`` once there is nothing left to page through.
    """

    items: list[BCCustomer]
    next_cursor: str | None = None


class BCProject(BaseModel):
    """A project delivered for a customer (BC ``GET /projects``).

    Mapped from BC's native ``project`` (Job) entity by the live client.
    ``responsible`` (``personResponsible``) and ``technician`` (``projectManager``)
    are real BC fields that happen to be empty in the current data — they are not
    unavailable.

    ``project_type``, ``entity_type``, ``has_certificate``, ``certificate_expiry``
    and ``filing_date`` do **not** exist anywhere in the BC schema, so the live
    client leaves them unset (``None``); they are optional here rather than guessed
    from ``description`` string patterns. Tracked as a pending BC-side field
    addition (email to Sergio, 2026-07-10). The mock client still populates them
    from fixtures, so the fixture-backed views are unaffected.
    """

    id: str
    name: str
    customer_id: str
    project_type: str | None = None
    entity_type: str | None = None
    responsible: str
    technician: str
    has_certificate: bool | None = None
    certificate_expiry: date | None = None
    filing_date: date | None = None
    status: ProjectStatus


class BCProjectPage(BaseModel):
    """One page of projects plus an opaque continuation token.

    ``next_cursor`` wraps BC's own ``@odata.nextLink`` for the query that
    produced this page (see ``LiveBusinessCentralClient.get_projects_page``);
    it is ``None`` once there is nothing left to page through.
    """

    items: list[BCProject]
    next_cursor: str | None = None


class BCUser(BaseModel):
    """An internal staff member (BC ``GET /users``).

    Mapped from BC's native ``user`` entity. There is deliberately no ``role``
    field: the users directory sources role from the local ``auth.User.role``
    column, never from BC (see ``app.domains.users.service``).
    """

    id: str
    name: str
    email: str


class BCUserTask(BaseModel):
    """A task assigned to a user on a project (BC ``GET /userTasks``)."""

    id: str
    title: str
    project_id: str
    assignee_id: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date


class BCObligation(BaseModel):
    """A catalog obligation type (BC ``GET /obligations``).

    Mapped from BC's native ``obligation`` entity by the live client. BC now
    exposes ``periodicity`` and ``dueDateRule`` (both BC ``DateFormula`` values,
    serialized as plain strings such as ``"1Y"`` or ``"5Y"``, not the enum's
    Spanish/Catalan words), so the live client populates them.

    ``periodicity`` is therefore a free-form ``str`` rather than the
    :class:`Periodicity` enum: the live ``DateFormula`` strings would not validate
    against the enum's ``mensual``/``trimestral``/... members. The mock client's
    fixture values (e.g. ``"mensual"``) remain valid plain strings under this
    looser type, so no fixture rewrite is required.
    """

    id: str
    code: str
    name: str
    periodicity: str | None = None
    due_date_rule: str | None = None


class BCProjectObligation(BaseModel):
    """An obligation instance for a project (BC ``GET /projectObligations``).

    ``subject`` is the *subjecte* SI/NO flag (whether the project is liable for
    this obligation). ``submission_date`` is null until the obligation is filed.
    The BC ``status`` field is the system-of-record label; Strategos re-derives
    its own due state from ``due_date``/``submission_date`` against a reference
    date in the obligations domain.

    BC's ``projectObligation`` entity now carries ``subject``, ``dueDate`` and
    ``submissionDate`` alongside the ``jobNo``/``obligationCode`` link, so the
    live client populates them. ``submission_date`` stays ``None`` until the
    obligation is filed, and any instance BC still returns without a ``dueDate``
    remains undated (``Sin fecha``) — both are handled by the obligations domain.
    ``status`` has no BC source and is left unset (Strategos derives its own).

    ``fecha_notificacion`` is the date on which the firm should be alerted about
    the obligation (drives the daily obligation-alert task). BC has **not** yet
    implemented this field upstream, so it is Optional with a ``None`` default:
    live payloads that omit it still validate (defensive), and the live client
    maps it through once BC exposes it.
    """

    id: str
    project_id: str
    obligation_id: str
    subject: bool | None = None
    due_date: date | None = None
    submission_date: date | None = None
    fecha_notificacion: date | None = None
    status: ObligationStatus | None = None


# -- Billing / Costs -----------------------------------------------------------
#
# Read-only transport DTOs for BC's sales and job-ledger entities, the source of
# truth for the firm's billing and costs. A sales document is a header plus its
# lines: a line links back to its header on ``document_no`` (BC ``documentNo`` ==
# header ``no``). Amounts are BC's own ``lineAmount``/``totalCostLCY`` in local
# currency (EUR) and are kept as plain floats — there is no ``Decimal`` in this
# codebase and BC serializes them as JSON numbers. ``line_type``/``number``/
# ``entry_type`` are free-form BC Option strings (like ``customer_type`` above),
# not enums.


class BCSalesInvoiceHeader(BaseModel):
    """A sales-invoice header (BC ``GET /salesInvoiceHeaders``).

    ``document_no`` (BC ``no``) is the invoice number a line references via its
    own ``documentNo``. ``customer_id`` is BC ``sellToCustomerNumber``.
    """

    document_no: str
    customer_id: str
    posting_date: date | None = None


class BCSalesInvoiceLine(BaseModel):
    """A sales-invoice line (BC ``GET /salesInvoiceLines``).

    ``document_no`` (BC ``documentNo``) ties the line to its
    :class:`BCSalesInvoiceHeader`. ``project_id`` is BC ``jobNo`` (blank for
    non-project lines). ``line_type``/``number`` are BC ``type``/``number``.
    """

    document_no: str
    line_amount: float = 0.0
    project_id: str | None = None
    line_type: str | None = None
    number: str | None = None


class BCSalesCrMemoHeader(BaseModel):
    """A sales credit-memo header (BC ``GET /salesCrMemoHeaders``).

    Same shape as :class:`BCSalesInvoiceHeader`; credit-memo amounts are
    subtracted from invoiced amounts to get net billing.
    """

    document_no: str
    customer_id: str
    posting_date: date | None = None


class BCSalesCrMemoLine(BaseModel):
    """A sales credit-memo line (BC ``GET /salesCrMemoLines``).

    ``document_no`` (BC ``documentNo``) ties the line to its
    :class:`BCSalesCrMemoHeader`; ``project_id`` is BC ``jobNo``.
    """

    document_no: str
    line_amount: float = 0.0
    project_id: str | None = None


class BCJobLedgerEntry(BaseModel):
    """A job-ledger entry (BC ``GET /jobLedgerEntries``).

    The live client fetches only ``entryType eq 'Usage'`` rows (the cost side of
    a project). ``entry_no`` is BC ``no``, ``project_id`` is ``jobNo``,
    ``customer_id`` is ``customerNo``, ``total_cost_lcy`` is the entry's cost in
    local currency, and ``line_type`` is BC ``type``.
    """

    entry_no: str
    project_id: str | None = None
    customer_id: str | None = None
    entry_type: str | None = None
    total_cost_lcy: float = 0.0
    line_type: str | None = None
    posting_date: date | None = None


class BCTimeSheetPostingEntry(BaseModel):
    """A time-sheet posting entry (BC ``GET /timeSheetPostingEntries``).

    Read-through only for now (hours are not yet aggregated). ``project_id`` is
    BC ``jobNo``, ``resource_no`` is the resource that logged ``quantity`` hours.
    """

    time_sheet_no: str
    project_id: str | None = None
    resource_no: str
    quantity: float = 0.0
    posting_date: date | None = None


class BCResource(BaseModel):
    """A billable resource (BC ``GET /resources``).

    Read-through only for now (used by a future margin/hours feature).
    ``id`` is BC ``no``.
    """

    id: str
    name: str
    unit_cost: float = 0.0
    unit_price: float = 0.0
