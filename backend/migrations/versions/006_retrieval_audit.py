"""Persist bounded retrieval parameters and actual provider metadata on operations."""
from alembic import op
import sqlalchemy as sa

revision = '006_retrieval_audit'
down_revision = '005_material_scope_handoff'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ai_operations', sa.Column('retrieval_log', sa.JSON, nullable=True))


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled')
