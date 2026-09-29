"""Which customers a user is allowed to see.

The caller's login email is matched against BC ``resources.email``; their assigned
customers come from ``customersResources``, and ``manageAllCustomers`` lifts the limit.
"""

from dataclasses import dataclass

from app import logger
from app.domains.auth.models import User
from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import BCProject, BCUser


@dataclass(frozen=True)
class CustomerScope:
    """The customers a caller may see. ``customer_ids=None`` means every customer,
    which only a manager gets; a tuple keeps the frozen dataclass genuinely immutable.

    ``reason`` names the branch taken, so the logs distinguish "restricted" from
    "the Business Central join is broken" — they look identical on screen.
    """

    customer_ids: tuple[str, ...] | None
    reason: str

    @property
    def sees_everything(self) -> bool:
        return self.customer_ids is None

    def sees(self, customer_id: str) -> bool:
        """Whether this caller may see ``customer_id`` (a manager sees every one)."""
        return self.customer_ids is None or customer_id in self.customer_ids


def resolve_customer_scope(
    user: User, bc_client: BusinessCentralClient
) -> CustomerScope:
    """Resolve ``user`` to their customer scope, reading Business Central.

    Only ``manageAllCustomers`` lifts the limit: without it a caller sees exactly the
    customers assigned to them, and an unlinked account sees none.
    """
    # A blank email must never match the blank email of a resource: BC leaves the
    # field empty on most cards, so that would hand out someone else's customers.
    email = (user.email or "").strip().casefold()
    resources = (
        [
            r
            for r in bc_client.get_resources()
            if (r.email or "").strip().casefold() == email
        ]
        if email
        else []
    )

    if not resources:
        logger.warning(
            "No Business Central resource has the email %s; they will see no customers",
            user.email,
        )
        return CustomerScope(customer_ids=(), reason="unlinked")

    if any(r.manage_all_customers for r in resources):
        return CustomerScope(customer_ids=None, reason="manager")

    # A person can hold several resource cards, so union the customers of all of them.
    resource_ids = {r.id for r in resources}
    customer_ids = tuple(
        sorted(
            {
                assignment.customer_id
                for assignment in bc_client.get_customer_resources()
                if assignment.resource_id in resource_ids and assignment.customer_id
            }
        )
    )

    if not customer_ids:
        logger.warning(
            "Business Central has no customer assigned to %s (resources %s); "
            "they will see no customers",
            user.email,
            sorted(resource_ids),
        )

    return CustomerScope(customer_ids=customer_ids, reason="assignments")


def users_by_key(bc_users: list[BCUser]) -> dict[str, BCUser]:
    """Map each BC user's code (``userName``) and name, casefolded, to the user."""
    by_key: dict[str, BCUser] = {}
    for bc_user in bc_users:
        if bc_user.user_name:
            by_key.setdefault(bc_user.user_name.casefold(), bc_user)
        if bc_user.name:
            by_key.setdefault(bc_user.name.casefold(), bc_user)
    return by_key


def project_owner_emails(project: BCProject, by_key: dict[str, BCUser]) -> set[str]:
    """Casefolded emails of a project's technician and responsible (BC codes/names)."""
    emails: set[str] = set()
    for key in (project.technician, project.responsible):
        if not key:
            continue
        bc_user = by_key.get(key.casefold())
        if bc_user is not None and bc_user.email:
            emails.add(bc_user.email.casefold())
    return emails


def may_see_project(
    project: BCProject,
    user_email: str,
    scope: CustomerScope,
    by_key: dict[str, BCUser],
) -> bool:
    """Union rule: the project's client is in scope, or the caller is its owner."""
    if scope.sees(project.customer_id):
        return True
    email = (user_email or "").casefold()
    return bool(email) and email in project_owner_emails(project, by_key)
