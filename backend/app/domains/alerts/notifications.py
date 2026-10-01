"""Email delivery for alerts, via Resend, routed by customer assignment.

An alert is emailed to whoever may see its customer (the same visibility rule the
app uses): managers get everything, an employee only their assigned customers.
Each alert is emailed **once** (``Alert.email_sent_at`` is the dedup guard) and a
DISCARDED alert is never emailed. In test mode every message is redirected to a
single test mailbox with the real recipient noted, so the rollout can be validated
before writing to real employee inboxes.
"""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import logger
from app.core.config import settings
from app.core.email import EmailService
from app.core.visibility import project_owner_emails, users_by_key
from app.domains.alerts.models import (
    Alert,
    AlertCategory,
    AlertStatus,
    UserAlertPreference,
)
from app.domains.alerts.utils import alert_category
from app.domains.auth.models import User
from app.domains.settings.service import SettingsService
from app.integrations.business_central.client import BusinessCentralClient

# Template file and subject line per category.
_TEMPLATE_BY_CATEGORY = {
    AlertCategory.BOPA: ("alert_bopa.html", "Nueva publicación en el BOPA"),
    AlertCategory.DOCUMENT_EXPIRY: (
        "alert_document_expiry.html",
        "Caducidad de documento próxima",
    ),
    AlertCategory.IVA: ("alert_iva.html", "Presentación de IVA próxima"),
    AlertCategory.OBLIGATION: (
        "alert_obligation.html",
        "Vencimiento de obligación próximo",
    ),
    AlertCategory.TRAFFIC_CHANGE: (
        "alert_traffic_change.html",
        "Cambio en el semáforo de una obligación",
    ),
}


class _Routing:
    """Reverse of the visibility scope: customer id -> recipient emails.

    Built from a single read of ``resources``/``customersResources`` so a whole
    dispatch pass costs two Business Central reads, not two per alert. Mirrors
    ``app.core.visibility``: a blank resource email never matches, and any card
    with ``manage_all_customers`` is a manager who receives every alert.
    """

    def __init__(self, bc_client: BusinessCentralClient):
        self._bc = bc_client
        resources = bc_client.get_resources()
        email_by_resource = {
            r.id: (r.email or "").strip().casefold()
            for r in resources
            if (r.email or "").strip()
        }
        self._manager_emails = {
            email_by_resource[r.id]
            for r in resources
            if r.manage_all_customers and r.id in email_by_resource
        }
        self._emails_by_customer: dict[str, set[str]] = defaultdict(set)
        for assignment in bc_client.get_customer_resources():
            email = email_by_resource.get(assignment.resource_id)
            if email and assignment.customer_id:
                self._emails_by_customer[assignment.customer_id].add(email)
        # Project maps for traffic-light routing are built lazily on first use, so a
        # dispatch with no TRAFFIC_CHANGE alerts pays nothing for them.
        self._traffic_ready = False
        self._projects_by_id: dict = {}
        self._users_by_key: dict = {}

    def emails_for(self, customer_id: str) -> set[str]:
        return self._manager_emails | self._emails_by_customer.get(customer_id, set())

    def _ensure_traffic_maps(self) -> None:
        if self._traffic_ready:
            return
        self._projects_by_id = {p.id: p for p in self._bc.get_projects()}
        self._users_by_key = users_by_key(self._bc.get_users())
        self._traffic_ready = True

    def traffic_emails(
        self, project_id: str | None, include_manager: bool
    ) -> set[str] | None:
        """Recipients for a traffic-light alert: the project's technician + responsible.

        Adds the manager emails only when ``include_manager``. Returns ``None`` if the
        project cannot be resolved, so the caller can fall back.
        """
        self._ensure_traffic_maps()
        project = self._projects_by_id.get(project_id) if project_id else None
        if project is None:
            return None
        emails = set(project_owner_emails(project, self._users_by_key))
        if include_manager:
            emails |= self._manager_emails
        return emails


