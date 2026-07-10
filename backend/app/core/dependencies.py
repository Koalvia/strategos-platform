# app/core/dependencies.py
from functools import lru_cache

from fastapi import Depends, HTTPException

from app.core.config import settings
from app.core.security import get_current_user
from app.domains.auth.models import User
from app.integrations.business_central import (
    BusinessCentralClient,
    LiveBusinessCentralClient,
    MockBusinessCentralClient,
)


def require_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="User not verified")
    return user


@lru_cache(maxsize=1)
def _live_business_central_client() -> LiveBusinessCentralClient:
    """Build the live client once so its in-memory token cache survives requests.

    The provider below runs per request, but a fresh instance each time would
    re-authenticate on every call. Caching the instance keeps one token cache
    (and one HTTP connection pool) for the whole process.
    """
    return LiveBusinessCentralClient.from_settings(settings)


def get_business_central_client() -> BusinessCentralClient:
    """Return the Business Central client for the configured mode.

    This is the single injection point every BC-backed service depends on.
    ``BUSINESS_CENTRAL_MODE`` defaults to ``"mock"``, a fixture-backed client that
    needs no credentials. ``"live"`` returns the real BC REST client built from the
    ``BC_*`` settings. Any other value is rejected explicitly.
    """
    if settings.BUSINESS_CENTRAL_MODE == "mock":
        return MockBusinessCentralClient()
    if settings.BUSINESS_CENTRAL_MODE == "live":
        return _live_business_central_client()
    raise RuntimeError(
        f"Unsupported BUSINESS_CENTRAL_MODE: {settings.BUSINESS_CENTRAL_MODE!r}. "
        'Expected "mock" or "live".'
    )
