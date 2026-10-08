"""Add 'archived' value to the taskstatus enum

Lets a board card (BC task or obligation) be archived — hidden from the board and
shown only under the "Archivadas" filter.

Revision ID: f6b7c8d9e0a1
Revises: e5a6b7c8d9e0
Create Date: 2026-10-08
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'f6b7c8d9e0a1'
down_revision = 'e5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres only: SQLite stores SAEnum as VARCHAR, so the new value is picked up
    # from the model with no ALTER. (PG 12+ allows ADD VALUE inside a transaction as
    # long as the value is not used in the same transaction, which it is not here.)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'archived'")


def downgrade() -> None:
    # Postgres cannot drop a single enum value without recreating the type; left as a
    # no-op (the unused value is harmless).
    pass
