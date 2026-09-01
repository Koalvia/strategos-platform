# app/core/dependencies.py
from functools import lru_cache

from fastapi import Depends, HTTPException

from app.core.config import settings
from app.core.security import get_current_user
from app.core.visibility import CustomerScope, resolve_customer_scope
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.bopa import (
    BopaClient,
    LiveBopaClient,
    MockBopaClient,
)
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


@lru_cache(maxsize=1)
def _live_bopa_client() -> LiveBopaClient:
    """Build the live BOPA client once so its HTTP connection pool is reused.

    The provider below runs per request; caching the instance keeps one pool for
    the whole process rather than opening a fresh client every call.
    """
    return LiveBopaClient.from_settings(settings)


def get_bopa_client() -> BopaClient:
    """Return the BOPA client for the configured mode.

    ``BOPA_MODE`` defaults to ``"mock"``, a fixture-backed client that needs no
    network access. ``"live"`` returns the real BOPA client built from the
    ``BOPA_*`` settings. Any other value is rejected explicitly.
    """
    if settings.BOPA_MODE == "mock":
        return MockBopaClient()
    if settings.BOPA_MODE == "live":
        return _live_bopa_client()
    raise RuntimeError(
        f"Unsupported BOPA_MODE: {settings.BOPA_MODE!r}. "
        'Expected "mock" or "live".'
    )


def get_customer_scope(
    user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
) -> CustomerScope:
    """Resolve the caller's customer scope once per request.

    Uses the same ``get_verified_user`` the routers do: it yields the ORM ``User``
    (with its email), unlike ``require_verified_user``'s token payload.
    """
    return resolve_customer_scope(user, bc_client)
