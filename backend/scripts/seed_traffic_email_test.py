"""Seed a controlled traffic-light email test scenario (mock, opt-in).

Generates the dev fixtures (loaded by MockBusinessCentralClient only when
``STRATEGOS_DEV_FIXTURES=1``), creates the two app users that can log in, and
pre-seeds the obligation traffic state so a pipeline run detects two worsenings
*today*: one green->yellow and one yellow->red. The two green obligations do not
trigger.

Users created (real passwords, verified):
* technician  brian.marin+strategosemailtest@koalvia.com        / Strategos2026!
* manager     brian.marin+managerstrategosemailtest@koalvia.com / Manager2026!

The manager also has a BC resource card with manageAllCustomers, so they resolve
as director (can edit the traffic-light toggle) and are added to the emails when
the toggle is on.

Run from ``backend/`` (mock mode), then start the worker with
``STRATEGOS_DEV_FIXTURES=1`` and run the pipeline (evaluate + dispatch)::

    python -m scripts.seed_traffic_email_test
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

script_dir = Path(__file__).parent
app_dir = script_dir.parent
sys.path.insert(0, str(app_dir))

import app.main  # noqa: E402,F401  (registers every ORM model so mappers resolve)
from app.db.session import get_db  # noqa: E402
from app.domains.alerts.models import ObligationTrafficState  # noqa: E402
from app.domains.auth.models import User  # noqa: E402
from app.domains.auth.utils import get_password_hash  # noqa: E402

TECH_EMAIL = "brian.marin+strategosemailtest@koalvia.com"
TECH_PASSWORD = "Strategos2026!"
MANAGER_EMAIL = "brian.marin+managerstrategosemailtest@koalvia.com"
MANAGER_PASSWORD = "Manager2026!"

_FIXTURES_DEV = app_dir / "app/integrations/business_central/fixtures/dev"

# Ids used by both the fixtures and the seeded traffic state.
TECH_USER_ID = "dev-usr-tech"
TECH_CODE = "BRIANTEST"
MANAGER_RES_ID = "dev-res-manager"
CUSTOMER_ID = "dev-cust-email"
PROJECT_ID = "dev-proj-email"
OB_GREEN_1 = "dev-obl-green-1"
OB_GREEN_2 = "dev-obl-green-2"
OB_YELLOW = "dev-obl-yellow"
OB_RED = "dev-obl-red"


def _write(name: str, data) -> None:
    (_FIXTURES_DEV / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_dev_fixtures() -> None:
    """Write fixtures/dev/*.json with due dates relative to today."""
    _FIXTURES_DEV.mkdir(parents=True, exist_ok=True)
    today = date.today()

    def due(days: int) -> str:
        return (today + timedelta(days=days)).isoformat()

    _write("users.json", [
        {"id": TECH_USER_ID, "name": "Brian Test", "email": TECH_EMAIL,
         "user_name": TECH_CODE},
    ])
    # The manager is a resource with manageAllCustomers (director + email recipient).
    _write("resources.json", [
        {"id": MANAGER_RES_ID, "name": "Brian Manager", "email": MANAGER_EMAIL,
         "manage_all_customers": True},
    ])
    _write("customers.json", [
        {"id": CUSTOMER_ID, "name": "Cliente Test Email", "nif": "X0000000X",
         "customer_type": "Company", "responsible": "", "active_project_count": 1,
         "status": "Activo"},
    ])
    _write("projects.json", [
        {"id": PROJECT_ID, "name": "Proyecto Test Email", "customer_id": CUSTOMER_ID,
         "project_type": "Iguala mensual", "entity_type": "Societat",
         "responsible": "", "technician": TECH_CODE, "has_certificate": None,
         "certificate_expiry": None, "filing_date": None, "status": "Activo"},
    ])
    # 2 green (+40/+60), 1 yellow (+10), 1 red (+3); thresholds yellow=15, red=7.
    _write("project_obligations.json", [
        {"id": ob_id, "project_id": PROJECT_ID, "obligation_id": "obl-is",
         "subject": True, "due_date": d, "submission_date": None,
         "fecha_notificacion": None, "status": None}
        for ob_id, d in (
            (OB_GREEN_1, due(40)), (OB_GREEN_2, due(60)),
            (OB_YELLOW, due(10)), (OB_RED, due(3)),
        )
    ])


def _ensure_user(db, name: str, email: str, password: str) -> None:
    if db.query(User).filter(User.email.ilike(email)).one_or_none() is None:
        db.add(User(
            name=name, email=email,
            hashed_password=get_password_hash(password), is_verified=True,
        ))


def _seed_db() -> None:
    """Create the two app users and pre-seed the worsening traffic state."""
    db = next(get_db())
    try:
        _ensure_user(db, "Brian Test", TECH_EMAIL, TECH_PASSWORD)
        _ensure_user(db, "Brian Manager", MANAGER_EMAIL, MANAGER_PASSWORD)

        # Reset then seed: yellow was green, red was yellow -> both worsen today.
        db.query(ObligationTrafficState).filter(
            ObligationTrafficState.bc_obligation_id.in_(
                [OB_GREEN_1, OB_GREEN_2, OB_YELLOW, OB_RED]
            )
        ).delete(synchronize_session=False)
        db.add(ObligationTrafficState(bc_obligation_id=OB_YELLOW, last_status="Al día"))
        db.add(ObligationTrafficState(bc_obligation_id=OB_RED, last_status="Próximo"))
        db.commit()
    finally:
        db.close()


def main() -> None:
    _write_dev_fixtures()
    _seed_db()
    print(f"Dev fixtures written to {_FIXTURES_DEV}")
    print(f"App users ensured: {TECH_EMAIL} / {MANAGER_EMAIL}")
    print(
        "Now run the worker with STRATEGOS_DEV_FIXTURES=1 (mock mode) and trigger the "
        "pipeline (evaluate_traffic_transitions + dispatch_alert_emails). With the "
        "director toggle OFF, expect 2 emails to the technician; with it ON, the "
        "manager also receives them."
    )


if __name__ == "__main__":
    main()
