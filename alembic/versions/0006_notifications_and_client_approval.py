"""client notifications, client approval state on recommendations, message kind

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.String(length=60), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_client_id'), 'notifications', ['client_id'], unique=False)
    op.create_index(op.f('ix_notifications_created_at'), 'notifications', ['created_at'], unique=False)
    op.add_column('recommendations', sa.Column('client_approval', sa.String(length=20), nullable=False, server_default='not_required'))
    op.add_column('messages', sa.Column('kind', sa.String(length=20), nullable=False, server_default='text'))


def downgrade() -> None:
    op.drop_column('messages', 'kind')
    op.drop_column('recommendations', 'client_approval')
    op.drop_index(op.f('ix_notifications_created_at'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_client_id'), table_name='notifications')
    op.drop_table('notifications')
