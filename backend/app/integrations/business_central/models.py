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
    """A catalog obligation type (BC ``GET /obligations``)."""

    id: str
    code: str
    name: str
    periodicity: Periodicity
    due_date_rule: str


class BCProjectObligation(BaseModel):
    """An obligation instance for a project (BC ``GET /projectObligations``).

    ``subject`` is the *subjecte* SI/NO flag (whether the project is liable for
    this obligation). ``submission_date`` is null until the obligation is filed.
    The BC ``status`` field is the system-of-record label; Strategos re-derives
    its own due state from ``due_date``/``submission_date`` against a reference
    date in the obligations domain.
    """

    id: str
    project_id: str
    obligation_id: str
    subject: bool
    due_date: date
    submission_date: date | None = None
    status: ObligationStatus
