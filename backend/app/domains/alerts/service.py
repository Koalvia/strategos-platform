"""Business logic for the Alerts domain.

:class:`AlertsService` owns the platform-native ``alerts`` table. Alerts are
created from BOPA matches by the analysis cronjob (see
:meth:`create_for_match`, called from
:mod:`app.domains.bopa.tasks`) and read/updated by the Alertas page and the
sidebar unread badge.

State is global (shared by all users): an alert carries a single ``status`` and
``user_id`` is left NULL to mean "for all users". Reads resolve each alert's
display fields from the linked :class:`~app.domains.bopa.models.BopaMatch` and
its document via an eager-loaded relationship.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.domains.bopa.models import BopaMatch

from .models import Alert, AlertStatus, AlertType
from .schemas import AlertPage, AlertResponse


class AlertsService:
    """Persist and serve the platform's alerts."""

    def __init__(self, db: Session):
        self.db = db

    def list_alerts(
        self,
        status: AlertStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AlertPage:
        """Return one page of alerts, newest first, optionally filtered by status.

        The linked BOPA match and its document are eager-loaded so the response's
        display fields (matched term, document title/date, source URL) resolve
        without a query per row.
        """
        query = self.db.query(Alert).options(
            joinedload(Alert.bopa_match).joinedload(BopaMatch.document)
        )
        if status is not None:
            query = query.filter(Alert.status == status)

        total = query.count()
        alerts = (
            query.order_by(Alert.created_at.desc(), Alert.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return AlertPage(
            items=[self._to_response(a) for a in alerts],
            total=total,
        )

    def unread_count(self) -> int:
        """Number of unread (``NEW``) alerts, for the sidebar badge."""
        return (
            self.db.query(Alert).filter(Alert.status == AlertStatus.NEW).count()
        )

    def update_status(self, alert_id: int, status: AlertStatus) -> AlertResponse:
        """Set an alert's lifecycle status, or raise 404 if it does not exist."""
        alert = self.db.query(Alert).filter(Alert.id == alert_id).first()
        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        alert.status = status
        self.db.commit()
        self.db.refresh(alert)
        return self._to_response(alert)

    def mark_all_read(self) -> int:
        """Mark every unread (``NEW``) alert as ``VIEWED``; return the count changed."""
        updated = (
            self.db.query(Alert)
            .filter(Alert.status == AlertStatus.NEW)
            .update(
                {Alert.status: AlertStatus.VIEWED}, synchronize_session=False
            )
        )
        self.db.commit()
        return updated

    def create_for_match(self, match: BopaMatch) -> Alert | None:
        """Create the alert for a BOPA match, or return the existing one.

        Idempotent: the ``uq_alert_bopa_match`` unique constraint allows only one
        alert per match, so this is safe to call repeatedly (e.g. on a cronjob
        re-run). ``user_id`` is left NULL — the alert is for all users. The caller
        is responsible for committing; ``match.id`` must already be assigned
        (flush the match first).
        """
        existing = (
            self.db.query(Alert)
            .filter(Alert.bopa_match_id == match.id)
            .first()
        )
        if existing is not None:
            return existing

        alert = Alert(
            user_id=None,
            customer_id=match.customer_id,
            alert_type=AlertType.BOPA,
            bopa_match_id=match.id,
            status=AlertStatus.NEW,
        )
        self.db.add(alert)
        return alert

    def create_for_obligation(
        self,
        bc_obligation_id: str,
        customer_id: str,
        title: str,
        message: str,
    ) -> Alert:
        """Build and stage an OBLIGATION alert (the caller commits).

        This performs **no** idempotency query on purpose: the daily task guards
        duplicates with an in-memory set built from a single bulk read, and the
        ``uq_alert_bc_obligation`` unique constraint is the strict DB-level
        backstop. ``user_id`` is left NULL — the alert is for all users.
        """
        alert = Alert(
            user_id=None,
            customer_id=customer_id,
            alert_type=AlertType.OBLIGATION,
            bc_obligation_id=bc_obligation_id,
            title=title,
            message=message,
            status=AlertStatus.NEW,
        )
        self.db.add(alert)
        return alert

    @staticmethod
    def _to_response(alert: Alert) -> AlertResponse:
        """Map an alert to the API response shape.

        OBLIGATION alerts use their stored ``title``/``message``; BOPA alerts
        resolve display from the linked match/document and mirror it onto the
        unified ``title``/``message`` pair too.
        """
        if alert.alert_type is AlertType.OBLIGATION:
            return AlertResponse(
                id=alert.id,
                customer_id=alert.customer_id,
                alert_type=alert.alert_type,
                status=alert.status,
                created_at=alert.created_at,
                title=alert.title,
                message=alert.message,
                matched_term=None,
                document_id=None,
                document_title=None,
                article_date=None,
                source_url=None,
            )

        match = alert.bopa_match
        document = match.document if match is not None else None
        matched_term = match.matched_term if match is not None else None
        document_title = document.title if document is not None else None
        return AlertResponse(
            id=alert.id,
            customer_id=alert.customer_id,
            alert_type=alert.alert_type,
            status=alert.status,
            created_at=alert.created_at,
            title=matched_term,
            message=document_title,
            matched_term=matched_term,
            document_id=document.id if document is not None else None,
            document_title=document_title,
            article_date=document.article_date if document is not None else None,
            source_url=document.source_url if document is not None else None,
        )
