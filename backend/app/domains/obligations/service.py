"""Business logic for the obligations (Obligaciones) domain.

The service reads obligations read-only from Business Central via the injected
:class:`~app.integrations.business_central.client.BusinessCentralClient` port
(never from fixtures directly). It exposes two things:

* the obligation **catalog** (``BCObligation`` DTOs mapped to
  :class:`~app.domains.obligations.schemas.ObligationTypeResponse``),
* the **per-project instances** (``BCProjectObligation`` DTOs), enriched with the
  obligation, project and client display names and a **derived** due state —
  either as the complete list (:meth:`ObligationsService.list_project_obligations`,
  which the dashboard widgets call in-process) or as one page inside the shared
  envelope (:meth:`ObligationsService.list_project_obligations_page`), and
* the distinct **projects that have obligations**
  (:meth:`ObligationsService.list_obligation_projects`), which is all the
  Obligaciones filter dropdown needs.

The due state is computed by the pure :func:`derive_status` helper against a
reference date supplied by the caller (the router injects the server date; tests
freeze it), so it can be asserted deterministically without patching the clock.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.pagination import build_paginated_response
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
    ProjectObligationPage,
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
        Filters compose. Results are ordered by ``due_date`` ascending, with undated
        (``due_date is None``) instances sorted last.

        **The order of the Business Central reads below is deliberate — do not
        reshuffle it.** The instance link table is read *first* because it is by
        far the cheapest read (measured at 0.09s against the live tenant) and it
        is the only one that says which projects and customers this response
        actually mentions.

        In particular, resolving client names goes through
        ``get_customer_names(ids)`` and **never** ``get_customers()``."""
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

        # Nothing survived the filters, so there are no names to resolve: return
        # before paying for the catalog, the projects and the customers.
        if not instances:
            return []

        obligations_by_id = {o.id: o for o in self.bc_client.get_obligations()}
        projects_by_id = {p.id: p for p in self.bc_client.get_projects()}
        customer_names = self._customer_names_for(instances, projects_by_id)

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

    def list_project_obligations_page(
        self,
        reference_date: date,
        status: DerivedObligationStatus | None = None,
        project_id: str | None = None,
        due_after: date | None = None,
        due_before: date | None = None,
        upcoming_within_days: int = DEFAULT_UPCOMING_WINDOW_DAYS,
        page: int = 1,
        page_size: int | None = None,
    ) -> ProjectObligationPage:
        """Return one page of per-project instances inside the shared envelope.

        Delegates the whole read to :meth:`list_project_obligations` and only then
        slices, so filtering, status derivation and ordering are identical to the
        unpaginated call *by construction* — the two cannot drift apart.

        ``page_size`` is optional, and that is load-bearing: omitting it means
        "give me everything in one page", which is what the callers that derive
        figures from the complete set need (the projects grid computes each card's
        next deadline from it, a project's detail screen lists all of its
        obligations). A default page size would have truncated both silently — no
        error, just cards missing a date. When it is omitted, ``page`` is
        meaningless and is normalised to 1.

        Note what this pagination does and does not buy. It bounds the JSON sent
        to the browser and gives the client an honest ``total_count`` for its
        pager. It does **not** bound the work upstream, because the page window is
        not pushed into Business Central — unlike the dashboard's billing table,
        which can pick its page from BC first because customers are ordered by a
        field BC slices natively. Here the ``status`` is *derived* against a
        request-scoped reference date (and "Al día" is a disjunction), so
        ``total_count`` has to be counted after derivation, which no BC ``$count``
        can express; and OData does not pin where nulls land in an ``$orderby``,
        while this endpoint's contract sorts undated instances last. What bounds
        the BC work is the read order in :meth:`list_project_obligations`, not the
        page window.
        """
        responses = self.list_project_obligations(
            reference_date=reference_date,
            status=status,
            project_id=project_id,
            due_after=due_after,
            due_before=due_before,
            upcoming_within_days=upcoming_within_days,
        )
        # Counted before slicing: this is the number the client could never know
        # from a bare list — how many matches exist behind the current page.
        total_count = len(responses)

        if page_size is None:
            # ``build_paginated_response`` clamps ``page_size`` to at least 1, and
            # 0 would break its ``ceil`` division, so an empty result reports
            # page_size 1 / total_pages 0.
            return build_paginated_response(responses, total_count, 1, max(total_count, 1))

        # A Python slice past the end yields an empty list rather than raising,
        # which is why asking for page 99 answers 200 with ``items: []``.
        start = (page - 1) * page_size
        return build_paginated_response(
            responses[start : start + page_size], total_count, page, page_size
        )

    def list_obligation_projects(self) -> list[EntityRef]:
        """Return the distinct projects that have at least one obligation.

        Exists so the Obligaciones screen's "Proyecto" dropdown has a cheap source
        of its options. It used to build them by downloading the *entire*
        obligation list a second time and de-duplicating the projects out of it,
        which doubled the cost of opening the screen; once the table is paginated
        that trick stops working anyway, because the options would shrink to
        whichever projects happened to be on the current page.

        Reads only the instance link table and the projects — no catalog, no
        customers. Projects whose row cannot be resolved keep an empty name rather
        than disappearing, matching :meth:`_to_response`'s tolerance: a live
        instance pointing at a missing project must still be selectable.
        """
        instances = self.bc_client.get_project_obligations()
        project_ids = sorted({i.project_id for i in instances if i.project_id})
        if not project_ids:
            return []

        projects_by_id = {p.id: p for p in self.bc_client.get_projects()}
        refs = [
            EntityRef(
                id=pid,
                name=projects_by_id[pid].name if pid in projects_by_id else "",
            )
            for pid in project_ids
        ]
        refs.sort(key=lambda r: (r.name, r.id))
        return refs

    def _customer_names_for(
        self,
        instances: list[BCProjectObligation],
        projects_by_id: dict[str, BCProject],
    ) -> dict[str, str]:
        """Resolve ``{customer_id: name}`` for just the customers these rows mention.

        The ids are collected from the projects the *instances* reference, not from
        every project read: scoping the customers read to a handful of ids is only
        cheaper than ``get_customers()`` while the id list stays small, and passing
        it every project's customer would defeat the point.

        Blank ``customer_id`` values are dropped — ``_map_project_row`` defaults a
        missing ``billToCustomerNo`` to ``""``, and sending it would add a wasted
        ``no eq ''`` clause to the query. ``_to_response`` already falls back to an
        empty display name for ids that resolve to nothing.
        """
        customer_ids = sorted(
            {
                projects_by_id[i.project_id].customer_id
                for i in instances
                if i.project_id in projects_by_id
                and projects_by_id[i.project_id].customer_id
            }
        )
        return self.bc_client.get_customer_names(customer_ids)

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
