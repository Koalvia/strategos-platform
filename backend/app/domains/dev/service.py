"""Dev-only orchestration of the mock BOPA → Alerts pipeline.

This wires together the three existing pipeline stages so the whole flow can be
exercised locally with no external services, purely against committed fixtures:

1. **Ingest + persist** — :meth:`BopaService.sync_latest` run against a
   :class:`MockBopaClient` pointed at the crafted demo fixtures
   (:data:`DEMO_BULLETINS` / :data:`DEMO_DOCUMENTS`), whose document titles embed
   real Business Central customer/project names so the next stage finds matches.
2. **Analyze** — the ``bopa.analyze_matches`` task body reads the persisted
   documents plus the (mock) BC customers/projects, writes ``BopaMatch`` rows and
   creates BOPA/Client alerts.
3. **Obligation alerts** — the ``alerts.generate_obligation_alerts`` task body
   turns due BC obligations into Obligation alerts.

Every stage delegates to existing, unchanged code, so this adds no business logic
of its own. It is idempotent: sync skips already-complete bulletins, analysis
skips already-logged bulletins, and obligation-alert creation is guarded by a
unique constraint — so re-running leaves the counts unchanged.

The two task bodies open their own ``SessionLocal`` (they normally run outside a
request scope), so they operate on the configured database rather than the ``db``
session passed here; locally both point at the same database, so the summary read
back through ``db`` sees everything they committed.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.domains.alerts.models import Alert, AlertStatus, AlertType
from app.domains.alerts.tasks import generate_obligation_alerts
from app.domains.bopa.models import BopaMatch
from app.domains.bopa.service import BopaService
from app.domains.bopa.tasks import analyze_bopa_matches
from app.integrations.bopa.mock_client import MockBopaClient

from .schemas import MockPipelineResult

# Crafted demo fixtures (see app/integrations/bopa/fixtures/): one bulletin whose
# documents name specific BC customers/projects to deterministically trigger
# matches, plus one control document that matches nothing.
DEMO_BULLETINS = "pipeline_demo_bulletins.json"
DEMO_DOCUMENTS = "pipeline_demo_documents.json"


def run_mock_bopa_pipeline(
    db: Session,
    reference_date: date | None = None,
    demo_states: bool = False,
) -> MockPipelineResult:
    """Run the full mock BOPA pipeline and return a count summary.

    ``reference_date`` overrides "today" for obligation-alert generation (the
    daily task's default); pass a fixed date in tests so assertions do not depend
    on the wall clock.

    ``demo_states`` is a local-seeding convenience only: when ``True`` it moves a
    small, fixed subset of the generated alerts into the VIEWED and DISCARDED
    states so the Alertas UI shows content under all three tabs. It is idempotent
    and off by default (the pipeline's natural output is all-``NEW``); the CLI and
    the dev endpoint enable it, tests of the pure pipeline leave it off.
    """
    # 1. Ingest + persist synthetic BOPA through the real sync/persistence path.
    client = MockBopaClient(
        bulletins_fixture=DEMO_BULLETINS, documents_fixture=DEMO_DOCUMENTS
    )
    sync = BopaService(db, client).sync_latest()

    # 2. Analyze persisted documents -> BopaMatch rows + BOPA/Client alerts.
    analyze_bopa_matches()

    # 3. Due BC obligations -> Obligation alerts.
    generate_obligation_alerts(reference_date=reference_date)

    if demo_states:
        _apply_demo_states(db)

    # 4. Summarize from the database. Expire first so counts reflect rows the task
    #    bodies committed on their own sessions rather than this session's cache.
    db.expire_all()
    return MockPipelineResult(
        bulletins_synced=sync.bulletins_synced,
        documents_synced=sync.documents_synced,
        bopa_matches=db.query(BopaMatch).count(),
        bopa_alerts=(
            db.query(Alert).filter(Alert.alert_type == AlertType.BOPA).count()
        ),
        obligation_alerts=(
            db.query(Alert)
            .filter(Alert.alert_type == AlertType.OBLIGATION)
            .count()
        ),
    )


def _apply_demo_states(db: Session) -> None:
    """Move a fixed subset of demo alerts into VIEWED/DISCARDED (local seed only).

    Targets specific alerts by stable business key (customer / obligation id), not
    by row order, so the assignment is deterministic and re-running is idempotent.
    Leaves every other alert in its NEW state. See :func:`run_mock_bopa_pipeline`.
    """
    # Vistas: one BOPA/Client alert (Fontaneria Puigcerdà SL) + one obligation.
    db.query(Alert).filter(
        Alert.alert_type == AlertType.BOPA, Alert.customer_id == "cust-001"
    ).update({Alert.status: AlertStatus.VIEWED}, synchronize_session=False)
    db.query(Alert).filter(Alert.bc_obligation_id == "pobl-002").update(
        {Alert.status: AlertStatus.VIEWED}, synchronize_session=False
    )
    # Descartadas: one obligation alert.
    db.query(Alert).filter(Alert.bc_obligation_id == "pobl-006").update(
        {Alert.status: AlertStatus.DISCARDED}, synchronize_session=False
    )
    db.commit()
