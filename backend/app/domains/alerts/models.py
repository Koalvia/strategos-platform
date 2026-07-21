"""SQLAlchemy models for the Alerts domain.

The Alerts domain is the platform's unified notification center. Unlike the
Tareas domain (a hybrid), alerts are fully native to this database; they track
the lifecycle of notifications linked to specific customers.

An alert is one of two **types** (discriminated by ``alert_type``):

* ``BOPA`` — a customer/project match found in an official bulletin, linked to a
  :class:`~app.domains.bopa.models.BopaMatch` via ``bopa_match_id``. Created by
  the BOPA analysis cronjob.
* ``OBLIGATION`` — a Business Central obligation ("Obligación") whose
  notification date has arrived, keyed by the opaque external ``bc_obligation_id``
  (no physical FK — BC data lives externally). Created by the daily
  ``alerts.generate_obligation_alerts`` task.

Each alert serves as a collaboration trigger, letting staff acknowledge or
discard notifications. Alert states are persisted locally to ensure stateful
tracking (New/Viewed/Discarded) without write-back to external systems.

State is intentionally **global** (shared by every user), not per-user: an
alert's ``status`` is a single shared column and ``user_id`` is left NULL to mean
"for all users". Two unique constraints keep the generators idempotent —
``uq_alert_bopa_match`` (one alert per BOPA match) and ``uq_alert_bc_obligation``
(one alert per BC obligation, ever). Both columns are nullable and only one is
set per row; multiple NULLs are permitted by a unique constraint on Postgres and
SQLite, so the two alert types never collide.
"""
import enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class AlertStatus(enum.Enum):
    NEW = "new"
    VIEWED = "viewed"
    DISCARDED = "discarded"


class AlertType(enum.Enum):
    BOPA = "BOPA"
    OBLIGATION = "OBLIGATION"


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("bopa_match_id", name="uq_alert_bopa_match"),
        UniqueConstraint("bc_obligation_id", name="uq_alert_bc_obligation"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # NULL means the alert is for all users (see module docstring).
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    customer_id = Column(String, nullable=False, index=True)
    # server_default is quoted SQL (text("'BOPA'")); a bare string would render
    # as unquoted DEFAULT BOPA, which is invalid for a Postgres enum column when
    # the schema is built via create_all() rather than the Alembic migration.
    alert_type = Column(
        Enum(AlertType), nullable=False, server_default=text(f"'{AlertType.BOPA.value}'")
    )
    # BOPA alerts link to a BopaMatch; OBLIGATION alerts leave this NULL.
    bopa_match_id = Column(
        Integer, ForeignKey("bopa_matches.id", ondelete="CASCADE"), index=True
    )
    # OBLIGATION alerts carry the opaque BC obligation id; BOPA alerts leave NULL.
    bc_obligation_id = Column(String, nullable=True, index=True)
    # Denormalized display text (populated for OBLIGATION alerts at creation so
    # the read path stays DB-only; BOPA alerts resolve display via bopa_match).
    title = Column(String, nullable=True)
    message = Column(String, nullable=True)
    status = Column(Enum(AlertStatus), nullable=False, default=AlertStatus.NEW)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bopa_match = relationship("BopaMatch")
