"""Smoke tests proving the test harness boots and wires app + auth + DB.

These intentionally cover only existing behavior (the public health check).
Feature-specific tests belong with the feature that adds them.
"""


def test_health_ok(client):
    """The app boots and the public health endpoint responds without an API key."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
