"""Microsoft Business Central integration.

Strategos reads its core data (customers, projects, users, tasks, obligations)
from Business Central via BC's REST API. This package defines the integration
seam:

* :class:`~app.integrations.business_central.client.BusinessCentralClient` — the
  port (one method per BC endpoint, each returning typed Pydantic DTOs).
* :class:`~app.integrations.business_central.mock_client.MockBusinessCentralClient`
  — a fixture-backed implementation used until real BC credentials exist.

Every BC-backed service depends on the port, not on a concrete client, so the
mock can be swapped for a live implementation later without changing callers.
"""

from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.mock_client import MockBusinessCentralClient

__all__ = ["BusinessCentralClient", "MockBusinessCentralClient"]
