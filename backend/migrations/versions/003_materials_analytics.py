"""Materials, recoverable jobs, period reports and separate daily quotas."""
from alembic import op
import sqlalchemy as sa

revision = '003_materials_analytics'
down_revision = '002_quota_precision'
branch_labels = None
depends_on = None


def upgrade():
    for field in ('material_count', 'period_count'):
        op.add_column('ai_quotas', sa.Column(field, sa.Integer, nullable=False, server_default='0'))
    user = lambda: sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    common = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    op.create_table('material_jobs', sa.Column('id', sa.String(36), primary_key=True), user(),
        sa.Column('key', sa.String(128, collation='utf8mb4_bin'), nullable=False), sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('stage', sa.String(32), nullable=False),
        sa.Column('material_id', sa.String(36)), sa.Column('error_code', sa.String(64)), sa.Column('message', sa.String(300)),
        sa.Column('created_at', sa.DateTime, nullable=False, index=True), sa.UniqueConstraint('user_id', 'key', name='uq_material_job_key'), **common)
    op.create_table('materials', sa.Column('id', sa.String(36), primary_key=True), user(), sa.Column('content', sa.JSON, nullable=False),
        sa.Column('referenced', sa.Integer, nullable=False), sa.Column('created_at', sa.DateTime, nullable=False, index=True), **common)
    op.create_table('period_reports', sa.Column('id', sa.String(36), primary_key=True), user(), sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('snapshot', sa.JSON, nullable=False), sa.Column('content', sa.JSON), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False), sa.Column('error_code', sa.String(64)), sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('user_id', 'digest', name='uq_period_snapshot'), **common)
    op.create_index('ix_attempt_analysis', 'learning_attempts', ['user_id', 'mode', 'completed_at'])


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled')
