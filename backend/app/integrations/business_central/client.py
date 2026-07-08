"""Business Central client port.

The abstract base class every BC client implementation must satisfy. It defines
one method per Business Central endpoint, each returning typed Pydantic DTOs.
Services depend on this interface (via the DI provider in
``app.core.dependencies``), never on a concrete implementation, so the current
:class:`MockBusinessCentralClient` can be replaced by a live client later without
touching callers.
"""

from abc import ABC, abstractmethod

from app.integrations.business_central.models import (
    BCCustomer,
    BCObligation,
    BCProject,
    BCProjectObligation,
    BCUser,
    BCUserTask,
)


class BusinessCentralClient(ABC):
    """Port mirroring the Business Central REST endpoints Strategos consumes."""

    @abstractmethod
    def get_customers(self) -> list[BCCustomer]:
        """Return all customers (BC ``GET /customers``)."""
        raise NotImplementedError

    @abstractmethod
    def get_projects(self) -> list[BCProject]:
        """Return all projects (BC ``GET /projects``)."""
        raise NotImplementedError

    @abstractmethod
    def get_users(self) -> list[BCUser]:
        """Return all internal users (BC ``GET /users``)."""
        raise NotImplementedError

    @abstractmethod
    def get_user_tasks(self) -> list[BCUserTask]:
        """Return all user tasks (BC ``GET /userTasks``)."""
        raise NotImplementedError

    @abstractmethod
    def get_obligations(self) -> list[BCObligation]:
        """Return the obligation catalog (BC ``GET /obligations``)."""
        raise NotImplementedError

    @abstractmethod
    def get_project_obligations(self) -> list[BCProjectObligation]:
        """Return all project-obligation instances (BC ``GET /projectObligations``)."""
        raise NotImplementedError
