"""HTTP routes for the BOPA domain.

Read endpoints serve what :meth:`BopaService.sync_latest` has persisted, plus a
manual ``POST /bopa/sync`` trigger that runs the sync synchronously (useful for
backfilling/testing before the daily schedule lands in a follow-up issue). Every
route requires a verified user (and the ``x-api-key`` gateway header, except
under ``TESTING=1``).
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_bopa_client
from app.db.session import get_db
from app.domains.alerts.tasks import generate_obligation_alerts
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.bopa.client import BopaClient

from .schemas import (
    BulletinDetail,
    BulletinSummary,
    DocumentDetail,
    DocumentFilterOptions,
    DocumentSearchPage,
    ScanResult,
    SyncResult,
)
from .service import BopaService
from .tasks import analyze_bopa_matches

router = APIRouter(prefix="/bopa", tags=["bopa"])


@router.get("/bulletins", response_model=list[BulletinSummary])
def list_bulletins(
    year: int | None = None,
    is_extra: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """List stored bulletins (most recently published first).

    Optional ``year`` / ``is_extra`` filters; ``limit`` / ``offset`` page the
    result.
    """
    service = BopaService(db, bopa_client)
    return service.list_bulletins(
        year=year, is_extra=is_extra, limit=limit, offset=offset
    )


@router.get("/bulletins/{year}/{num}", response_model=BulletinDetail)
def get_bulletin(
    year: int,
    num: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Return one bulletin with its documents (404 if unknown)."""
    service = BopaService(db, bopa_client)
    return service.get_bulletin(year, num)


@router.get("/documents", response_model=DocumentSearchPage)
def search_documents(
    q: str | None = None,
    organisme: str | None = None,
    tema: str | None = None,
    organisme_pare: str | None = None,
    tema_pare: str | None = None,
    year: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Search/filter stored documents across all bulletins.

    ``q`` substring-matches the title or the stored HTML body (case-insensitive);
    ``organisme`` / ``tema``
    / ``organisme_pare`` / ``tema_pare`` are exact-match facets; ``year`` filters by
    the owning bulletin; ``date_from`` / ``date_to`` bound ``article_date``.
    ``limit`` / ``offset`` page the result, which carries the total match count.
    """
    service = BopaService(db, bopa_client)
    return service.search_documents(
        q=q,
        organisme=organisme,
        tema=tema,
        organisme_pare=organisme_pare,
        tema_pare=tema_pare,
        year=year,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


# Registered before ``/documents/{document_id}`` so the literal ``filters`` path is
# not captured by the int path param (which would 422).
@router.get("/documents/filters", response_model=DocumentFilterOptions)
def get_document_filters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Return the sorted, deduplicated facet values for the document search."""
    service = BopaService(db, bopa_client)
    return service.get_document_filter_options()


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Return one document with its stored HTML body (404 if unknown)."""
    service = BopaService(db, bopa_client)
    return service.get_document(document_id)


@router.post("/sync", response_model=SyncResult)
def sync_bopa(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Manually run the BOPA sync synchronously and return what it persisted."""
    service = BopaService(db, bopa_client)
    return service.sync_latest()


@router.post("/scan", response_model=ScanResult)
def scan_bopa(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bopa_client: BopaClient = Depends(get_bopa_client),
):
    """Run the full BOPA scan on demand: sync, analyze matches, generate alerts.

    This is what the "Iniciar Escaneo" button triggers. It mirrors the pipeline
    that runs when a Celery worker starts (see ``app.celery_app``) and the
    ``scripts/run_bopa_pipeline`` helper, but runs **synchronously** in the
    request: there is no Celery result backend to poll, so running inline lets the
    caller get the refreshed state back in one round-trip. Every step is
    idempotent, so re-scanning only adds newly-published bulletins, newly-matched
    documents and newly-due obligation alerts.
    """
    service = BopaService(db, bopa_client)
    sync_result = service.sync_latest()
    matches_created = analyze_bopa_matches()
    generate_obligation_alerts()
    return ScanResult(
        bulletins_synced=sync_result.bulletins_synced,
        documents_synced=sync_result.documents_synced,
        documents_failed=sync_result.documents_failed,
        matches_created=matches_created,
    )
