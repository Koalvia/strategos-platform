"""Business logic for the users (Usuarios) directory.

Identity is 100% local this round, so the directory lists the local
``auth.User`` rows (name, role, email) and does **not** consume BC ``/users`` for
identity. Business Central is read for ``userTasks`` (each user's active-task
load: the count of their non-"Hecho" tasks) and for ``userSetups``, whose
``manageAllCustomers`` flag decides whether the caller sees the whole directory
or only their own entry.

Each local user is mapped to their BC assignee by **email** (case-insensitive),
mirroring the tasks domain; a user with no matching BC user simply shows 0 active
tasks. Because the BC assignee counts are keyed by email against the BC user
directory, the numbers reflect whatever the mock BC data holds.
"""

from sqlalchemy.orm import Session

from app import logger
from app.domains.auth.models import User
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import TaskStatus

from .schemas import UserDirectoryEntry


class UsersService:
    """Serve the staff directory: local users plus their BC active-task load."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_directory(self, current_user: User) -> list[UserDirectoryEntry]:
        """Return the directory as ``current_user`` is allowed to see it.

        A user whose BC setup has ``manageAllCustomers`` set sees every local
        user, in insertion order (by id) so the list matches the Usuarios mock's
        ordering; anyone else sees only their own entry.
        """
        active_by_email = self._active_tasks_by_email()
        users = self.db.query(User).order_by(User.id.asc()).all()

        if not self._manage_all_customers(current_user):
            own_email = (current_user.email or "").casefold()
            users = [u for u in users if (u.email or "").casefold() == own_email]

        return [
            UserDirectoryEntry(
                name=user.name,
                role=user.role,
                email=user.email,
                active_tasks=active_by_email.get((user.email or "").casefold(), 0),
            )
            for user in users
        ]

    def _manage_all_customers(self, user: User) -> bool:
        """Whether ``user``'s BC setup grants them the full directory.

        Resolves local user → BC user (by email) → BC user setup (by the BC User
        ID code). Any unresolved hop is logged and denies the permission, so a
        missing setup or a BC outage restricts rather than over-shares.
        """
        email = (user.email or "").casefold()
        bc_user = next(
            (u for u in self.bc_client.get_users() if u.email.casefold() == email),
            None,
        )
        if bc_user is None or not bc_user.user_name:
            logger.warning(
                "No Business Central user matches %s; denying manageAllCustomers",
                user.email,
            )
            return False

        code = bc_user.user_name.casefold()
        setup = next(
            (s for s in self.bc_client.get_user_setups() if s.user_id.casefold() == code),
            None,
        )
        if setup is None:
            logger.warning(
                "No Business Central user setup for %s; denying manageAllCustomers",
                bc_user.user_name,
            )
            return False

        return setup.manage_all_customers

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
