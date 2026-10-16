"""Explicit handoff from an unreadable page with a clear topic to scope confirmation."""
from alembic import op
import sqlalchemy as sa

revision = '005_material_scope_handoff'
down_revision = '004_quiz_grounding'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('material_jobs', sa.Column('preparation_id', sa.String(36), nullable=True))
    op.create_foreign_key('fk_material_job_preparation', 'material_jobs', 'topic_preparations',
                          ['preparation_id'], ['id'], ondelete='SET NULL')


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled')
