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
    Boolean,
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


class AlertCategory(enum.Enum):
    """The email/notification category, finer than ``AlertType``.

    OBLIGATION alerts split by their BC obligation code so each gets its own email
    template and per-user preference: DNI/PASSAPORT are documents, IVA its own,
    everything else the generic obligation.
    """

    BOPA = "BOPA"
    DOCUMENT_EXPIRY = "DOCUMENT_EXPIRY"
    IVA = "IVA"
    OBLIGATION = "OBLIGATION"
    # A traffic-light colour worsening for an obligation (green->yellow->red).
    # Reuses ``AlertType.OBLIGATION`` but is its own email template and per-user
    # preference; it is set explicitly on the alert (``Alert.category``) because it
    # cannot be derived from the BC obligation code like the others.
    TRAFFIC_CHANGE = "TRAFFIC_CHANGE"


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
    # The BC obligation code (DNI/PASSAPORT/IVA/...) for OBLIGATION alerts, so the
    # email layer picks a template/category without re-reading BC. BOPA leaves NULL.
    obligation_code = Column(String, nullable=True)
    # Explicit email category override. NULL means "derive from type + code" (the
    # default for BOPA and one-per-life obligation alerts); it is set to
    # ``TRAFFIC_CHANGE`` for colour-change alerts, which reuse
    # ``AlertType.OBLIGATION`` but must not be routed like a due-date obligation.
    category = Column(Enum(AlertCategory), nullable=True)
    # Set the first (and only) time this alert is emailed — the dedup guard.
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
    # Denormalized display text (populated for OBLIGATION alerts at creation so
    # the read path stays DB-only; BOPA alerts resolve display via bopa_match).
    title = Column(String, nullable=True)
    message = Column(String, nullable=True)
    status = Column(Enum(AlertStatus), nullable=False, default=AlertStatus.NEW)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bopa_match = relationship("BopaMatch")


class UserAlertPreference(Base):
    """Per-user opt-in/out of alert emails, by category.

    A missing row means "use the default" (enabled): a user only ever has rows for
    categories they have explicitly changed. One row per (user, category).
    """

    __tablename__ = "user_alert_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_user_alert_pref"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category = Column(Enum(AlertCategory), nullable=False)
    email_enabled = Column(Boolean, nullable=False, default=True)


class ObligationTrafficState(Base):
    """Remembered traffic-light status per obligation, to detect *transitions*.

    Obligations are read-only from Business Central with no local row, so there is
    nowhere to hang "what colour was this yesterday?". This one-row-per-obligation
    table remembers each instance's last derived status so
    ``alerts.evaluate_traffic_transitions`` can tell green->yellow->red worsenings
    from steady state and only email on a worsening. Idempotency of that task comes
    entirely from ``last_status``: a same-day re-run finds it already advanced and
    stages nothing.

    ``last_status`` stores the derived-status *value* (the Spanish label such as
    ``"Al día"``/``"Vencido"``, matching
    :class:`~app.domains.obligations.schemas.DerivedObligationStatus`).
    """

    __tablename__ = "obligation_traffic_state"

    id = Column(Integer, primary_key=True, index=True)
    # The opaque BC project-obligation instance id (one state row per instance).
    bc_obligation_id = Column(String, nullable=False, unique=True, index=True)
    last_status = Column(String, nullable=False)
    last_evaluated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
