"""price history (for performance charts) and client-RM messages

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('price_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('close', sa.Float(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('retrieved_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'day', name='uq_price_symbol_day')
    )
    op.create_index(op.f('ix_price_history_symbol'), 'price_history', ['symbol'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.String(length=60), nullable=False),
    sa.Column('rm_id', sa.String(length=40), nullable=False),
    sa.Column('sender_role', sa.String(length=10), nullable=False),
    sa.Column('sender_name', sa.String(length=120), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_client_id'), 'messages', ['client_id'], unique=False)
    op.create_index(op.f('ix_messages_created_at'), 'messages', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_messages_created_at'), table_name='messages')
    op.drop_index(op.f('ix_messages_client_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_price_history_symbol'), table_name='price_history')
    op.drop_table('price_history')
