"""HTTP routes for dev-only tooling.

These endpoints exist to make local development and integration testing easy;
they are disabled outside non-production environments (guarded on ``APP_ENV``).
Like every other ``/api`` route they sit behind the ``x-api-key`` gateway and
require a verified user (both are bypassed under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user

from .schemas import MockPipelineResult
from .service import run_mock_bopa_pipeline

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/run-mock-bopa-pipeline", response_model=MockPipelineResult)
def run_mock_pipeline(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    """Run the mock BOPA pipeline (sync -> analyze -> obligation alerts).

    Uses only committed fixtures — no external calls. Returns a count summary of
    what now exists in the database. Idempotent: re-running does not duplicate
    rows. Disabled in production.
    """
    if settings.APP_ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")
    return run_mock_bopa_pipeline(db, demo_states=True)
