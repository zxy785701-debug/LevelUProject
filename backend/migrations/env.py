from alembic import context
from app.accounts.database import Base, Database
from app.config import Settings

config = context.config

def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

connection = config.attributes.get('connection')
if connection is not None:
    run(connection)
else:
    settings = Settings()
    if settings.database_testing:
        raise RuntimeError('Use the dedicated migrate --test command for test databases')
    with Database(settings).engine.connect() as connection:
        run(connection)
