"""Add notify_manager_on_change to traffic_light_settings

Director opt-in to also receive the per-project traffic-light emails.

Revision ID: d4f5a6b7c8d9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd4f5a6b7c8d9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'traffic_light_settings',
        sa.Column(
            'notify_manager_on_change',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('traffic_light_settings', 'notify_manager_on_change')
