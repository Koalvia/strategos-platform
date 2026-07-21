from fastapi import APIRouter

from app.api.health import router as health_router
from app.domains.alerts.router import router as alerts_router
from app.domains.auth.router import router as auth_router
from app.domains.bopa.router import router as bopa_router
from app.domains.customers.router import router as customers_router
from app.domains.dashboard.router import router as dashboard_router
from app.domains.dev.router import router as dev_router
from app.domains.obligations.router import router as obligations_router
from app.domains.projects.router import router as projects_router
from app.domains.tasks.router import router as tasks_router
from app.domains.users.router import router as users_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(alerts_router)
router.include_router(auth_router)
router.include_router(bopa_router)
router.include_router(customers_router)
router.include_router(dashboard_router)
router.include_router(dev_router)
router.include_router(projects_router)
router.include_router(obligations_router)
router.include_router(tasks_router)
router.include_router(users_router)
