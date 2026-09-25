"""merge alert-email and traffic-light heads

Revision ID: f1a2b3c4d5e6
Revises: e2f3a4b5c6d7, e1f2a3b4c5d6
Create Date: 2026-09-25 17:10:00.000000

PRs #95 (alert email fields + preferences) and #105 (traffic-light settings) each
added a migration off ``d1e2f3a4b5c6``, leaving two Alembic heads. With two heads
``alembic upgrade head`` fails, so the deploy's API container never becomes
healthy. This is an empty merge revision that unifies both heads into one; no
schema changes.
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = ('e2f3a4b5c6d7', 'e1f2a3b4c5d6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
