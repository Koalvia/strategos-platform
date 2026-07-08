"""Add task_notes table

Adds the one local table for the Business-Central-sourced Tareas domain: internal
notes staff leave on a task. Tasks themselves live in BC (no local columns); this
table holds only the platform-native note text, keyed by the opaque BC task id.
See issue #10.

Revision ID: c1a2b3d4e5f6
Revises: b7f3c2a1d9e4
Create Date: 2026-07-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1a2b3d4e5f6'
down_revision = 'b7f3c2a1d9e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_task_notes_id'), 'task_notes', ['id'], unique=False)
    op.create_index(
        op.f('ix_task_notes_task_id'), 'task_notes', ['task_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_task_notes_task_id'), table_name='task_notes')
    op.drop_index(op.f('ix_task_notes_id'), table_name='task_notes')
    op.drop_table('task_notes')
