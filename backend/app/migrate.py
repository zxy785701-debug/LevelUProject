"""Run explicitly: python -m app.migrate [--test]. Never drops business data."""
import argparse
from .config import Settings
from .accounts.database import Database

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    settings = Settings(database_testing=args.test)
    Database(settings).migrate()
    print('MySQL migration complete:', settings.mysql_test_database if args.test else settings.mysql_database)
