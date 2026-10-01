"""Add bc_project_id to alerts (traffic-light owner routing)

Revision ID: e5a6b7c8d9e0
Revises: d4f5a6b7c8d9
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e5a6b7c8d9e0'
down_revision = 'd4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('alerts', sa.Column('bc_project_id', sa.String(), nullable=True))
    op.create_index(
        op.f('ix_alerts_bc_project_id'), 'alerts', ['bc_project_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_alerts_bc_project_id'), table_name='alerts')
    op.drop_column('alerts', 'bc_project_id')
