"""HTTP routes for the settings domain.

Exposes the obligations traffic-light thresholds: any verified user may read
them, but only a director (a caller whose customer scope sees everything) may
change them.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_customer_scope, get_director_user
from app.core.visibility import CustomerScope
from app.db.session import get_db
from app.domains.auth.models import User

from .schemas import TrafficLightSettingsResponse, TrafficLightSettingsUpdate
from .service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_response(row, editable: bool) -> TrafficLightSettingsResponse:
    """Build the response, tagging whether the caller may edit the thresholds."""
    return TrafficLightSettingsResponse(
        yellow_within_days=row.yellow_within_days,
        red_within_days=row.red_within_days,
        email_on_change_enabled=row.email_on_change_enabled,
        updated_at=row.updated_at,
        editable=editable,
    )


@router.get("/traffic-light", response_model=TrafficLightSettingsResponse)
def get_traffic_light_settings(
    db: Session = Depends(get_db),
    scope: CustomerScope = Depends(get_customer_scope),
):
    """Return the traffic-light thresholds (seeds defaults on first read).

    ``editable`` is true only for a manager (scope sees everything), so the UI can
    show the editor to managers and hide it from everyone else.
    """
    return _to_response(
        SettingsService(db).get_traffic_light(), editable=scope.sees_everything
    )


@router.put("/traffic-light", response_model=TrafficLightSettingsResponse)
def update_traffic_light_settings(
    data: TrafficLightSettingsUpdate,
    db: Session = Depends(get_db),
    director: User = Depends(get_director_user),
):
    """Replace the traffic-light thresholds (director only; 422 on invalid ordering)."""
    # Reaching here means the caller passed get_director_user, so editable is True.
    return _to_response(SettingsService(db).update_traffic_light(data), editable=True)
