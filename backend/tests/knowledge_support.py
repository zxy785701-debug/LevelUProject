"""Explicit test-only boundaries. Never imported by the production API/worker."""
from pathlib import Path
from sqlalchemy import text


def assert_test_boundary(settings, actual_database, storage_root, temporary_root):
    if (not settings.database_testing or actual_database != settings.mysql_test_database
            or actual_database == settings.mysql_database or not actual_database.endswith('_test')):
        raise RuntimeError('Knowledge tests require the explicitly configured isolated MySQL test database')
    path, temporary = Path(storage_root), Path(temporary_root)
    if not path.is_absolute() or path.resolve() == temporary.resolve() or not path.resolve().is_relative_to(temporary.resolve()):
        raise RuntimeError('Knowledge test files and indexes must be children of the test temporary directory')


def assert_database(settings, connection):
    actual = connection.scalar(text('SELECT DATABASE()'))
    if (not settings.database_testing or actual != settings.mysql_test_database
            or actual == settings.mysql_database or not actual.endswith('_test')):
        raise RuntimeError('Refusing to modify a non-test database')
    return actual


def embedding_response(request):
    """Deterministic provider boundary, while MySQL and Chroma remain real."""
    import hashlib
    import json
    import httpx
    payload = json.loads(request.content)
    texts = payload['input']['texts']
    values = []
    for index, value in enumerate(texts):
        digest = hashlib.sha256(value.encode()).digest()
        vector = [(digest[i % len(digest)] - 127.5) / 127.5 for i in range(1024)]
        values.append({'text_index': index, 'embedding': vector})
    return httpx.Response(200, json={'output': {'embeddings': values},
                                   'usage': {'total_tokens': sum(len(t.encode()) for t in texts)}})
