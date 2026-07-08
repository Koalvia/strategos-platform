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
    """A customer of the advisory firm (BC ``GET /customers``)."""

    id: str
    name: str
    nif: str
    customer_type: str
    responsible: str
    active_project_count: int
    status: CustomerStatus


class BCProject(BaseModel):
    """A project delivered for a customer (BC ``GET /projects``)."""

    id: str
    name: str
    customer_id: str
    project_type: str
    entity_type: str
    responsible: str
    technician: str
    status: ProjectStatus


class BCUser(BaseModel):
    """An internal staff member (BC ``GET /users``)."""

    id: str
    name: str
    role: str
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
    name: str
    periodicity: Periodicity


class BCProjectObligation(BaseModel):
    """An obligation instance for a project (BC ``GET /projectObligations``)."""

    id: str
    project_id: str
    obligation_id: str
    due_date: date
    status: ObligationStatus
