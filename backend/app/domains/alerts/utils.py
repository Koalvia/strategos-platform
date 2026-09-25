"""Pure business logic for the Alerts domain.

These helpers are deliberately free of database and clock I/O so they can be
unit-tested by passing plain values. In particular the obligation-alert rule
takes an explicit ``reference_date`` — it never calls ``date.today()`` — so the
daily task stays the single source of "today" (a timezone-aware local date, see
:mod:`app.domains.alerts.tasks`).
"""

from datetime import date, timedelta

from app.domains.alerts.models import AlertCategory, AlertType
from app.domains.obligations.schemas import DerivedObligationStatus
from app.integrations.business_central.models import BCProjectObligation

# How many days before its due date an obligation should notify, by BC code.
# Documents (DNI/passport) need a long lead to renew; fiscal filings a short one.
_LEAD_DAYS_BY_CODE = {"DNI": 60, "PASSAPORT": 60}
_DEFAULT_LEAD_DAYS = 15

# BC obligation codes that map to their own email category.
_DOCUMENT_CODES = {"DNI", "PASSAPORT"}


def lead_days_for(obligation_code: str | None) -> int:
    """Days before the due date to notify for this obligation code."""
    return _LEAD_DAYS_BY_CODE.get((obligation_code or "").upper(), _DEFAULT_LEAD_DAYS)


def alert_category(
    alert_type: AlertType,
    obligation_code: str | None,
    stored_category: AlertCategory | None = None,
) -> AlertCategory:
    """Map an alert to its email category (template + user preference key).

    A ``stored_category`` set on the alert row wins: colour-change alerts reuse
    ``AlertType.OBLIGATION`` yet must route as ``TRAFFIC_CHANGE``, which cannot be
    derived from the BC obligation code. When it is ``None`` (BOPA and one-per-life
    obligation alerts) the category is derived from the type and code as before.
    """
    if stored_category is not None:
        return stored_category
    if alert_type is AlertType.BOPA:
        return AlertCategory.BOPA
    code = (obligation_code or "").upper()
    if code in _DOCUMENT_CODES:
        return AlertCategory.DOCUMENT_EXPIRY
    if code == "IVA":
        return AlertCategory.IVA
    return AlertCategory.OBLIGATION


# Ascending traffic-light severity. ``Sin fecha`` (undated) is deliberately absent:
# it is off-scale, so transitions into or out of it are never a worsening.
_TRAFFIC_SEVERITY = {
    DerivedObligationStatus.on_track: 0,   # Al día  (green)
    DerivedObligationStatus.upcoming: 1,   # Próximo (yellow)
    DerivedObligationStatus.urgent: 2,     # Urgente (red)
    DerivedObligationStatus.overdue: 3,    # Vencido (red, overdue)
}


def is_traffic_worsening(
    previous: DerivedObligationStatus, current: DerivedObligationStatus
) -> bool:
    """Whether ``current`` is a strictly worse traffic-light state than ``previous``.

    A worsening is a move to a strictly higher severity on the
    ``Al día < Próximo < Urgente < Vencido`` scale (so ``Urgente`` -> ``Vencido``
    counts). ``Sin fecha`` is off-scale: any transition into or out of it is never a
    worsening, so it never emails.
    """
    prev = _TRAFFIC_SEVERITY.get(previous)
    curr = _TRAFFIC_SEVERITY.get(current)
    if prev is None or curr is None:
        return False
    return curr > prev


def obligation_notification_date(
    obligation: BCProjectObligation,
) -> date | None:
    """When an obligation should notify.

    BC's own ``fecha_notificacion`` wins when present; otherwise it is derived as
    ``due_date - lead_days`` (BC does not populate a notification date yet). Returns
    ``None`` when neither is available.
    """
    if obligation.fecha_notificacion is not None:
        return obligation.fecha_notificacion
    if obligation.due_date is None:
        return None
    return obligation.due_date - timedelta(days=lead_days_for(obligation.obligation_id))


def should_generate_obligation_alert(
    obligation: BCProjectObligation, reference_date: date
) -> bool:
    """Return whether a BC obligation warrants an alert on ``reference_date``.

    An obligation qualifies when **all** of the following hold:

    * ``subject`` is ``True`` — the project is liable for this obligation;
    * ``submission_date`` is ``None`` — it has not been filed yet;
    * its notification date (BC's own, or derived ``due_date - lead_days``) has
      arrived (``<=`` gives catch-up; the task's idempotency check ensures one
      alert ever).

    This function performs no I/O and does not read the clock: ``reference_date``
    is required and supplied by the caller.
    """
    if not obligation.subject:
        return False
    if obligation.submission_date is not None:
        return False
    notify_on = obligation_notification_date(obligation)
    if notify_on is None:
        return False
    return notify_on <= reference_date
