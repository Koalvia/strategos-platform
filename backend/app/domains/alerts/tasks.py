"""Celery tasks for the Alerts domain.

Houses the daily task that turns Business Central obligations into alerts. Like
the BOPA tasks it runs outside FastAPI's request scope, so it builds its own DB
session (``SessionLocal``) and BC client (``get_business_central_client``) rather
than using ``Depends``.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import logger
from app.celery_app import celery
from app.core.dependencies import get_business_central_client
from app.db.session import SessionLocal

from .models import Alert, AlertStatus, AlertType
from .service import AlertsService
from .utils import should_generate_obligation_alert

# The firm operates in Andorra (CET/CEST); compute the calendar day there rather
# than in UTC so a task firing in the early UTC morning still uses the correct
# local date. Europe/Madrid shares Andorra's offset and DST rules.
_LOCAL_TZ = ZoneInfo("Europe/Madrid")

# Statuses an obligation alert can be auto-dismissed from (i.e. not yet archived).
_ACTIVE_STATUSES = (AlertStatus.NEW, AlertStatus.VIEWED)


@celery.task(name="alerts.generate_obligation_alerts")
def generate_obligation_alerts(reference_date: date | None = None):
    """Create alerts for due BC obligations and auto-dismiss completed ones.

    Runs daily. In one pass it:

    1. resolves today's date in the firm's local timezone (``reference_date`` is
       an override for tests/manual runs; the daily schedule passes nothing);
    2. fetches the current project-obligations (plus catalog/project/customer
       lookups) once;
    3. reads every existing OBLIGATION alert once and derives an in-memory set of
       already-alerted ``bc_obligation_id`` (O(1) idempotency, no per-row query);
    4. **reconciles state**: any active alert whose obligation now has a
       ``submission_date`` (filed in the ERP) is moved to ``DISCARDED`` so the
       inbox self-cleans;
    5. **creates** a ``NEW`` alert for each qualifying obligation not already in
       the set.
    """
    db = SessionLocal()
    try:
        if reference_date is None:
            reference_date = datetime.now(_LOCAL_TZ).date()
        bc_client = get_business_central_client()

        instances = bc_client.get_project_obligations()
        obligations_by_id = {o.id: o for o in bc_client.get_obligations()}
        projects_by_id = {p.id: p for p in bc_client.get_projects()}
        # Resolve names only for the customers referenced by these projects.
        # get_customer_names() is a scoped /customers read; get_customers()
        # would re-fetch every project company-wide (to compute
        # active_project_count) — a second full projects round-trip we don't need.
        customer_ids = [p.customer_id for p in projects_by_id.values()]
        customer_names = bc_client.get_customer_names(customer_ids)

        service = AlertsService(db)

        # Single bulk read of existing obligation alerts — no N+1 in the loop.
        existing_alerts = (
            db.query(Alert)
            .filter(Alert.alert_type == AlertType.OBLIGATION)
            .all()
        )
        existing_alert_ids = {
            a.bc_obligation_id for a in existing_alerts if a.bc_obligation_id
        }

        # State reconciliation: auto-dismiss alerts whose obligation is now filed.
        submission_by_id = {i.id: i.submission_date for i in instances}
        dismissed = 0
        for alert in existing_alerts:
            if alert.status not in _ACTIVE_STATUSES:
                continue
            if submission_by_id.get(alert.bc_obligation_id) is not None:
                alert.status = AlertStatus.DISCARDED
                dismissed += 1

        # Create alerts for newly-due obligations not already alerted.
        created = 0
        for instance in instances:
            if instance.id in existing_alert_ids:
                continue
            if not should_generate_obligation_alert(instance, reference_date):
                continue

            project = projects_by_id.get(instance.project_id)
            customer_id = project.customer_id if project is not None else ""
            obligation = obligations_by_id.get(instance.obligation_id)
            title = (
                obligation.name
                if obligation is not None and obligation.name
                else instance.obligation_id
            )
            project_name = project.name if project is not None else instance.project_id
            client_name = customer_names.get(customer_id, "")
            message = (
                f"{project_name} · {client_name} · "
                f"deadline {instance.fecha_notificacion.isoformat()}"
            )

            service.create_for_obligation(
                bc_obligation_id=instance.id,
                customer_id=customer_id,
                title=title,
                message=message,
            )
            # Guard against duplicates within this same run.
            existing_alert_ids.add(instance.id)
            created += 1

        db.commit()
        logger.info(
            "Obligation alerts: %s created, %s auto-dismissed (reference date %s)",
            created,
            dismissed,
            reference_date.isoformat(),
        )
    except Exception:
        db.rollback()
        logger.exception("Obligation alert generation failed")
        raise
    finally:
        db.close()
