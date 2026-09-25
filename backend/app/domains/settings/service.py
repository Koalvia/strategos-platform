"""Business logic for the DB-backed platform settings.

The traffic-light thresholds live in a single-row table. This service owns the
get-or-seed read (returning the defaults and inserting the seed row on first
access) and the validated update.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import (
    DEFAULT_EMAIL_ON_CHANGE_ENABLED,
    DEFAULT_RED_WITHIN_DAYS,
    DEFAULT_YELLOW_WITHIN_DAYS,
    TRAFFIC_LIGHT_SETTINGS_ID,
    TrafficLightSettings,
)
from .schemas import TrafficLightSettingsUpdate


class SettingsService:
    """Read and update the singleton traffic-light settings row."""

    def __init__(self, db: Session):
        self.db = db

    def get_traffic_light(self) -> TrafficLightSettings:
        """Return the traffic-light settings, seeding the row on first read.

        The store is a singleton (``id == 1``). If the row does not exist yet it is
        created with the seed defaults (15 / 5 / true) and persisted, so subsequent
        reads and updates operate on a real row.
        """
        settings_row = self.db.get(TrafficLightSettings, TRAFFIC_LIGHT_SETTINGS_ID)
        if settings_row is None:
            settings_row = TrafficLightSettings(
                id=TRAFFIC_LIGHT_SETTINGS_ID,
                yellow_within_days=DEFAULT_YELLOW_WITHIN_DAYS,
                red_within_days=DEFAULT_RED_WITHIN_DAYS,
                email_on_change_enabled=DEFAULT_EMAIL_ON_CHANGE_ENABLED,
            )
            self.db.add(settings_row)
            self.db.commit()
            self.db.refresh(settings_row)
        return settings_row

    def update_traffic_light(
        self, data: TrafficLightSettingsUpdate
    ) -> TrafficLightSettings:
        """Replace the traffic-light thresholds after validating their ordering.

        Rejects with 422 unless ``0 < red_within_days < yellow_within_days`` (red
        must be a strictly nearer, positive boundary than yellow).
        """
        if not 0 < data.red_within_days < data.yellow_within_days:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Thresholds must satisfy 0 < red_within_days < yellow_within_days"
                ),
            )

        settings_row = self.get_traffic_light()
        settings_row.yellow_within_days = data.yellow_within_days
        settings_row.red_within_days = data.red_within_days
        settings_row.email_on_change_enabled = data.email_on_change_enabled
        self.db.commit()
        self.db.refresh(settings_row)
        return settings_row
