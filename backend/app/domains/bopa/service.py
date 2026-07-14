"""Business logic for the BOPA domain.

:class:`BopaService` owns both halves of the domain:

* :meth:`sync_latest` — fetch the recent bulletins from the injected
  :class:`~app.integrations.bopa.client.BopaClient` and persist any that are not
  already stored. This is the single place all sync logic lives; both the manual
  ``POST /bopa/sync`` endpoint and (in a follow-up issue) the daily Celery task
  call it.
* The read helpers (:meth:`list_bulletins`, :meth:`get_bulletin`,
  :meth:`get_document`) that back the query endpoints.

A numbered BOPA issue is legally immutable once published, so a bulletin whose
row already exists is never re-fetched. One known limitation follows from that:
if a prior run crashed part-way through a bulletin (leaving fewer documents than
``total_document_count``), a later run skips it rather than completing it — see
the issue's Non-goals.
"""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import logger
from app.integrations.bopa.client import BopaClient
from app.integrations.bopa.models import BopaBulletinListItem

from .models import BopaBulletin, BopaDocument
from .schemas import (
    BulletinDetail,
    BulletinSummary,
    DocumentDetail,
    SyncResult,
)

# File types whose HTML body we fetch and store inline; everything else keeps
# only its reference URLs.
_HTML_FILE_TYPES = ("html", "htmlCopy")


class BopaService:
    """Persist and serve synced BOPA bulletins and documents."""

    def __init__(self, db: Session, bopa_client: BopaClient):
        self.db = db
        self.bopa_client = bopa_client

    def sync_latest(self) -> SyncResult:
        """Fetch recent bulletins and persist any not already stored.

        Idempotent: bulletins already present (matched on ``(year, num)``) are
        skipped, so calling this twice back-to-back creates no duplicate rows and
        performs no redundant document fetches. Each bulletin is committed on its
        own so a crash mid-catch-up keeps earlier bulletins' progress, and a
        single failing document download is logged and counted without aborting
        the rest of its bulletin.
        """
        # bopa.ad's own homepage queries with "tomorrow" so a bulletin published
        # today is never missed by the API's rolling window (see #48).
        reference_date = date.today() + timedelta(days=1)
        items = self.bopa_client.get_month_bulletins(reference_date)

        # The rolling window can repeat entries across calls — dedupe on
        # (year, num), keeping first occurrence.
        deduped: dict[tuple[int, int], BopaBulletinListItem] = {}
        for item in items:
            deduped.setdefault((item.year, item.num), item)

        existing = {
            (year, num)
            for year, num in self.db.query(
                BopaBulletin.year, BopaBulletin.num
            ).all()
        }

        bulletins_synced = 0
        documents_synced = 0
        documents_failed = 0

        for (year, num), item in sorted(deduped.items()):
            if (year, num) in existing:
                # A published issue is immutable — never re-synced once stored.
                continue

            page = self.bopa_client.get_documents_by_bopa(year, num)
            if page.total_count != len(page.documents):
                logger.warning(
                    "BOPA bulletin %s/%s totalCount=%s but %s documents returned",
                    year,
                    num,
                    page.total_count,
                    len(page.documents),
                )

            bulletin = BopaBulletin(
                year=year,
                num=num,
                is_extra=item.is_extra,
                published_at=item.published_at,
                total_document_count=page.total_count,
                sumari_pdf_url=self.bopa_client.build_sumari_pdf_url(year, num),
            )
            self.db.add(bulletin)
            self.db.flush()  # assign bulletin.id for the documents' FK

            for doc in page.documents:
                try:
                    html_content = None
                    if doc.file_type in _HTML_FILE_TYPES:
                        html_content = self.bopa_client.fetch_content(
                            doc.source_url
                        ).decode("utf-8")
                    self.db.add(
                        BopaDocument(
                            bulletin_id=bulletin.id,
                            document_name=doc.document_name,
                            file_type=doc.file_type,
                            organisme=doc.organisme,
                            organisme_pare=doc.organisme_pare,
                            tema=doc.tema,
                            tema_pare=doc.tema_pare,
                            title=doc.title,
                            article_date=doc.article_date,
                            source_url=doc.source_url,
                            pdf_url=self.bopa_client.build_pdf_url(
                                year, num, doc.document_name
                            ),
                            html_content=html_content,
                        )
                    )
                    documents_synced += 1
                except Exception:
                    # One bad document must not lose the rest of the bulletin.
                    logger.exception(
                        "Failed to fetch BOPA document %s", doc.document_name
                    )
                    documents_failed += 1
                    continue

            # Commit per bulletin, not one giant transaction: a crash part-way
            # through a multi-bulletin catch-up keeps earlier bulletins' progress.
            self.db.commit()
            existing.add((year, num))
            bulletins_synced += 1

        return SyncResult(
            bulletins_synced=bulletins_synced,
            documents_synced=documents_synced,
            documents_failed=documents_failed,
        )

    def list_bulletins(
        self,
        year: int | None = None,
        is_extra: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BulletinSummary]:
        """List stored bulletins, most recently published first.

        Optional ``year`` / ``is_extra`` filter the result; ``limit`` / ``offset``
        page it.
        """
        query = self.db.query(BopaBulletin)
        if year is not None:
            query = query.filter(BopaBulletin.year == year)
        if is_extra is not None:
            query = query.filter(BopaBulletin.is_extra == is_extra)
        bulletins = (
            query.order_by(BopaBulletin.published_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [BulletinSummary.model_validate(b) for b in bulletins]

    def get_bulletin(self, year: int, num: int) -> BulletinDetail:
        """Return one bulletin (with its documents) or raise 404."""
        bulletin = (
            self.db.query(BopaBulletin)
            .filter(BopaBulletin.year == year, BopaBulletin.num == num)
            .first()
        )
        if bulletin is None:
            raise HTTPException(status_code=404, detail="Bulletin not found")
        return BulletinDetail.model_validate(bulletin)

    def get_document(self, document_id: int) -> DocumentDetail:
        """Return one document (with its HTML body) or raise 404."""
        document = (
            self.db.query(BopaDocument)
            .filter(BopaDocument.id == document_id)
            .first()
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentDetail.model_validate(document)
