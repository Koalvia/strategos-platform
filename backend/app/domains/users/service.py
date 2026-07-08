"""Business logic for the users (Usuarios) directory.

Identity is 100% local this round, so the directory lists the local
``auth.User`` rows (name, role, email) and does **not** consume BC ``/users`` for
identity. The only Business Central read here is ``userTasks``, used to compute
each user's active-task load: the count of their non-"Hecho" (not-done) tasks.

Each local user is mapped to their BC assignee by **email** (case-insensitive),
mirroring the tasks domain; a user with no matching BC user simply shows 0 active
tasks. Because the BC assignee counts are keyed by email against the BC user
directory, the numbers reflect whatever the mock BC data holds.
"""

from sqlalchemy.orm import Session

from app.domains.auth.models import User
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import TaskStatus

from .schemas import UserDirectoryEntry


class UsersService:
    """Serve the staff directory: local users plus their BC active-task load."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_directory(self) -> list[UserDirectoryEntry]:
        """Return every local user with name, role, email and active-task count.

        Users are returned in insertion order (by id) so the list matches the
        Usuarios mock's ordering.
        """
        active_by_email = self._active_tasks_by_email()
        users = self.db.query(User).order_by(User.id.asc()).all()
        return [
            UserDirectoryEntry(
                name=user.name,
                role=user.role,
                email=user.email,
                active_tasks=active_by_email.get((user.email or "").casefold(), 0),
            )
            for user in users
        ]

    def _active_tasks_by_email(self) -> dict[str, int]:
        """Map each BC user's email (case-folded) to their non-done task count."""
        active_by_assignee: dict[str, int] = {}
        for task in self.bc_client.get_user_tasks():
            if task.status is TaskStatus.done:
                continue
            active_by_assignee[task.assignee_id] = (
                active_by_assignee.get(task.assignee_id, 0) + 1
            )

        return {
            bc_user.email.casefold(): active_by_assignee.get(bc_user.id, 0)
            for bc_user in self.bc_client.get_users()
        }
