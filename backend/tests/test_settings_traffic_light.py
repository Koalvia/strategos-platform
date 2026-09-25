"""Tests for the traffic-light settings store and its director-only update.

The store is a single row seeded on first read (15 / 5 / true). Reads are open to
any verified user; the update is restricted to a "director" — a caller whose
customer scope sees everything. We drive that check with a dependency override for
``get_customer_scope`` (mirroring ``test_customer_scoping`` / ``test_visibility``),
rather than standing up Business Central fixtures.
"""

import pytest

from app.core.dependencies import get_customer_scope
from app.core.visibility import CustomerScope
from app.domains.settings.models import (
    TRAFFIC_LIGHT_SETTINGS_ID,
    TrafficLightSettings,
)
from app.main import app

TRAFFIC_LIGHT_URL = "/api/v1/settings/traffic-light"

# The ``client`` fixture already pins the scope to "sees everything" (a director);
# tests that need a non-director swap in this scope.
RESTRICTED_SCOPE = CustomerScope(customer_ids=("cust-001",), reason="test-restricted")


def _override_scope(scope: CustomerScope) -> None:
    app.dependency_overrides[get_customer_scope] = lambda: scope


@pytest.mark.integration
def test_get_seeds_defaults(client, db_session):
    """A first read returns the seed defaults and persists the singleton row."""
    assert db_session.get(TrafficLightSettings, TRAFFIC_LIGHT_SETTINGS_ID) is None

    resp = client.get(TRAFFIC_LIGHT_URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body["yellow_within_days"] == 15
    assert body["red_within_days"] == 5
    assert body["email_on_change_enabled"] is True

    row = db_session.get(TrafficLightSettings, TRAFFIC_LIGHT_SETTINGS_ID)
    assert row is not None
    assert row.yellow_within_days == 15
    assert row.red_within_days == 5


@pytest.mark.integration
def test_update_as_director(client, db_session):
    """A director (scope sees everything) updates and gets the new values back."""
    resp = client.put(
        TRAFFIC_LIGHT_URL,
        json={
            "yellow_within_days": 30,
            "red_within_days": 10,
            "email_on_change_enabled": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["yellow_within_days"] == 30
    assert body["red_within_days"] == 10
    assert body["email_on_change_enabled"] is False

    row = db_session.get(TrafficLightSettings, TRAFFIC_LIGHT_SETTINGS_ID)
    assert row.yellow_within_days == 30
    assert row.red_within_days == 10
    assert row.email_on_change_enabled is False


@pytest.mark.integration
def test_update_as_non_director_forbidden(client, db_session):
    """A non-director gets 403 and the stored values are left unchanged."""
    # Seed the row first so we can assert it is untouched.
    client.get(TRAFFIC_LIGHT_URL)
    _override_scope(RESTRICTED_SCOPE)

    resp = client.put(
        TRAFFIC_LIGHT_URL,
        json={
            "yellow_within_days": 30,
            "red_within_days": 10,
            "email_on_change_enabled": False,
        },
    )

    assert resp.status_code == 403

    row = db_session.get(TrafficLightSettings, TRAFFIC_LIGHT_SETTINGS_ID)
    assert row.yellow_within_days == 15
    assert row.red_within_days == 5
    assert row.email_on_change_enabled is True


@pytest.mark.integration
@pytest.mark.parametrize(
    ("yellow", "red"),
    [
        (5, 15),  # red >= yellow (wrong ordering)
        (10, 10),  # red == yellow
        (10, 0),  # non-positive red
        (10, -1),  # negative red
    ],
)
def test_update_invalid_thresholds_returns_422(client, yellow, red):
    """Invalid ordering or a non-positive red boundary is rejected with 422."""
    resp = client.put(
        TRAFFIC_LIGHT_URL,
        json={
            "yellow_within_days": yellow,
            "red_within_days": red,
            "email_on_change_enabled": True,
        },
    )

    assert resp.status_code == 422