def dispatch_pending_alert_emails(db: Session, bc_client: BusinessCentralClient) -> int:
    """Email every not-yet-emailed, non-discarded alert. Returns how many were sent.

    Idempotent: an alert with ``email_sent_at`` set is skipped, so re-running the
    daily task never resends. Recipients are gated by their per-category
    preference (default on).
    """
    if not settings.ALERT_EMAIL_ENABLED:
        return 0
    if settings.ALERT_EMAIL_TEST_MODE and not settings.ALERT_EMAIL_TEST_RECIPIENT:
        logger.error(
            "ALERT_EMAIL_TEST_MODE is on but ALERT_EMAIL_TEST_RECIPIENT is blank; "
            "refusing to send so alerts are not fanned out to an unintended inbox."
        )
        return 0

    pending = (
        db.query(Alert)
        .filter(Alert.status != AlertStatus.DISCARDED, Alert.email_sent_at.is_(None))
        .all()
    )
    if not pending:
        return 0

    routing = _Routing(bc_client)
    notify_manager = SettingsService(db).get_traffic_light().notify_manager_on_change
    users_by_email = {
        (u.email or "").casefold(): u
        for u in db.query(User).filter(User.is_verified.is_(True)).all()
    }
    disabled = {
        (p.user_id, p.category)
        for p in db.query(UserAlertPreference).filter(
            UserAlertPreference.email_enabled.is_(False)
        )
    }

    sent = 0
    for alert in pending:
        category = alert_category(
            alert.alert_type, alert.obligation_code, alert.category
        )
        # Traffic-light alerts go to the project's technician + responsible (and the
        # manager only if the director opted in); everything else routes by customer.
        recipient_emails = None
        if category == AlertCategory.TRAFFIC_CHANGE:
            recipient_emails = routing.traffic_emails(
                alert.bc_project_id, notify_manager
            )
        if recipient_emails is None:
            recipient_emails = routing.emails_for(alert.customer_id)
        if not recipient_emails:
            logger.warning(
                "Alert %s (customer %s) has no email recipient; marking as sent.",
                alert.id,
                alert.customer_id,
            )
        for email in recipient_emails:
            user = users_by_email.get(email)
            if user is None:
                continue  # BC contact with no app account — do not email
            if (user.id, category) in disabled:
                continue  # opted out of this category
            if _send_one(alert, user, category):
                sent += 1
        # Mark as emailed even if no recipient matched, so we do not re-scan it.
        alert.email_sent_at = datetime.now(timezone.utc)

    db.commit()
    logger.info("Alert emails: %s message(s) sent for %s alert(s)", sent, len(pending))
    return sent


def _send_one(alert: Alert, user: User, category: AlertCategory) -> bool:
    """Render and send one alert email to one recipient (test-mode aware).

    Returns whether the send succeeded, so the caller counts delivered messages
    rather than attempts.
    """
    template_name, subject = _TEMPLATE_BY_CATEGORY[category]
    real_recipient = user.email
    context = {
        "recipient_name": user.name,
        "title": alert.title or "",
        "message": alert.message or "",
        "customer_id": alert.customer_id,
        "app_url": settings.FRONTEND_URL,
        "test_mode": settings.ALERT_EMAIL_TEST_MODE,
        "real_recipient": real_recipient,
    }
    html = EmailService.render_template(template_name, context)

    if settings.ALERT_EMAIL_TEST_MODE:
        to_email = settings.ALERT_EMAIL_TEST_RECIPIENT
        subject = f"[PRUEBA · destinatario real: {real_recipient}] {subject}"
    else:
        to_email = real_recipient

    try:
        EmailService.send_email(to_email=to_email, subject=subject, html_content=html)
        return True
    except Exception:
        # One bad send must not abort the batch or block the dedup mark.
        logger.exception("Failed to send alert email to %s", to_email)
        return False
