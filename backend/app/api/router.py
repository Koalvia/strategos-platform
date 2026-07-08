from fastapi import APIRouter

from app.api.health import router as health_router
from app.domains.auth.router import router as auth_router
from app.domains.customers.router import router as customers_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(customers_router)
