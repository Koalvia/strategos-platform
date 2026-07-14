"""Celery tasks for the BOPA domain."""
from app import logger
from app.celery_app import celery
from app.core.dependencies import get_bopa_client
from app.db.session import SessionLocal

from .service import BopaService


@celery.task(name="bopa.sync_daily")
def sync_bopa_daily():
    """Sync the latest BOPA bulletins once a day (Celery Beat entry).

    Runs outside FastAPI's request scope, so the DB session and BOPA client are
    built directly here rather than injected via ``Depends``.
    """
    db = SessionLocal()
    try:
        service = BopaService(db=db, bopa_client=get_bopa_client())
        result = service.sync_latest()
        logger.info(
            f"BOPA sync: {result.bulletins_synced} bulletins, "
            f"{result.documents_synced} documents "
            f"({result.documents_failed} failed)"
        )
    finally:
        db.close()
