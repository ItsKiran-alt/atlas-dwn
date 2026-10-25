"""stored interpretations of news headlines (market event interpreter)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('news_interpretations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('guid_hash', sa.String(length=64), nullable=False),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('classes_json', sa.Text(), nullable=False),
    sa.Column('relevance', sa.String(length=10), nullable=False),
    sa.Column('fact', sa.Text(), nullable=False),
    sa.Column('interpretation', sa.Text(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_news_interpretations_guid_hash'), 'news_interpretations', ['guid_hash'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_news_interpretations_guid_hash'), table_name='news_interpretations')
    op.drop_table('news_interpretations')
