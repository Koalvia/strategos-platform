# app/core/dependencies.py
from app.domains.identity.models import User
from fastapi import Depends, HTTPException

from app.core.security import get_current_user


def require_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="User not verified")
    return user
