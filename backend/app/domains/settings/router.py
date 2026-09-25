"""HTTP routes for the settings domain.

Exposes the obligations traffic-light thresholds: any verified user may read
them, but only a director (a caller whose customer scope sees everything) may
change them.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_director_user
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user

from .schemas import TrafficLightSettingsResponse, TrafficLightSettingsUpdate
from .service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/traffic-light", response_model=TrafficLightSettingsResponse)
def get_traffic_light_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Return the obligations traffic-light thresholds (seeds defaults on first read)."""
    return SettingsService(db).get_traffic_light()


@router.put("/traffic-light", response_model=TrafficLightSettingsResponse)
def update_traffic_light_settings(
    data: TrafficLightSettingsUpdate,
    db: Session = Depends(get_db),
    director: User = Depends(get_director_user),
):
    """Replace the traffic-light thresholds (director only; 422 on invalid ordering)."""
    return SettingsService(db).update_traffic_light(data)
