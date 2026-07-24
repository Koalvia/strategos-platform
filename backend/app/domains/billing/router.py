"""HTTP routes for the billing (Facturación / Costes) domain.

Read-only: billing and cost figures are aggregated from Business Central, the
system of record. Every route requires a verified user (and the ``x-api-key``
gateway header, except under ``TESTING=1``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_business_central_client
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.integrations.business_central.client import BusinessCentralClient

from .schemas import CustomerBillingResponse, ProjectBillingResponse
from .service import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/by-customer", response_model=list[CustomerBillingResponse])
def billing_by_customer(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Net billing per customer (invoices minus credit memos), highest first."""
    service = BillingService(db, bc_client)
    return service.billing_by_customer()


@router.get("/by-project", response_model=list[ProjectBillingResponse])
def billing_by_project(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
    bc_client: BusinessCentralClient = Depends(get_business_central_client),
):
    """Net billing, usage cost and logged hours per project, highest billing first."""
    service = BillingService(db, bc_client)
    return service.billing_by_project()
