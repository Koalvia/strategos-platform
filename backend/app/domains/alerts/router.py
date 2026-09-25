"""HTTP routes for the Alerts domain.

Alerts are platform-native notifications generated from BOPA matches. State is
global (shared by all users), so these routes read and mutate a single shared
lifecycle per alert. Every route requires a verified user (and the ``x-api-key``
gateway header, except under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user

from .models import AlertStatus
from .schemas import (
    AlertPage,
    AlertPreference,
    AlertPreferencesResponse,
    AlertPreferenceUpdate,
    AlertResponse,
    AlertUpdate,
    UnreadCountResponse,
)
from .service import AlertsService

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/preferences", response_model=AlertPreferencesResponse)
def get_alert_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Return the current user's per-category alert-email preferences."""
    prefs = AlertsService(db).get_preferences(current_user.id)
    return AlertPreferencesResponse(
        items=[
            AlertPreference(category=c, email_enabled=enabled)
            for c, enabled in prefs.items()
        ]
    )


@router.put("/preferences", response_model=AlertPreferencesResponse)
def update_alert_preferences(
    data: AlertPreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Toggle alert emails for one category for the current user."""
    service = AlertsService(db)
    service.set_preference(current_user.id, data.category, data.email_enabled)
    prefs = service.get_preferences(current_user.id)
    return AlertPreferencesResponse(
        items=[
            AlertPreference(category=c, email_enabled=enabled)
            for c, enabled in prefs.items()
        ]
    )


@router.get("", response_model=AlertPage)
def list_alerts(
    status: AlertStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """List alerts, newest first, optionally filtered by ``status``.

    ``status`` (``new`` / ``viewed`` / ``discarded``) restricts to one lifecycle
    state; ``limit`` (1–200) / ``offset`` page the result.
    """
    return AlertsService(db).list_alerts(status=status, limit=limit, offset=offset)


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Return the number of unread (``new``) alerts, for the sidebar badge."""
    return UnreadCountResponse(count=AlertsService(db).unread_count())


@router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Mark every unread alert as viewed; return how many changed."""
    return {"updated": AlertsService(db).mark_all_read()}


@router.patch("/{alert_id}", response_model=AlertResponse)
def update_alert(
    alert_id: int,
    data: AlertUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Change an alert's lifecycle status (404 if the alert is unknown)."""
    return AlertsService(db).update_status(alert_id, data.status)
