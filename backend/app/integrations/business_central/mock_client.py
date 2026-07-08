"""Fixture-backed Business Central client.

:class:`MockBusinessCentralClient` implements the :class:`BusinessCentralClient`
port by reading committed JSON fixtures under ``fixtures/``. It performs no
network I/O and needs no credentials, so downstream product features (#6–#17)
can be built and demoed against a stable contract before real BC access exists.

Fixtures are loaded and validated into the transport DTOs once at import time;
every method returns a fresh copy of the validated list so callers cannot mutate
shared fixture state.
"""

import json
from pathlib import Path

from pydantic import TypeAdapter

from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCCustomer,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCUser,
    BCUserTask,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(filename: str, model: type) -> list:
    """Read ``fixtures/<filename>`` and validate it into a list of ``model``."""
    raw = json.loads((_FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    return TypeAdapter(list[model]).validate_python(raw)


# Validate every fixture once at import so a malformed fixture fails loudly and
# early rather than on the first request.
_CUSTOMERS = _load("customers.json", BCCustomer)
_PROJECTS = _load("projects.json", BCProject)
_USERS = _load("users.json", BCUser)
_USER_TASKS = _load("user_tasks.json", BCUserTask)
_OBLIGATIONS = _load("obligations.json", BCObligation)
_PROJECT_OBLIGATIONS = _load("project_obligations.json", BCProjectObligation)


class MockBusinessCentralClient(BusinessCentralClient):
    """A :class:`BusinessCentralClient` backed by committed JSON fixtures."""

    def get_customers(self) -> list[BCCustomer]:
        return list(_CUSTOMERS)

    def get_projects(self) -> list[BCProject]:
        return list(_PROJECTS)

    def get_users(self) -> list[BCUser]:
        return list(_USERS)

    def get_user_tasks(self) -> list[BCUserTask]:
        return list(_USER_TASKS)

    def get_obligations(self) -> list[BCObligation]:
        return list(_OBLIGATIONS)

    def get_project_obligations(self) -> list[BCProjectObligation]:
        return list(_PROJECT_OBLIGATIONS)
