"""Which customers a user is allowed to see.

The caller's login email is matched against BC ``resources.email``; their assigned
customers come from ``customersResources``, and ``manageAllCustomers`` lifts the limit.
"""

from dataclasses import dataclass

from app import logger
from app.domains.auth.models import User
from app.integrations.business_central.client import BusinessCentralClient


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
