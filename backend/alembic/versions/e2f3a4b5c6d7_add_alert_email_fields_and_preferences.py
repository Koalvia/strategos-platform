"""add alert email fields and per-user preferences

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-25 12:00:00.000000

Adds the email layer's persistence: ``alerts.obligation_code`` (template/category
routing) and ``alerts.email_sent_at`` (the send-once dedup guard), plus the
``user_alert_preferences`` table (one row per user+category opt-in).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None

# create_type=False: the type is created once, explicitly, with checkfirst below;
# without this the create_table would try to CREATE TYPE a second time (and fail
# with DuplicateObject on PostgreSQL). checkfirst also tolerates a type left behind
# by a previously failed run.
alert_category = postgresql.ENUM(
    'BOPA',
    'DOCUMENT_EXPIRY',
    'IVA',
    'OBLIGATION',
    name='alertcategory',
    create_type=False,
)


def upgrade() -> None:
    op.add_column('alerts', sa.Column('obligation_code', sa.String(), nullable=True))
    op.add_column(
        'alerts',
        sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True),
    )

    alert_category.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'user_alert_preferences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('category', alert_category, nullable=False),
        sa.Column(
            'email_enabled', sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.UniqueConstraint('user_id', 'category', name='uq_user_alert_pref'),
    )
    op.create_index(
        op.f('ix_user_alert_preferences_user_id'),
        'user_alert_preferences',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_user_alert_preferences_user_id'),
        table_name='user_alert_preferences',
    )
    op.drop_table('user_alert_preferences')
    alert_category.drop(op.get_bind(), checkfirst=True)
    op.drop_column('alerts', 'email_sent_at')
    op.drop_column('alerts', 'obligation_code')
