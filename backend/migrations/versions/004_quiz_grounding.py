"""Topic preparations and bounded background operation progress (additive)."""
from alembic import op
import sqlalchemy as sa

revision = '004_quiz_grounding'
down_revision = '003_materials_analytics'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ai_quotas', sa.Column('topic_prepare_count', sa.Integer, nullable=False, server_default='0'))
    op.add_column('ai_operations', sa.Column('stage', sa.String(32), nullable=True))
    op.add_column('ai_operations', sa.Column('deadline_at', sa.DateTime, nullable=True))
    for field in ('retry_after_seconds', 'model_calls', 'tool_calls', 'page_attempts'):
        op.add_column('ai_operations', sa.Column(field, sa.Integer, nullable=False, server_default='0'))
    op.create_table(
        'topic_preparations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('ai_operations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(128, collation='utf8mb4_bin'), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('input_text', sa.Text, nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('stage', sa.String(32), nullable=False),
        sa.Column('content', sa.JSON, nullable=True),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('user_id', 'key', name='uq_topic_prepare_key'),
        sa.UniqueConstraint('operation_id', name='uq_topic_prepare_operation'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4',
    )
    op.create_index('ix_topic_preparations_user_id', 'topic_preparations', ['user_id'])
    op.create_index('ix_topic_preparations_expires_at', 'topic_preparations', ['expires_at'])


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; keep source snapshots and use the feature flag')
