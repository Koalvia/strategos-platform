"""SQLAlchemy models for the tasks (Tareas) domain.

The Tareas domain is a deliberate **hybrid**: the tasks themselves live in
Business Central (title / project / assignee / due date / priority are read from
``BCUserTask`` DTOs and are **not** stored here). Three small local tables hold the
task data BC does not cover: the internal notes staff leave on a task, and the
platform-native workflow **status** set when a user moves a card between board
columns (one table for BC tasks, one for obligations shown as tasks). Keeping these
local avoids writing back to BC (the system of record for the task's other fields).

The status tables reference their BC item by its opaque string id; there is no
foreign key into BC because BC tasks/obligations are not rows in this database.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)

from app.db.base import Base
from app.integrations.business_central.models import TaskStatus


class TaskNote(Base):
    """An internal note left by a user on a Business-Central-sourced task."""

    __tablename__ = "task_notes"

    id = Column(Integer, primary_key=True, index=True)
    # Opaque BC user-task id the note is attached to (e.g. "task-001"). Not a
    # foreign key: BC tasks are not stored in this database.
    task_id = Column(String, index=True, nullable=False)
    author_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TaskStatusOverride(Base):
    """The platform-owned workflow column for a BC-sourced task.

    BC is read-only and cannot represent "Esperando información", so a task's board
    column, once a user moves it, is persisted here — one row per task (``task_id``
    is unique), the override winning over the BC status on read.
    """

    __tablename__ = "task_status_overrides"

    id = Column(Integer, primary_key=True, index=True)
    # Opaque BC user-task id (e.g. "task-001"). Not a foreign key: BC tasks are not
    # rows in this database. Unique so there is exactly one override per task.
    task_id = Column(String, nullable=False, unique=True, index=True)
    status = Column(SAEnum(TaskStatus), nullable=False)
    updated_by = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class ObligationTaskState(Base):
    """The board workflow column for an obligation shown as a task.

    Obligations are read-only from BC and have no workflow column, so once a user
    moves the obligation's card it is persisted here — one row per obligation
    instance (``bc_obligation_id`` is unique). Absent a row, the column is derived
    (filed -> Hecho, else Pendiente).
    """

    __tablename__ = "obligation_task_states"

    id = Column(Integer, primary_key=True, index=True)
    # Opaque BC project-obligation instance id (e.g. "pobl-001"). No FK: obligations
    # are not rows in this database.
    bc_obligation_id = Column(String, nullable=False, unique=True, index=True)
    status = Column(SAEnum(TaskStatus), nullable=False)
    updated_by = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class BoardCardPosition(Base):
    """The shared vertical order of a card within its board column.

    One global row per card (``(source, card_id)`` unique), independent of the status
    override so reordering never pins a column; cards without a row keep backend order.
    """

    __tablename__ = "board_card_positions"
    __table_args__ = (
        UniqueConstraint("source", "card_id", name="uq_board_card_positions_card"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # Opaque BC id: a user-task id ("task-001") or an obligation instance id
    # ("pobl-001"). No FK: neither is a row in this database.
    card_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)  # "task" | "obligation"
    position = Column(Integer, nullable=False)
    updated_by = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
