"""Pydantic v2 schemas for the Alerts domain.

An alert is platform-native (stored locally). Its human-readable content depends
on the ``alert_type``: BOPA alerts resolve their display from the linked
:class:`~app.domains.bopa.models.BopaMatch` and its document (matched term,
document title/date, source URL); OBLIGATION alerts carry denormalized
``title``/``message`` written at creation. Both types also expose a unified
``title``/``message`` pair so the frontend can render either without extra
lookups. The service builds :class:`AlertResponse` from the ORM graph rather than
mapping straight from a single table, so this is a plain response model (not
``from_attributes``).
"""

from datetime import datetime

from pydantic import BaseModel

from .models import AlertStatus, AlertType


class AlertResponse(BaseModel):
    """An alert as shown in the Alertas page / notification badge."""

    id: int
    customer_id: str
    alert_type: AlertType
    status: AlertStatus
    created_at: datetime | None
    # Unified display fields: for BOPA these mirror matched_term / document_title;
    # for OBLIGATION they carry the stored obligation headline / detail.
    title: str | None
    message: str | None
    # BOPA-specific display fields (None for OBLIGATION alerts).
    matched_term: str | None
    document_id: int | None
    document_title: str | None
    article_date: datetime | None
    source_url: str | None


class AlertUpdate(BaseModel):
    """Request body to change an alert's lifecycle status."""

    status: AlertStatus


class AlertPage(BaseModel):
    """One page of alerts plus the total matching the filter."""

    items: list[AlertResponse]
    total: int


class UnreadCountResponse(BaseModel):
    """The number of unread (``NEW``) alerts, for the sidebar badge."""

    count: int
