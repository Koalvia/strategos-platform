"""Remove BOPA matches (and their alerts) that fail the whole-word rule, once.

A one-off cleanup for data created before the analyzer switched from a naked
``term in text`` substring test to whole-word name/NIF matching (see
``app.domains.bopa.matching``). Any stored match whose ``matched_term`` no longer
appears as complete word(s) in its document is a false positive; this deletes it
together with its alert, so it is no longer shown and no longer links anywhere.

Run it from ``backend/``::

    python -m scripts.prune_bopa_false_positives

or, against the docker-compose stack::

    docker compose exec app python -m scripts.prune_bopa_false_positives

Idempotent: newly created matches already satisfy the rule, so a second run
removes nothing.
"""

import sys
from pathlib import Path

# Add the backend directory to the path so ``app`` imports work when run directly.
script_dir = Path(__file__).parent
app_dir = script_dir.parent
sys.path.insert(0, str(app_dir))

from app import logger  # noqa: E402
from app.domains.bopa.tasks import prune_false_positive_matches  # noqa: E402


def main() -> int:
    """Prune false-positive BOPA matches in-process; return how many were removed."""
    removed = prune_false_positive_matches()
    logger.info(f"Prune complete: {removed} false-positive BOPA matches removed.")
    return removed


if __name__ == "__main__":
    main()
