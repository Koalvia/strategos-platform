import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class PriorityEnum(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"

class RecurrenceEnum(str, enum.Enum):
    none = "none"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    list_id = Column(Integer, ForeignKey("lists.id", ondelete="CASCADE"), nullable=False)
    priority = Column(Enum(PriorityEnum), default=PriorityEnum.medium)
    due_date = Column(Date, nullable=True)
    completed = Column(Boolean, default=False)
    recurrence = Column(
        Enum(RecurrenceEnum),
        nullable=False,
        server_default="none",
        default=RecurrenceEnum.none,
    )
    parent_task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    list = relationship("List", back_populates="tasks")
    parent_task = relationship("Task", remote_side=[id], backref="occurrences")
