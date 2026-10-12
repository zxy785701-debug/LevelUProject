"""Store epoch deadlines without 32-bit floating-point rounding."""
from alembic import op
import sqlalchemy as sa
revision = '002_quota_precision'
down_revision = '001_accounts'
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column('ai_quotas', 'busy_until', type_=sa.Double(), existing_type=sa.Float(), existing_nullable=False)
    op.alter_column('ai_quotas', 'retire_after', type_=sa.Double(), existing_type=sa.Float(), existing_nullable=True)

def downgrade():
    raise RuntimeError('Destructive downgrade is disabled')
