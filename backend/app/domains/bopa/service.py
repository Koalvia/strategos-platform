"""Business logic for the BOPA domain.

:class:`BopaService` owns both halves of the domain:

* :meth:`sync_latest` — fetch the recent bulletins from the injected
  :class:`~app.integrations.bopa.client.BopaClient` and persist any that are not
  already stored. This is the single place all sync logic lives; both the manual
  ``POST /bopa/sync`` endpoint and (in a follow-up issue) the daily Celery task
  call it.
* The read helpers (:meth:`list_bulletins`, :meth:`get_bulletin`,
  :meth:`get_document`) that back the query endpoints.

A numbered BOPA issue is legally immutable once published, so its bulletin row is
written once and never rewritten. A bulletin that is already complete (its stored
``document_count`` has reached ``total_document_count``) is skipped without any
API call. A bulletin that is short — e.g. because a prior run lost documents to a
transient fetch/decode failure (see #69) — is revisited: only the missing
documents are inserted, guarded by the ``(bulletin_id, document_name)`` unique
constraint so re-runs stay idempotent.
"""

from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, contains_eager

from app import logger
from app.integrations.bopa.client import BopaClient
from app.integrations.bopa.models import BopaBulletinListItem

from .models import BopaBulletin, BopaDocument
from .schemas import (
    BulletinDetail,
    BulletinSummary,
    DocumentDetail,
    DocumentFilterOptions,
    DocumentSearchPage,
    DocumentSummary,
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
        """Fetch recent bulletins and persist new or missing documents.

        Idempotent: a bulletin already stored and complete (its ``document_count``
        has reached ``total_document_count``) is skipped without any API call, so
        calling this twice back-to-back creates no duplicate rows. A bulletin that
        is short — a prior run lost documents to a transient fetch/decode failure
        (see #69) — is revisited and only its missing documents are inserted; the
        bulletin row itself is not recreated, so such a backfill does not count as
        a new ``bulletins_synced``. Each bulletin is committed on its own so a
        crash mid-catch-up keeps earlier bulletins' progress, and a single failing
        document download is logged and counted without aborting the rest.
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
            (b.year, b.num): b for b in self.db.query(BopaBulletin).all()
        }

        bulletins_synced = 0
        documents_synced = 0
        documents_failed = 0

        for (year, num), item in sorted(deduped.items()):
            stored = existing.get((year, num))
            if stored is not None:
                # Immutable issue: the row stays, but a prior run may have stored
                # fewer documents than the issue has (#69). Backfill only the
                # shortfall; a bulletin already complete needs no API call. The
                # "totalCount can exceed documents returned" quirk means such a
                # bulletin stays perennially short and is re-listed each run, but
                # the per-name skip below keeps that a cheap no-op.
                if stored.document_count >= stored.total_document_count:
                    continue
                page = self.bopa_client.get_documents_by_bopa(year, num)
                present = {doc.document_name for doc in stored.documents}
                synced, failed = self._persist_documents(
                    stored, year, num, page.documents, skip_names=present
                )
                self.db.commit()
                documents_synced += synced
                documents_failed += failed
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

            synced, failed = self._persist_documents(
                bulletin, year, num, page.documents, skip_names=set()
            )
            documents_synced += synced
            documents_failed += failed

            # Commit per bulletin, not one giant transaction: a crash part-way
            # through a multi-bulletin catch-up keeps earlier bulletins' progress.
            self.db.commit()
            existing[(year, num)] = bulletin
            bulletins_synced += 1

        return SyncResult(
            bulletins_synced=bulletins_synced,
            documents_synced=documents_synced,
            documents_failed=documents_failed,
        )

    def _persist_documents(
        self,
        bulletin: BopaBulletin,
        year: int,
        num: int,
        documents,
        *,
        skip_names: set[str],
    ) -> tuple[int, int]:
        """Insert each document not already present, returning (synced, failed).

        Shared by the new-bulletin and backfill paths. ``skip_names`` holds the
        ``document_name``s already stored for the bulletin (empty for a brand-new
        one); those are left untouched so re-runs neither re-fetch nor duplicate
        them. A single document that fails to download/decode is logged and
        counted without aborting the rest of the bulletin.
        """
        synced = 0
        failed = 0
        for doc in documents:
            if doc.document_name in skip_names:
                continue
            try:
                html_content = None
                if doc.file_type in _HTML_FILE_TYPES:
                    html_content = self._decode_html(
                        self.bopa_client.fetch_content(doc.source_url)
                    )
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
                synced += 1
            except Exception:
                # One bad document must not lose the rest of the bulletin.
                logger.exception(
                    "Failed to fetch BOPA document %s", doc.document_name
                )
                failed += 1
                continue
        return synced, failed

    @staticmethod
    def _decode_html(content: bytes) -> str:
        """Decode a fetched HTML body, tolerating BOPA's UTF-16 exports.

        Most bodies are UTF-8, but a subset of BOPA's own Windows/Word-style HTML
        exports are served as UTF-16-with-BOM (see #69); Python's ``utf-16`` codec
        auto-detects and strips the BOM in either byte order, so no manual BOM
        sniffing is needed. A body that decodes as neither raises and is handled
        by the caller's per-document ``except`` (logged + counted, still skips
        only that one document).
        """
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("utf-16")

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

    def search_documents(
        self,
        *,
        q: str | None = None,
        organisme: str | None = None,
        tema: str | None = None,
        organisme_pare: str | None = None,
        tema_pare: str | None = None,
        year: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentSearchPage:
        """Search/filter stored documents across all bulletins, most recent first.

        ``q`` is a case-insensitive substring match on the ``title`` **or** the
        stored HTML body (``html_content``), so a term appearing only in an
        article's body still matches; the metadata facets are exact-match equality
        when given; ``year`` filters via the bulletin join; ``date_from`` /
        ``date_to`` inclusively bound ``article_date``. Every row carries its
        bulletin's ``year`` / ``num`` — the bulletin is joined once (and
        eager-loaded) rather than queried per row.
        """
        query = (
            self.db.query(BopaDocument)
            .join(BopaDocument.bulletin)
            .options(contains_eager(BopaDocument.bulletin))
        )
        if q:
            # ``html_content`` is NULL for non-HTML (PDF-only) documents; ILIKE on
            # NULL yields NULL, which never matches inside the OR, so those still
            # match on title alone.
            escaped_q = q.replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped_q}%"

            query = query.filter(
                or_(
                    BopaDocument.title.ilike(like, escape="\\"),
                    BopaDocument.html_content.ilike(like, escape="\\"),
                )
            )
        if organisme is not None:
            query = query.filter(BopaDocument.organisme == organisme)
        if tema is not None:
            query = query.filter(BopaDocument.tema == tema)
        if organisme_pare is not None:
            query = query.filter(BopaDocument.organisme_pare == organisme_pare)
        if tema_pare is not None:
            query = query.filter(BopaDocument.tema_pare == tema_pare)
        if year is not None:
            query = query.filter(BopaBulletin.year == year)
        if date_from is not None:
            query = query.filter(BopaDocument.article_date >= date_from)
        if date_to is not None:
            # Upper bound is inclusive of the whole ``date_to`` day even though
            # ``article_date`` carries a time component.
            query = query.filter(
                BopaDocument.article_date < date_to + timedelta(days=1)
            )

        total = query.count()
        documents = (
            query.order_by(
                BopaDocument.article_date.desc(), BopaDocument.id.desc()
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
        return DocumentSearchPage(
            items=[DocumentSummary.model_validate(d) for d in documents],
            total=total,
        )

    def get_document_filter_options(self) -> DocumentFilterOptions:
        """Return the sorted, deduplicated values available for each facet."""

        def distinct_values(column) -> list[str]:
            rows = self.db.query(column).distinct().order_by(column).all()
            return [value for (value,) in rows if value is not None]

        return DocumentFilterOptions(
            organisme=distinct_values(BopaDocument.organisme),
            tema=distinct_values(BopaDocument.tema),
            organisme_pare=distinct_values(BopaDocument.organisme_pare),
            tema_pare=distinct_values(BopaDocument.tema_pare),
        )

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
