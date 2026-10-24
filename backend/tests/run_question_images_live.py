"""Explicit, paid image smoke test. Never collected by pytest or run at startup."""
import argparse
import asyncio
import json
import gzip
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.accounts.database import Database
from app.accounts.repository import Accounts
from app.config import Settings
from app.question_images.config import ImageSettings
from app.question_images.database import ImageCall
from app.llm import ModelGateway
from app.question_images.provider import QwenImages
from app.question_images.service import QuestionImages
from app.question_images.storage import download_png
from tests.knowledge_support import assert_database


class AuditStream(httpx.AsyncByteStream):
    def __init__(self, stream, audit, secrets, encoding):
        self.stream, self.audit, self.secrets = stream, audit, secrets
        self.encoding = encoding

    async def __aiter__(self):
        body = bytearray()
        async for chunk in self.stream:
            if len(body) < 65536:
                body.extend(chunk[:65536-len(body)])
            yield chunk
        try:
            self.audit['wire_bytes'] = len(body)
            if self.encoding == 'gzip':
                body = gzip.decompress(body)
            self.audit['json_bytes'] = len(body)
            data = json.loads(body)
            self.audit['root_keys'] = list(data) if isinstance(data, dict) else []
            if not isinstance(data, dict):
                return
            self.audit['code'] = data.get('code')
            self.audit['request_id'] = data.get('request_id')
            message = str(data.get('message', ''))
            for secret in self.secrets:
                if secret:
                    message = message.replace(secret, '[redacted]')
            self.audit['message'] = message[:500]
            output = data.get('output')
            self.audit['output_keys'] = list(output) if isinstance(output, dict) else []
            choices = output.get('choices') if isinstance(output, dict) else None
            if isinstance(choices, list):
                self.audit['choices'] = []
                for choice in choices:
                    message = choice.get('message', {})
                    contents = message.get('content', [])
                    self.audit['choices'].append({
                        'finish_reason': choice.get('finish_reason'), 'role': message.get('role'),
                        'content_keys': [list(item) for item in contents if isinstance(item, dict)],
                        'image_hosts': [urlsplit(item['image']).hostname for item in contents
                                        if isinstance(item, dict) and isinstance(item.get('image'), str)],
                    })
        except (ValueError, KeyError, TypeError):
            self.audit['json_valid'] = False

    async def aclose(self):
        await self.stream.aclose()


class AuditTransport(httpx.AsyncBaseTransport):
    def __init__(self, audit, secrets):
        self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.audit, self.secrets = audit, secrets

    async def handle_async_request(self, request):
        response = await self.transport.handle_async_request(request)
        self.audit.update(http_status=response.status_code, content_type=response.headers.get('content-type'),
                          content_encoding=response.headers.get('content-encoding'))
        stream=AuditStream(response.stream,self.audit,self.secrets,response.headers.get('content-encoding'))
        if response.status_code>=400:
            # The production adapter rejects HTTP errors without reading their
            # body. Consume it here only for bounded, redacted acceptance evidence.
            async for _ in stream:pass
            await stream.aclose()
            return httpx.Response(response.status_code)
        return httpx.Response(response.status_code, headers=response.headers,
                              stream=stream)

    async def aclose(self):
        await self.transport.aclose()


async def run(output):
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings(database_testing=True)
    database = Database(settings)
    with database.engine.connect() as connection:
        assert_database(settings, connection)
    database.migrate()
    accounts = Accounts(settings, database)
    user = accounts.login({'openid': 'image-live-'+uuid4().hex}, '2026-10-12')['user']['id']
    config = ImageSettings()
    audit = {}
    secrets = [config.api_key.get_secret_value(), config.cos_secret_id.get_secret_value(), config.cos_secret_key.get_secret_value()]
    provider = QwenImages(config, transport=AuditTransport(audit, secrets))

    def capture(url, config):
        data = download_png(url, config)
        (output/'apple-real.png').write_bytes(data)
        return data

    service = QuestionImages(accounts, config, provider=provider, download=capture)
    quiz = {'title': '英语水果词汇', 'questions': [
        {'id': 'apple', 'stem': '英语单词 apple 所指的是哪种水果？', 'knowledge_point': '英语水果词汇'},
    ]}
    before = service.repository.quota(user)
    started = time.monotonic()
    text_calls=0
    async def before_text():
        nonlocal text_calls
        text_calls+=1
        if text_calls>settings.model_max_attempts:raise RuntimeError('Live text-call bound exceeded')
    gateway=ModelGateway(settings,before_call=before_text,operation_id='live-image-planning')
    result = await service.attach(user, 'live-single-'+uuid4().hex, quiz,gateway=gateway)
    report = {'user_id': user, 'elapsed_seconds': round(time.monotonic()-started, 2),
              'quota_before': before, 'quota_after': service.repository.quota(user),
              'provider': audit, 'text_calls':text_calls, 'result': result}
    with database.session() as session:
        report['calls'] = [{'status': row.status, 'error_code': row.error_code, 'object_key': row.object_key}
                           for row in session.scalars(select(ImageCall).where(ImageCall.user_id == user))]
    (output/'single-audited.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    database.engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output))
