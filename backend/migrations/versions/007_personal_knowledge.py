"""Independent durable personal knowledge tables. Frozen revision definitions."""
from alembic import op
import sqlalchemy as sa

revision = '007_personal_knowledge'
down_revision = '006_retrieval_audit'
branch_labels = None
depends_on = None


def definitions():
    metadata = sa.MetaData()
    # External referenced tables exist already; placeholders are never created here.
    sa.Table('users', metadata, sa.Column('id', sa.String(36), primary_key=True))
    sa.Table('ai_operations', metadata, sa.Column('id', sa.String(36), primary_key=True))
    def col(name, kind, nullable=False, **kwargs):
        return sa.Column(name, kind, nullable=nullable, **kwargs)
    def uid(primary_key=False):
        return sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, primary_key=primary_key, index=not primary_key)
    def table(name, *columns):
        return sa.Table('knowledge_' + name, metadata, *columns, mysql_engine='InnoDB', mysql_charset='utf8mb4')
    def ident(): return col('id', sa.String(36), primary_key=True)
    def created(): return col('created_at', sa.DateTime)
    def operation(unique=False): return col('operation_id', sa.String(36), unique=unique, index=not unique)
    def integer(name): return col(name, sa.Integer)
    def json(name, nullable=False): return col(name, sa.JSON, nullable=nullable)
    tables = [
        table('documents', ident(), uid(), col('title', sa.String(180)), col('source_type', sa.String(16)), json('source'),
              col('status', sa.String(16)), col('active_revision_id', sa.String(36), nullable=True),
              col('deleted_at', sa.DateTime, nullable=True, index=True), created(), col('updated_at', sa.DateTime)),
        table('revisions', ident(), sa.Column('document_id', sa.String(36), sa.ForeignKey('knowledge_documents.id', ondelete='CASCADE'), nullable=False, index=True),
              integer('number'), col('profile', sa.String(64)), col('status', sa.String(16)), col('text', sa.Text(16777215)), json('segments'), json('manifest'),
              col('parser_version', sa.String(64)), col('splitter_version', sa.String(64)), created(), sa.UniqueConstraint('document_id', 'number', name='uq_knowledge_revision_number')),
        table('chunks', col('id', sa.String(64), primary_key=True), sa.Column('revision_id', sa.String(36), sa.ForeignKey('knowledge_revisions.id', ondelete='CASCADE'), nullable=False, index=True),
              integer('position'), col('text', sa.Text), col('content_hash', sa.String(64)), json('location'), sa.UniqueConstraint('revision_id', 'position', name='uq_knowledge_chunk_position')),
        table('jobs', ident(), uid(), col('kind', sa.String(16)), col('key', sa.String(128, collation='utf8mb4_bin')), col('digest', sa.String(64)), operation(),
              sa.Column('ai_operation_id', sa.String(36), sa.ForeignKey('ai_operations.id', ondelete='SET NULL'), nullable=True),
              col('parent_id', sa.String(36), nullable=True), col('document_id', sa.String(36), nullable=True, index=True), json('payload'), json('budget'), json('result', True),
              col('status', sa.String(16), index=True), col('stage', sa.String(32)), integer('progress'), col('priority', sa.Integer, index=True), integer('attempts'), integer('fence'),
              col('owner', sa.String(36), nullable=True), col('lease_until', sa.DateTime, nullable=True, index=True), col('deadline_at', sa.DateTime), integer('retry_after_seconds'),
              col('error_code', sa.String(64), nullable=True), col('message', sa.String(300), nullable=True), col('created_at', sa.DateTime, index=True),
              sa.UniqueConstraint('user_id', 'kind', 'key', name='uq_knowledge_job_key')),
        table('checkpoints', col('operation_id', sa.String(36), primary_key=True), col('name', sa.String(100), primary_key=True), uid(), json('content'), col('updated_at', sa.DateTime)),
        table('scopes', ident(), operation(True), uid(), integer('version'), col('goal', sa.Text), json('documents'), integer('supplement'), json('content'), created(), col('expires_at', sa.DateTime, index=True)),
        table('questions', ident(), operation(True), uid(), col('question', sa.Text), json('documents'), integer('supplement'), json('content'), col('deleted_at', sa.DateTime, nullable=True), col('created_at', sa.DateTime, index=True)),
        table('cleanup_outbox', ident(), col('user_id', sa.String(36), index=True), json('payload'), col('status', sa.String(16), index=True), integer('attempts'), integer('fence'),
              col('owner', sa.String(36), nullable=True), col('lease_until', sa.DateTime, nullable=True), col('error_code', sa.String(64), nullable=True), created()),
        table('usage', col('identity', sa.String(64), primary_key=True), col('day', sa.String(10), primary_key=True), integer('imports'), integer('questions'), integer('embedding_reserved'), integer('embedding_actual')),
        table('worker_leases', col('id', sa.String(64), primary_key=True), col('owner', sa.String(36)), integer('fence'), col('expires_at', sa.DateTime), col('heartbeat_at', sa.DateTime)),
        table('embedding_cache', uid(True), col('profile', sa.String(64), primary_key=True), col('content_hash', sa.String(64), primary_key=True), col('text_type', sa.String(12), primary_key=True), json('vector'), created()),
        table('published_results', col('operation_id', sa.String(36), primary_key=True), uid(), col('kind', sa.String(16)), json('result'), created()),
    ]
    return tables


def upgrade():
    for table in definitions():
        table.create(op.get_bind())


def downgrade():
    tables = definitions()
    connection = op.get_bind()
    if any(connection.scalar(sa.select(sa.func.count()).select_from(table)) for table in tables):
        raise RuntimeError('Knowledge data exists; disable new submissions and retain snapshots instead of destructive downgrade')
    for table in reversed(tables):
        table.drop(connection)
