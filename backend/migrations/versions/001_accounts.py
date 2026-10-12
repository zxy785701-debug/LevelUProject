"""Initial authenticated learning schema.

Revision definitions are frozen here; future schema edits require a new revision.
"""
from alembic import op
import sqlalchemy as sa

revision = '001_accounts'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('identity', sa.String(64), nullable=False, unique=True),
        sa.Column('appid', sa.String(64, collation='utf8mb4_bin'), nullable=False),
        sa.Column('openid', sa.String(128, collation='utf8mb4_bin'), nullable=False),
        sa.Column('unionid', sa.String(128)),
        sa.Column('nickname', sa.String(32), nullable=False),
        sa.Column('xp', sa.Integer, nullable=False), sa.Column('coins', sa.Integer, nullable=False),
        sa.Column('avatar', sa.LargeBinary), sa.Column('avatar_version', sa.Integer, nullable=False),
        sa.Column('agreement_version', sa.String(32), nullable=False), sa.Column('consent_at', sa.DateTime, nullable=False), sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('appid', 'openid', name='uq_wechat_identity'), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('login_sessions', sa.Column('digest', sa.String(64), primary_key=True), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True), sa.Column('expires_at', sa.DateTime, nullable=False, index=True), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('quizzes', sa.Column('id', sa.String(36), primary_key=True), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True), sa.Column('content', sa.JSON, nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('learning_attempts',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('quiz_id', sa.String(36), sa.ForeignKey('quizzes.id', ondelete='CASCADE')),
        sa.Column('quiz', sa.JSON, nullable=False), sa.Column('mode', sa.String(12), nullable=False), sa.Column('answers', sa.JSON, nullable=False), sa.Column('cursor', sa.Integer, nullable=False), sa.Column('review_keys', sa.JSON, nullable=False),
        sa.Column('started_at', sa.DateTime, nullable=False), sa.Column('completed_at', sa.DateTime), sa.Column('report', sa.JSON), sa.Column('report_attempts', sa.Integer, nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('reward_ledger', sa.Column('id', sa.String(36), primary_key=True), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True), sa.Column('quiz_id', sa.String(36), sa.ForeignKey('quizzes.id', ondelete='CASCADE'), nullable=False), sa.Column('question_id', sa.String(128), nullable=False), sa.Column('xp', sa.Integer, nullable=False), sa.Column('coins', sa.Integer, nullable=False), sa.UniqueConstraint('user_id', 'quiz_id', 'question_id', name='uq_question_reward'), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('wrong_questions', sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True), sa.Column('key', sa.String(180), primary_key=True), sa.Column('attempt_id', sa.String(36), sa.ForeignKey('learning_attempts.id', ondelete='CASCADE'), nullable=False), sa.Column('question_id', sa.String(128), nullable=False), sa.Column('mastered', sa.Integer, nullable=False), sa.Column('reviews', sa.JSON, nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('ai_quotas', sa.Column('identity', sa.String(64), primary_key=True), sa.Column('day', sa.String(10), nullable=False), sa.Column('quiz_count', sa.Integer, nullable=False), sa.Column('calls', sa.JSON, nullable=False), sa.Column('busy_id', sa.String(36)), sa.Column('busy_until', sa.Float, nullable=False), sa.Column('retire_after', sa.Float, index=True), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('ai_operations', sa.Column('id', sa.String(36), primary_key=True), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True), sa.Column('key', sa.String(128, collation='utf8mb4_bin'), nullable=False), sa.Column('digest', sa.String(64), nullable=False), sa.Column('kind', sa.String(12), nullable=False), sa.Column('attempt_id', sa.String(36)), sa.Column('status', sa.String(16), nullable=False), sa.Column('charged', sa.Integer, nullable=False), sa.Column('result', sa.JSON), sa.Column('error_code', sa.String(64)), sa.Column('created_at', sa.DateTime, nullable=False), sa.UniqueConstraint('user_id', 'key', name='uq_user_operation'), mysql_engine='InnoDB', mysql_charset='utf8mb4')

def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; restore from a reviewed backup instead')
