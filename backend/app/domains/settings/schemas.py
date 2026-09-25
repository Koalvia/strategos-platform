"""Pydantic v2 schemas for the settings domain."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrafficLightSettingsResponse(BaseModel):
    """The obligations traffic-light thresholds as read from the store."""

    model_config = ConfigDict(from_attributes=True)

    yellow_within_days: int
    red_within_days: int
    email_on_change_enabled: bool
    updated_at: datetime | None


class TrafficLightSettingsUpdate(BaseModel):
    """Request body to replace the traffic-light thresholds.

    All fields are required: the update is a full replacement, and the service
    rejects it with 422 unless ``0 < red_within_days < yellow_within_days``.
    """

    yellow_within_days: int
    red_within_days: int
    email_on_change_enabled: bool
