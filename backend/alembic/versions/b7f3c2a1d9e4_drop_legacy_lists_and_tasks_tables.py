"""Drop legacy lists and tasks tables

Removes the TaskFlow-era personal to-do domain (``lists`` and ``tasks``) so the
new Business-Central-sourced Tareas domain can be built cleanly. See issue #5.

The downgrade recreates both tables in their final pre-drop shape (including the
task recurrence columns) so the migration is fully reversible.

Revision ID: b7f3c2a1d9e4
Revises: d34c0a0cde34
Create Date: 2026-07-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f3c2a1d9e4'
down_revision = 'd34c0a0cde34'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop ``tasks`` before ``lists``: tasks holds a FK into lists.
    op.drop_index(op.f('ix_tasks_parent_task_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_lists_id'), table_name='lists')
    op.drop_table('lists')
    # Drop the standalone ENUM types the tasks table introduced (Postgres only;
    # a no-op on backends without standalone enum types, e.g. SQLite).
    sa.Enum(name='priorityenum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='recurrenceenum').drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Recreate ``lists`` first, then ``tasks`` (which references it). The
    # create_table calls re-create the priorityenum/recurrenceenum types on
    # Postgres automatically.
    op.create_table(
        'lists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_lists_id'), 'lists', ['id'], unique=False)

    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('list_id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Enum('low', 'medium', 'high', name='priorityenum'), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('completed', sa.Boolean(), nullable=True),
        sa.Column(
            'recurrence',
            sa.Enum('none', 'daily', 'weekly', 'monthly', name='recurrenceenum'),
            server_default='none',
            nullable=False,
        ),
        sa.Column('parent_task_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['list_id'], ['lists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['parent_task_id'], ['tasks.id'],
            name='fk_tasks_parent_task_id_tasks', ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tasks_id'), 'tasks', ['id'], unique=False)
    op.create_index(op.f('ix_tasks_parent_task_id'), 'tasks', ['parent_task_id'], unique=False)
