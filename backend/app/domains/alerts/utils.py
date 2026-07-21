"""Pure business logic for the Alerts domain.

These helpers are deliberately free of database and clock I/O so they can be
unit-tested by passing plain values. In particular the obligation-alert rule
takes an explicit ``reference_date`` — it never calls ``date.today()`` — so the
daily task stays the single source of "today" (a timezone-aware local date, see
:mod:`app.domains.alerts.tasks`).
"""

from datetime import date

from app.integrations.business_central.models import BCProjectObligation


def should_generate_obligation_alert(
    obligation: BCProjectObligation, reference_date: date
) -> bool:
    """Return whether a BC obligation warrants an alert on ``reference_date``.

    An obligation qualifies when **all** of the following hold:

    * ``subject`` is ``True`` — the project is liable for this obligation;
    * ``submission_date`` is ``None`` — it has not been filed yet;
    * ``fecha_notificacion`` is set and is on or before ``reference_date`` — its
      notification date has arrived (``<=`` gives catch-up: a day the task missed
      still fires; the task's idempotency check ensures only one alert ever).

    This function performs no I/O and does not read the clock: ``reference_date``
    is required and supplied by the caller. The "has an alert already been
    created for this obligation" check is intentionally **not** here — that is
    database state, handled by the task.
    """
    if not obligation.subject:
        return False
    if obligation.submission_date is not None:
        return False
    if obligation.fecha_notificacion is None:
        return False
    return obligation.fecha_notificacion <= reference_date
