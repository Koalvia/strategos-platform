"""add user role column

Revision ID: e5f6a7b8c9d0
Revises: c1a2b3d4e5f6
Create Date: 2026-07-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'c1a2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable so existing rows (and self-registered accounts that carry no
    # staff role) upgrade cleanly without a backfill.
    op.add_column('users', sa.Column('role', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'role')
