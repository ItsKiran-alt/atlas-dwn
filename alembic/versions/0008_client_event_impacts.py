"""AI-drafted outlook of market events for one client (cached)

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('client_event_impacts',
    sa.Column('client_id', sa.String(length=60), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.PrimaryKeyConstraint('client_id')
    )


def downgrade() -> None:
    op.drop_table('client_event_impacts')
