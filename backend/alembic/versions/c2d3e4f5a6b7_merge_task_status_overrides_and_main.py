"""Merge task_status_overrides head into main

Unifies the two divergent Alembic heads into one so ``alembic upgrade head`` is
unambiguous:

* ``a1b2c3d4e5f6`` — main's tip (traffic-change alert category + obligation
  traffic state).
* ``f8a9b0c1d2e3`` — task_status_overrides (this branch).

Both descend from ``e1f2a3b4c5d6`` (via main's own merge ``f1a2b3c4d5e6``), so this
is a no-op merge with no schema change.

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6, f8a9b0c1d2e3
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = ('a1b2c3d4e5f6', 'f8a9b0c1d2e3')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
