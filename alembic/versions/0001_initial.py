"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2025-12-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None


def upgrade():
    op.create_table(
        'workflows',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('workflow', sa.Text(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False, index=True),
        sa.Column('source_id', sa.String(), nullable=False, unique=True),
        sa.Column('source_url', sa.Text()),
        sa.Column('keywords', sa.JSON()),
        sa.Column('country', sa.String(), index=True),
        sa.Column('popularity_metrics', sa.JSON()),
        sa.Column('popularity_score', sa.Float(), index=True),
        sa.Column('score_components', sa.JSON()),
        sa.Column('last_updated', sa.TIMESTAMP()),
        sa.Column('evidence_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('workflows')
