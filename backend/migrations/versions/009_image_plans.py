"""Durable batch visual descriptions, independent of paid image request quota."""
from alembic import context, op
import sqlalchemy as sa

revision = '009_image_plans'
down_revision = '008_question_images'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('question_image_plans',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('operation_id',sa.String(64),primary_key=True),
        sa.Column('source_hash',sa.String(64),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),
        sa.Column('scenes',sa.JSON,nullable=True),sa.Column('created_at',sa.DateTime,nullable=False),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')


def downgrade():
    connection = op.get_bind()
    target = context.get_revision_argument()
    # Preflight every protected older table before MySQL's nontransactional DDL.
    for name in sa.inspect(connection).get_table_names():
        protected = name == 'question_image_plans'
        if target not in (down_revision,'008','-1'):
            protected |= name.startswith(('question_image_', 'knowledge_'))
        if protected:
            table = sa.Table(name,sa.MetaData(),autoload_with=connection)
            if connection.scalar(sa.select(sa.func.count()).select_from(table)):
                raise RuntimeError('Protected data exists; disable new image generation instead of downgrading')
    op.drop_table('question_image_plans')
