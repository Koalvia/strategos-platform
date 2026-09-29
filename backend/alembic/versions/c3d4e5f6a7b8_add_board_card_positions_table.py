"""Add board_card_positions table

Shared vertical order of cards within a Tareas board column. One row per card
(``(source, card_id)`` unique), independent of the status override.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'board_card_positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'card_id', name='uq_board_card_positions_card'),
    )
    op.create_index(
        op.f('ix_board_card_positions_id'),
        'board_card_positions', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_board_card_positions_card_id'),
        'board_card_positions', ['card_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_board_card_positions_card_id'),
        table_name='board_card_positions',
    )
    op.drop_index(
        op.f('ix_board_card_positions_id'),
        table_name='board_card_positions',
    )
    op.drop_table('board_card_positions')
