"""SQLAlchemy models for the tasks (Tareas) domain.

The Tareas domain is a deliberate **hybrid**: the tasks themselves live in
Business Central (title / project / assignee / due date / priority / status are
read from ``BCUserTask`` DTOs and are **not** stored here), while this one small
local table holds the only piece of task data BC does not cover — internal notes
staff leave on a task. Keeping notes local avoids writing back to BC (which is
the system of record for the tasks) while still giving the platform a native
collaboration surface.

Notes reference their BC task by its opaque string id (``task_id``); there is no
foreign key into BC because BC tasks are not rows in this database.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

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
