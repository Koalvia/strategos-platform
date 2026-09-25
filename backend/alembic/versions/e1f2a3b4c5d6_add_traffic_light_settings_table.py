"""Add traffic_light_settings table

Adds the single-row store for the obligations traffic-light day thresholds a
director can edit at runtime (green→yellow and yellow→red) plus the
"email on change" toggle. The seed row is inserted lazily by the service on first
read, so this migration only creates the table. See issue #97.

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-09-25 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'traffic_light_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('yellow_within_days', sa.Integer(), nullable=False),
        sa.Column('red_within_days', sa.Integer(), nullable=False),
        sa.Column('email_on_change_enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('traffic_light_settings')
