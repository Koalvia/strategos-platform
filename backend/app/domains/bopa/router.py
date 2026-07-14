"""HTTP routes for the BOPA domain.

Read endpoints serve what :meth:`BopaService.sync_latest` has persisted, plus a
manual ``POST /bopa/sync`` trigger that runs the sync synchronously (useful for
backfilling/testing before the daily schedule lands in a follow-up issue). Every
route requires a verified user (and the ``x-api-key`` gateway header, except
under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_bopa_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.bopa.client import BopaClient

from .schemas import BulletinDetail, BulletinSummary, DocumentDetail, SyncResult
from .service import BopaService

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
