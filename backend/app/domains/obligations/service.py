"""Business logic for the obligations (Obligaciones) domain.

The service reads obligations read-only from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
(never from fixtures directly). It exposes two things:

* the obligation **catalog** (``BCObligation`` DTOs mapped to
  :class:`~app.domains.obligations.schemas.ObligationTypeResponse`), and
* the **per-project instances** (``BCProjectObligation`` DTOs), enriched with the
  obligation, project and client display names and a **derived** due state.

The due state is computed by the pure :func:`derive_status` helper against a
reference date supplied by the caller (the router injects the server date; tests
freeze it), so it can be asserted deterministically without patching the clock.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.integrations.business_central.client import BusinessCentralClient
from app.integrations.business_central.models import (
    BCObligation,
    BCProject,
    BCProjectObligation,
)

from .schemas import (
    DerivedObligationStatus,
    EntityRef,
    ObligationRef,
    ObligationTypeResponse,
    ProjectObligationResponse,
)

#: Default window (in days) within which an unfiled obligation counts as upcoming.
DEFAULT_UPCOMING_WINDOW_DAYS = 7


def derive_status(
    due_date: date | None,
    submission_date: date | None,
    reference_date: date,
    upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
) -> DerivedObligationStatus:
    """Derive an obligation's due state relative to ``reference_date``.

    * An instance with no ``due_date`` is ``Sin fecha`` (undated): it cannot be
      placed on the calendar, so it is excluded from the overdue/upcoming/on-track
      partitioning. The live BC ``projectObligation`` link carries no dates yet,
      so today this is effectively every live instance (expected, not a bug).
    * A filed instance (``submission_date`` set) is always ``Al día``.
    * An unfiled instance whose ``due_date`` is before the reference date is
      ``Vencido`` (overdue).
    * An unfiled instance due within ``upcoming_within_days`` (inclusive) of the
      reference date is ``Próximo`` (upcoming); the reference date itself counts.
    * Anything else (due further in the future) is ``Al día``.
    """
    if due_date is None:
        return DerivedObligationStatus.undated
    if submission_date is not None:
        return DerivedObligationStatus.on_track
    if due_date < reference_date:
        return DerivedObligationStatus.overdue
    if due_date <= reference_date + timedelta(days=upcoming_within_days):
        return DerivedObligationStatus.upcoming
    return DerivedObligationStatus.on_track


class ObligationsService:
    """Serve the firm's obligation catalog and per-project deadlines from BC."""

    def __init__(self, db: Session, bc_client: BusinessCentralClient):
        self.db = db
        self.bc_client = bc_client

    def list_catalog(self) -> list[ObligationTypeResponse]:
        """Return the obligation catalog (type, periodicity and due-date rule)."""
        return [
            ObligationTypeResponse(
                code=o.code,
                name=o.name,
                periodicity=o.periodicity,
                due_date_rule=o.due_date_rule,
            )
            for o in self.bc_client.get_obligations()
        ]

    def list_project_obligations(
        self,
        reference_date: date,
        status: DerivedObligationStatus | None = None,
        project_id: str | None = None,
        due_after: date | None = None,
        due_before: date | None = None,
        upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
    ) -> list[ProjectObligationResponse]:
        """Return per-project obligation instances, filtered and ordered by due date.

        ``status`` keeps only instances in that derived state; ``project_id``
        restricts to a single project; ``due_after`` / ``due_before`` bound the
        due date (both inclusive). Filters compose. Results are ordered by
        ``due_date`` ascending, with undated (``due_date is None``) instances
        sorted last. Undated instances never match a ``due_after`` / ``due_before``
        bound.
        """
        obligations_by_id = {o.id: o for o in self.bc_client.get_obligations()}
        projects_by_id = {p.id: p for p in self.bc_client.get_projects()}
        customer_names = {c.id: c.name for c in self.bc_client.get_customers()}

        instances = self.bc_client.get_project_obligations()
        if project_id is not None:
            instances = [i for i in instances if i.project_id == project_id]
        if due_after is not None:
            instances = [
                i for i in instances
                if i.due_date is not None and i.due_date >= due_after
            ]
        if due_before is not None:
            instances = [
                i for i in instances
                if i.due_date is not None and i.due_date <= due_before
            ]

        responses = [
            self._to_response(
                instance,
                reference_date,
                obligations_by_id,
                projects_by_id,
                customer_names,
                upcoming_within_days,
            )
            for instance in instances
        ]

        if status is not None:
            responses = [r for r in responses if r.status is status]

        # Undated instances have no due date to sort on; keep them last.
        responses.sort(key=lambda r: (r.due_date is None, r.due_date or date.min))
        return responses

    @staticmethod
    def _to_response(
        instance: BCProjectObligation,
        reference_date: date,
        obligations_by_id: dict[str, BCObligation],
        projects_by_id: dict[str, BCProject],
        customer_names: dict[str, str],
        upcoming_within_days: int,
    ) -> ProjectObligationResponse:
        """Map a BC project-obligation DTO to the API response shape."""
        obligation = obligations_by_id.get(instance.obligation_id)
        project = projects_by_id.get(instance.project_id)
        client_id = project.customer_id if project is not None else ""
        return ProjectObligationResponse(
            id=instance.id,
            obligation=ObligationRef(
                code=obligation.code if obligation is not None else "",
                name=obligation.name if obligation is not None else "",
            ),
            project=EntityRef(
                id=instance.project_id,
                name=project.name if project is not None else "",
            ),
            client=EntityRef(id=client_id, name=customer_names.get(client_id, "")),
            subject=instance.subject,
            due_date=instance.due_date,
            submission_date=instance.submission_date,
            status=derive_status(
                instance.due_date,
                instance.submission_date,
                reference_date,
                upcoming_within_days,
            ),
        )
