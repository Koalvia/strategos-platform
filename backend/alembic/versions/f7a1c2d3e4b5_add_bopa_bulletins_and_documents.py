"""Add bopa bulletins and documents

Adds the two tables backing the BOPA domain: ``bopa_bulletins`` (one row per
synced numbered issue, unique on ``(year, num)``) and ``bopa_documents`` (its
documents, unique on ``(bulletin_id, document_name)``). Only text, metadata and
constructed reference URLs are stored — never the source PDFs. See issue #49.

Revision ID: f7a1c2d3e4b5
Revises: e5f6a7b8c9d0
Create Date: 2026-07-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a1c2d3e4b5'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bopa_bulletins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('num', sa.Integer(), nullable=False),
        sa.Column('is_extra', sa.Boolean(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('total_document_count', sa.Integer(), nullable=False),
        sa.Column('sumari_pdf_url', sa.String(), nullable=False),
        sa.Column(
            'fetched_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('year', 'num', name='uq_bopa_bulletin_year_num'),
    )
    op.create_index(
        op.f('ix_bopa_bulletins_id'), 'bopa_bulletins', ['id'], unique=False
    )
    op.create_table(
        'bopa_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bulletin_id', sa.Integer(), nullable=False),
        sa.Column('document_name', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('organisme', sa.String(), nullable=False),
        sa.Column('organisme_pare', sa.String(), nullable=False),
        sa.Column('tema', sa.String(), nullable=False),
        sa.Column('tema_pare', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('article_date', sa.DateTime(), nullable=False),
        sa.Column('source_url', sa.String(), nullable=False),
        sa.Column('pdf_url', sa.String(), nullable=False),
        sa.Column('html_content', sa.Text(), nullable=True),
        sa.Column(
            'fetched_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['bulletin_id'], ['bopa_bulletins.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'bulletin_id', 'document_name', name='uq_bopa_document_bulletin_name'
        ),
    )
    op.create_index(
        op.f('ix_bopa_documents_id'), 'bopa_documents', ['id'], unique=False
    )
    op.create_index(
        op.f('ix_bopa_documents_bulletin_id'),
        'bopa_documents',
        ['bulletin_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_bopa_documents_bulletin_id'), table_name='bopa_documents')
    op.drop_index(op.f('ix_bopa_documents_id'), table_name='bopa_documents')
    op.drop_table('bopa_documents')
    op.drop_index(op.f('ix_bopa_bulletins_id'), table_name='bopa_bulletins')
    op.drop_table('bopa_bulletins')
