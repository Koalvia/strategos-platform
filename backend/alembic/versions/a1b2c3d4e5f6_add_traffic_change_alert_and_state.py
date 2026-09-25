"""add traffic-change alert category, alerts.category and obligation_traffic_state

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-09-25 18:00:00.000000

Supports emailing on worsening obligation traffic-light transitions:

* extends the ``alertcategory`` enum with ``TRAFFIC_CHANGE`` (PostgreSQL only —
  on SQLite the type is a plain VARCHAR with no enumerated values to alter);
* adds ``alerts.category``, an explicit category override so colour-change alerts
  reuse ``AlertType.OBLIGATION`` yet route to their own template/preference;
* creates ``obligation_traffic_state`` (one remembered status per obligation) so
  the daily task can detect transitions without a per-obligation local row.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

# Reference the existing enum type by name (create_type=False): the type already
# exists from an earlier migration, so this must never try to CREATE TYPE it again.
alert_category = postgresql.ENUM(
    'BOPA',
    'DOCUMENT_EXPIRY',
    'IVA',
    'OBLIGATION',
    'TRAFFIC_CHANGE',
    name='alertcategory',
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # PostgreSQL enums are closed: the new member must be added to the type before
    # any column can hold it. SQLite renders the enum as VARCHAR, so there is
    # nothing to alter there.
    if bind.dialect.name == 'postgresql':
        op.execute(
            "ALTER TYPE alertcategory ADD VALUE IF NOT EXISTS 'TRAFFIC_CHANGE'"
        )

    op.add_column('alerts', sa.Column('category', alert_category, nullable=True))

    op.create_table(
        'obligation_traffic_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bc_obligation_id', sa.String(), nullable=False),
        sa.Column('last_status', sa.String(), nullable=False),
        sa.Column(
            'last_evaluated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            'bc_obligation_id', name='uq_obligation_traffic_state_bc_id'
        ),
    )
    op.create_index(
        op.f('ix_obligation_traffic_state_bc_obligation_id'),
        'obligation_traffic_state',
        ['bc_obligation_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_obligation_traffic_state_bc_obligation_id'),
        table_name='obligation_traffic_state',
    )
    op.drop_table('obligation_traffic_state')
    op.drop_column('alerts', 'category')
    # The added enum value is intentionally left in place: PostgreSQL cannot drop a
    # value from an enum type, and re-adding it later is idempotent.
