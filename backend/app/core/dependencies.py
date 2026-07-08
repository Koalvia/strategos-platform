# app/core/dependencies.py
from fastapi import Depends, HTTPException

from app.core.config import settings
from app.core.security import get_current_user
from app.domains.auth.models import User
from app.integrations.business_central import (
    BusinessCentralClient,
    MockBusinessCentralClient,
)


def require_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="User not verified")
    return user


def get_business_central_client() -> BusinessCentralClient:
    """Return the Business Central client for the configured mode.

    This is the single injection point every BC-backed service depends on.
    ``BUSINESS_CENTRAL_MODE`` defaults to ``"mock"``, which returns a
    fixture-backed client that needs no credentials. A live client is not
    implemented yet, so any other mode is rejected explicitly.
    """
    if settings.BUSINESS_CENTRAL_MODE == "mock":
        return MockBusinessCentralClient()
    raise RuntimeError(
        f"Unsupported BUSINESS_CENTRAL_MODE: {settings.BUSINESS_CENTRAL_MODE!r}. "
        'Only "mock" is currently implemented.'
    )
