"""SQLAlchemy models for the tasks (Tareas) domain.

The Tareas domain is a deliberate **hybrid**: the tasks themselves live in
Business Central (title / project / assignee / due date / priority are read from
``BCUserTask`` DTOs and are **not** stored here). The one locally-owned piece is
the internal notes staff leave on a task.

The board's workflow column is **not** persisted yet: BC cannot represent the
"Esperando información" state and its ``userTasks`` are not writable/readable
live, so moving a card is a client-only, non-persisted interaction until BC can
be the store. See the Tareas board docs in the service module.

``task_notes`` references its BC task by the opaque string id (``task_id``); there
is no foreign key into BC because BC tasks are not rows in this database.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.db.base import Base


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
