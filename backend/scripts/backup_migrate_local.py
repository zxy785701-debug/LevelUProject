"""Back up this local development database before applying additive migrations."""
from datetime import datetime
from pathlib import Path
import json
import subprocess
import sys
import tempfile
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.accounts.database import Database


def main():
    settings = Settings()
    assert not settings.database_testing and settings.mysql_host in ('127.0.0.1', 'localhost')
    database = Database(settings)
    with database.engine.connect() as connection:
        assert connection.scalar(text('SELECT DATABASE()')) == settings.mysql_database
        before = connection.scalar(text('SELECT version_num FROM alembic_version'))
    directory = Path(__file__).resolve().parents[1] / 'logs/db-backups'
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / ('before-grounding-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sql')
    def ini(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', suffix='.cnf', delete=False) as config:
            temporary = Path(config.name)
            config.write('[client]\nhost=' + ini(settings.mysql_host) + '\nport=' + str(settings.mysql_port) + '\nuser=' + ini(settings.mysql_user) + '\npassword=' + ini(settings.mysql_password.get_secret_value()) + '\n')
        result = subprocess.run([sys.argv[1], '--defaults-extra-file=' + str(temporary), '--single-transaction', '--no-tablespaces', '--set-gtid-purged=OFF', '--routines', '--triggers', '--events', '--hex-blob', '--databases', settings.mysql_database, '--result-file=' + str(backup)], capture_output=True, timeout=60)
        if result.returncode or not backup.exists() or backup.stat().st_size == 0:
            print(json.dumps({'backup': 'failed', 'migration': 'not_started', 'exit_code': result.returncode}))
            return 1
    finally:
        if temporary: temporary.unlink(missing_ok=True)
    database.migrate()
    with database.engine.connect() as connection:
        after = connection.scalar(text('SELECT version_num FROM alembic_version'))
        connection.execute(text('SELECT retrieval_log FROM ai_operations LIMIT 1'))
    print(json.dumps({'backup': str(backup), 'backup_bytes': backup.stat().st_size, 'before': before, 'after': after, 'retrieval_log': 'available'}))
    database.engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
