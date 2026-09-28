"""Add obligation_task_states table

Board workflow state for obligations shown as tasks: one row per obligation
instance (``bc_obligation_id`` unique), reusing the existing ``taskstatus`` enum
(created by the task_status_overrides migration, so not recreated here).

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'obligation_task_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bc_obligation_id', sa.String(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'pending', 'in_progress', 'waiting_client', 'done',
                name='taskstatus', create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('updated_by', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_obligation_task_states_id'),
        'obligation_task_states', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_obligation_task_states_bc_obligation_id'),
        'obligation_task_states', ['bc_obligation_id'], unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_obligation_task_states_bc_obligation_id'),
        table_name='obligation_task_states',
    )
    op.drop_index(
        op.f('ix_obligation_task_states_id'),
        table_name='obligation_task_states',
    )
    op.drop_table('obligation_task_states')
    # The ``taskstatus`` enum is left in place: task_status_overrides still uses it.
