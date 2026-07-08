"""Pydantic v2 schemas for the users (Usuarios) directory.

The directory joins two sources: the local ``auth.User`` rows (name, role, email
— identity stays 100% local this round) and the per-user active-task count derived
from Business Central's ``userTasks``. Field names mirror the columns of
``usuarios.png``: Nombre / Rol / Email / Tareas activas.
"""

from pydantic import BaseModel


class UserDirectoryEntry(BaseModel):
    """A staff member as shown in the Usuarios directory."""

    name: str
    role: str | None = None
    email: str
    active_tasks: int
