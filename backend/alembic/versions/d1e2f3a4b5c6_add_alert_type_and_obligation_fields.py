"""add alert_type and obligation fields

Revision ID: d1e2f3a4b5c6
Revises: c9d8e7f6a5b4
Create Date: 2026-07-20 12:30:00.000000

Turns the ``alerts`` table into a unified notification center: a discriminator
(``alert_type``) plus the BC-obligation fields (``bc_obligation_id`` + its index,
denormalized ``title``/``message``) and a ``uq_alert_bc_obligation`` backstop.
Existing rows are all BOPA alerts, so ``alert_type`` backfills to ``'BOPA'`` via
its server default.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'c9d8e7f6a5b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    alert_type = sa.Enum('BOPA', 'OBLIGATION', name='alerttype')
    # Create the enum type explicitly (no-op on SQLite) so the add_column below
    # does not race the type creation on PostgreSQL.
    alert_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'alerts',
        sa.Column(
            'alert_type',
            alert_type,
            nullable=False,
            server_default='BOPA',
        ),
    )
    op.add_column('alerts', sa.Column('bc_obligation_id', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('title', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('message', sa.String(), nullable=True))
    op.create_index(
        op.f('ix_alerts_bc_obligation_id'),
        'alerts',
        ['bc_obligation_id'],
        unique=False,
    )
    op.create_unique_constraint(
        'uq_alert_bc_obligation', 'alerts', ['bc_obligation_id']
    )


def downgrade() -> None:
    op.drop_constraint('uq_alert_bc_obligation', 'alerts', type_='unique')
    op.drop_index(op.f('ix_alerts_bc_obligation_id'), table_name='alerts')
    op.drop_column('alerts', 'message')
    op.drop_column('alerts', 'title')
    op.drop_column('alerts', 'bc_obligation_id')
    op.drop_column('alerts', 'alert_type')
    sa.Enum(name='alerttype').drop(op.get_bind(), checkfirst=True)
