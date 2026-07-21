"""Run the mock BOPA → Alerts pipeline against the local database.

A dev convenience: ingests the crafted synthetic BOPA fixture, analyzes it into
customer/project matches (BOPA/Client alerts), and generates Obligation alerts —
all from committed fixtures, no external services. Use it to populate a local
database so the flow can be verified visually in the frontend.

Run it directly (from ``backend/``)::

    python -m scripts.run_mock_bopa_pipeline

It is idempotent: re-running does not create duplicate bulletins, matches, or
alerts. See ``app.domains.dev.service.run_mock_bopa_pipeline`` for the logic.
"""

import sys
import traceback
from pathlib import Path

# Add the backend directory to the path so ``app`` imports work when run directly.
script_dir = Path(__file__).parent
app_dir = script_dir.parent
sys.path.insert(0, str(app_dir))

from app.domains.dev.service import run_mock_bopa_pipeline  # noqa: E402


def main() -> None:
    from app.db.session import get_db

    db = next(get_db())
    try:
        result = run_mock_bopa_pipeline(db, demo_states=True)
        print("✅ Mock BOPA pipeline complete:")
        print(f"  • bulletins synced:   {result.bulletins_synced}")
        print(f"  • documents synced:   {result.documents_synced}")
        print(f"  • BOPA matches:       {result.bopa_matches}")
        print(f"  • BOPA/Client alerts: {result.bopa_alerts}")
        print(f"  • Obligation alerts:  {result.obligation_alerts}")
    except Exception:
        print("❌ Failed to run mock BOPA pipeline:")
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
