"""SQLAlchemy model for runtime, DB-backed platform settings.

The obligations traffic light needs day thresholds a director can change at
runtime (green→yellow and yellow→red). These live in a single-row table rather
than in ``app.core.config`` because they are edited through the API, not read
from the environment.

The table always holds exactly one row (``id == 1``); the service seeds it on
first read (see :class:`~app.domains.settings.service.SettingsService`).
"""

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy.sql import func

from app.db.base import Base

# The single row's primary key. The store is a singleton, so the service always
# reads/writes this id.
TRAFFIC_LIGHT_SETTINGS_ID = 1

# Seed values inserted on first read (see the issue's acceptance criteria).
DEFAULT_YELLOW_WITHIN_DAYS = 15
DEFAULT_RED_WITHIN_DAYS = 5
DEFAULT_EMAIL_ON_CHANGE_ENABLED = True


class TrafficLightSettings(Base):
    """Day thresholds for the obligations traffic light (single row, ``id == 1``).

    ``yellow_within_days`` is the green→yellow boundary and ``red_within_days`` the
    yellow→red one; the service enforces ``0 < red_within_days < yellow_within_days``.
    ``email_on_change_enabled`` toggles the "email on worsening transition" feature
    (behaviour lives in a later task).
    """

    __tablename__ = "traffic_light_settings"

    id = Column(Integer, primary_key=True)
    yellow_within_days = Column(Integer, nullable=False)
    red_within_days = Column(Integer, nullable=False)
    email_on_change_enabled = Column(Boolean, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
