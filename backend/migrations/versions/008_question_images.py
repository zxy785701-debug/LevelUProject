"""Optional question illustration quotas and durable object ownership."""
from alembic import context, op
import sqlalchemy as sa

revision = '008_question_images'
down_revision = '007_personal_knowledge'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('question_image_usage',
        sa.Column('identity',sa.String(64),primary_key=True),
        sa.Column('day',sa.String(10),primary_key=True),sa.Column('requests',sa.Integer,nullable=False),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('question_image_calls',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('operation_id',sa.String(64),nullable=False),sa.Column('question_id',sa.String(64),nullable=False),
        sa.Column('prompt_hash',sa.String(64),nullable=False),sa.Column('day',sa.String(10),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('object_key',sa.String(128),nullable=False),
        sa.Column('image_url',sa.String(2048),nullable=True),sa.Column('error_code',sa.String(80),nullable=True),
        sa.Column('created_at',sa.DateTime,nullable=False),
        sa.UniqueConstraint('user_id','operation_id','question_id',name='uq_image_call_question'),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_question_image_calls_user_id','question_image_calls',['user_id'])
    op.create_table('question_image_assets',
        sa.Column('object_key',sa.String(128),primary_key=True),sa.Column('user_id',sa.String(36),nullable=False),
        sa.Column('bucket',sa.String(128),nullable=False),sa.Column('region',sa.String(64),nullable=False),
        sa.Column('delete_after',sa.DateTime,nullable=True),sa.Column('attempts',sa.Integer,nullable=False),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_question_image_assets_user_id','question_image_assets',['user_id'])
    op.create_index('ix_question_image_assets_delete_after','question_image_assets',['delete_after'])


def downgrade():
    connection=op.get_bind()
    # MySQL DDL commits immediately. Check the older protected migration before
    # dropping any 008 table when a multi-version downgrade crosses 007.
    target=context.get_revision_argument()
    if target not in (down_revision,'007','-1'):
        for name in sa.inspect(connection).get_table_names():
            if name.startswith('knowledge_'):
                table=sa.Table(name,sa.MetaData(),autoload_with=connection)
                if connection.scalar(sa.select(sa.func.count()).select_from(table)):
                    raise RuntimeError('Knowledge data exists; refuse multi-version downgrade before changing image tables')
    for name in ('question_image_assets','question_image_calls','question_image_usage'):
        table=sa.Table(name,sa.MetaData(),autoload_with=connection)
        if connection.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError('Image records exist; disable new generation and retain stored images instead')
    for name in ('question_image_assets','question_image_calls','question_image_usage'):
        op.drop_table(name)
