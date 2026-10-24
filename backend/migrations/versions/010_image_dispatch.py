"""Shared model dispatch pacing across API and knowledge Worker processes."""
from alembic import context, op
import sqlalchemy as sa

revision='010_image_dispatch'
down_revision='009_image_plans'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('question_image_dispatch',
        sa.Column('model',sa.String(64),primary_key=True),
        sa.Column('next_allowed_at',sa.Float(53),nullable=False),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')


def downgrade():
    connection=op.get_bind()
    target=context.get_revision_argument()
    for name in sa.inspect(connection).get_table_names():
        protected=name=='question_image_dispatch'
        if target not in (down_revision,'009','-1'):
            protected |= name.startswith(('question_image_', 'knowledge_'))
        if protected:
            table=sa.Table(name,sa.MetaData(),autoload_with=connection)
            if connection.scalar(sa.select(sa.func.count()).select_from(table)):
                raise RuntimeError('Protected data exists; disable new image generation instead of downgrading')
    op.drop_table('question_image_dispatch')
