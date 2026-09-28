"""Add task_status_overrides table

Adds the second local table for the Business-Central-sourced Tareas domain: the
platform-owned workflow state set when a user moves a task between board columns.
Tasks live in BC (read-only); this table holds one override row per task, keyed by
the opaque BC task id, and wins over the BC status on read. Introduces the
``taskstatus`` enum (Pendiente / En curso / Esperando información / Hecho).

Revision ID: f8a9b0c1d2e3
Revises: e1f2a3b4c5d6
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8a9b0c1d2e3'
down_revision = 'e1f2a3b4c5d6'
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


def downgrade() -> None:
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
