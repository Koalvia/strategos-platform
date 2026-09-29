"""Add task_status_overrides and obligation_task_states tables

Platform-native workflow columns for the Tareas board: one row per BC task and one
per obligation instance. Both share the ``taskstatus`` PG enum (created here).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_status_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'pending', 'in_progress', 'waiting_client', 'done',
                name='taskstatus',
            ),
            nullable=False,
        ),
        sa.Column('updated_by', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_task_status_overrides_id'),
        'task_status_overrides', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_task_status_overrides_task_id'),
        'task_status_overrides', ['task_id'], unique=True,
    )

    op.create_table(
        'obligation_task_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bc_obligation_id', sa.String(), nullable=False),
        sa.Column(
            'status',
            # Reuse the enum created above (do not emit CREATE TYPE again).
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

    op.drop_index(
        op.f('ix_task_status_overrides_task_id'),
        table_name='task_status_overrides',
    )
    op.drop_index(
        op.f('ix_task_status_overrides_id'),
        table_name='task_status_overrides',
    )
    op.drop_table('task_status_overrides')
    # Drop the standalone ENUM type (Postgres only; a no-op on SQLite).
    sa.Enum(name='taskstatus').drop(op.get_bind(), checkfirst=True)
