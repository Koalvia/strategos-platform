import os

import sentry_sdk
from celery import Celery, chain
from celery.schedules import crontab
from celery.signals import worker_ready

from app import logger
from app.core.config import settings

# Initialize Sentry for Celery worker (if configured and not testing)
if settings.SENTRY_DSN and os.environ.get("TESTING") != "1":
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        send_default_pii=True,
        traces_sample_rate=getattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.0),
        profiles_sample_rate=getattr(settings, "SENTRY_PROFILES_SAMPLE_RATE", 0.0),
    )


# Configure Celery based on environment
if os.environ.get("TESTING") == "1":
    # Use eager mode for testing - tasks execute synchronously without Redis
    celery = Celery("strategos-celery", broker="memory://")
    celery.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
        broker_connection_retry_on_startup=False,
    )
else:
    # Normal mode for production
    celery = Celery("strategos-celery", broker=settings.REDIS_URL)

# Auto-discover tasks in domain modules
# Add task modules here as you create them
celery.autodiscover_tasks(
    [
        "app.domains.auth.tasks",
        "app.domains.bopa.tasks",
        "app.domains.alerts.tasks",
    ]
)

# Periodic tasks (Celery Beat)
celery.conf.beat_schedule = {
    "bopa-sync-daily": {
        "task": "bopa.sync_daily",
        # 06:00 UTC ≈ 07:00-08:00 Andorra local time depending on DST —
        # comfortably after BOPA's own midnight-anchored regular-issue publish.
        "schedule": crontab(hour=6, minute=0),
    },
    "bopa-analyze-daily": {
        "task": "bopa.analyze_matches",
        # 07:00 UTC — 1 hour after sync completes, analyzes new bulletins against
        # customers and projects from Business Central, stores matches in BopaMatch.
        "schedule": crontab(hour=7, minute=0),
    },
    "obligations-generate-alerts-daily": {
        "task": "alerts.generate_obligation_alerts",
        # 08:00 UTC — after the BOPA jobs; turns due BC obligations into alerts and
        # auto-dismisses ones already filed in the ERP.
        "schedule": crontab(hour=8, minute=0),
    },
}


# Short-lived Redis lock so only the first worker in the window queues the
# startup pipeline. ``worker_ready`` fires once per worker process, so a
# multi-process (``--concurrency`` with prefork) or multi-replica deployment
# would otherwise queue N identical chains on every restart. The TTL is small
# enough that a genuinely later restart still re-queues.
_STARTUP_LOCK_KEY = "bopa:startup-pipeline-lock"
_STARTUP_LOCK_TTL = 300  # seconds


def _claim_startup_run() -> bool:
    """Return True if this process should queue the startup pipeline.

    Testing runs Celery eagerly with no Redis, and the guard is irrelevant there,
    so it always claims. In production a ``SET NX EX`` lets only the first worker
    in the TTL window win. Fails **open**: if Redis is unreachable we still queue
    rather than silently skip the pipeline.
    """
    if os.environ.get("TESTING") == "1":
        return True
    try:
        import redis

        client = redis.from_url(settings.REDIS_URL)
        return bool(
            client.set(_STARTUP_LOCK_KEY, "1", nx=True, ex=_STARTUP_LOCK_TTL)
        )
    except Exception:  # noqa: BLE001 - never let lock trouble block the pipeline
        logger.warning("Startup pipeline lock unavailable; queuing without it.")
        return True


@worker_ready.connect
def run_bopa_pipeline_on_startup(sender=None, **kwargs):
    """Run the full BOPA scan when the first worker becomes ready.

    Mirrors the manual "Iniciar Escaneo" button (and ``scripts/run_bopa_pipeline``):
    sync the latest bulletins, analyze them against customers/projects to produce
    ``BopaMatch`` rows, then generate obligation alerts. The three steps run as a
    chain of immutable signatures (``.si``-style) so they execute in order on the
    worker without passing results between them, and without blocking startup.
    Every step is idempotent — it only touches newly-published bulletins,
    newly-matched documents and newly-due obligations — so firing it on every
    restart is safe; a Redis lock (see ``_claim_startup_run``) keeps a
    multi-worker deployment from queuing the chain more than once per restart.
    """
    if not _claim_startup_run():
        logger.info(
            "Worker ready: BOPA pipeline already queued by another worker; skipping."
        )
        return
    chain(
        celery.signature("bopa.sync_daily", immutable=True),
        celery.signature("bopa.analyze_matches", immutable=True),
        celery.signature("alerts.generate_obligation_alerts", immutable=True),
    ).apply_async()
    logger.info("Worker ready: queued BOPA pipeline (sync -> analyze -> alerts).")
