"""Run the BOPA + obligation pipeline once, synchronously, against the live DB.

The normal trigger for this work is Celery Beat (``bopa.sync_daily`` at 06:00 UTC,
``bopa.analyze_matches`` at 07:00, ``alerts.generate_obligation_alerts`` at 08:00 —
see ``app.celery_app``). This script runs the same three steps on demand so the
data appears immediately without waiting for the schedule — useful for local/dev
verification and first-time seeding of a fresh database. It honours
``BOPA_MODE`` / ``BUSINESS_CENTRAL_MODE`` from the environment (``mock`` by
default), so in mock mode it ingests the committed fixtures.

Run it from ``backend/``::

    python -m scripts.run_bopa_pipeline

or, against the docker-compose stack::

    docker compose exec app python -m scripts.run_bopa_pipeline

Each step is idempotent (see the individual tasks), so re-running it is safe: it
adds only newly-published bulletins, newly-matched documents and newly-due
obligation alerts.
"""

import sys
from pathlib import Path

# Add the backend directory to the path so ``app`` imports work when run directly.
script_dir = Path(__file__).parent
app_dir = script_dir.parent
sys.path.insert(0, str(app_dir))

from app import logger  # noqa: E402
from app.domains.alerts.tasks import generate_obligation_alerts  # noqa: E402
from app.domains.bopa.tasks import analyze_bopa_matches, sync_bopa_daily  # noqa: E402


def run_pipeline() -> None:
    """Run sync -> analyze -> obligation-alerts once, in order, in-process.

    The task functions are called directly (not ``.delay``), so they execute
    synchronously against the DB that ``SessionLocal`` is configured for — no
    Celery worker or broker is involved.
    """
    logger.info("BOPA pipeline: syncing latest bulletins...")
    sync_bopa_daily()

    logger.info("BOPA pipeline: analysing documents against customers...")
    analyze_bopa_matches()

    logger.info("BOPA pipeline: generating obligation alerts...")
    generate_obligation_alerts()

    logger.info("BOPA pipeline: done.")


if __name__ == "__main__":
    run_pipeline()
