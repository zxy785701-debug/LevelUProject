"""Exercise certificate validation over real, local HTTPS connections."""
import json
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import certifi
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.accounts import wechat
from app.config import Settings
from app.errors import AppError


REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def tls_servers(tmp_path, monkeypatch):
    # Tests never use developer proxy credentials or external services.
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
                 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
        monkeypatch.delenv(name, raising=False)
    servers = []

    def start(hostname='localhost', status=200):
        directory = tmp_path / str(len(servers))
        directory.mkdir()
        now = datetime.now(timezone.utc)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Local test CA')])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                             key_encipherment=False, data_encipherment=False, key_agreement=False,
                             key_cert_sign=True, crl_sign=True, encipher_only=False,
                             decipher_only=False), critical=True)
              .sign(key, hashes.SHA256()))
        ca_file = directory / 'ca.pem'
        ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
                .issuer_name(ca.subject).public_key(server_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        cert_file, key_file = directory / 'server.pem', directory / 'server.key'
        cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(server_key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(parse_qs(urlsplit(self.path).query))
                body = json.dumps({'openid': 'trusted-user', 'session_key': 'private-session'}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        servers.append((server, thread))
        return SimpleNamespace(ca=ca_file, requests=requests,
                               url=f'https://localhost:{server.server_port}/sns/jscode2session')

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def login_client(monkeypatch, server, platform_ca):
    monkeypatch.setattr(wechat, '_CLOUD_WECHAT_CA', platform_ca, raising=False)

    class LocalClient(REAL_ASYNC_CLIENT):
        async def get(self, url, **kwargs):
            assert url == 'https://api.weixin.qq.com/sns/jscode2session'
            return await super().get(server.url, **kwargs)

    monkeypatch.setattr(wechat.httpx, 'AsyncClient', LocalClient)
    return wechat.WeChatClient(Settings(_env_file=None, wechat_app_id='test-app',
                                      wechat_app_secret='private-test-secret'))


@pytest.mark.anyio
async def test_platform_certificate_enables_verified_login_without_changing_other_clients(tls_servers, monkeypatch):
    server = tls_servers()
    client = login_client(monkeypatch, server, server.ca)
    assert await client.exchange('one-use-code') == {'openid': 'trusted-user', 'unionid': None}
    assert server.requests == [{'appid': ['test-app'], 'secret': ['private-test-secret'],
                               'js_code': ['one-use-code'], 'grant_type': ['authorization_code']}]
    # The additional trust must be confined to WeChat, not a global SSL override.
    async with REAL_ASYNC_CLIENT(timeout=3) as ordinary_client:
        with pytest.raises(httpx.ConnectError):
            await ordinary_client.get(server.url)


@pytest.mark.anyio
@pytest.mark.parametrize('root_source', ['default', 'SSL_CERT_FILE'])
async def test_platform_certificate_preserves_existing_trusted_roots(tls_servers, monkeypatch, root_source):
    trusted_server, platform_server = tls_servers(), tls_servers()
    if root_source == 'default':
        monkeypatch.setattr(certifi, 'where', lambda: str(trusted_server.ca))
    else:
        monkeypatch.setenv('SSL_CERT_FILE', str(trusted_server.ca))
    client = login_client(monkeypatch, trusted_server, platform_server.ca)
    assert (await client.exchange('code'))['openid'] == 'trusted-user'


@pytest.mark.anyio
async def test_no_platform_certificate_preserves_normal_login(tls_servers, monkeypatch, tmp_path):
    server = tls_servers()
    monkeypatch.setattr(certifi, 'where', lambda: str(server.ca))
    client = login_client(monkeypatch, server, tmp_path / 'absent.pem')
    assert (await client.exchange('code'))['openid'] == 'trusted-user'


@pytest.mark.anyio
async def test_platform_certificate_works_with_configured_certificate_directory(tls_servers, monkeypatch, tmp_path):
    server = tls_servers()
    certificate_directory = tmp_path / 'root-store'
    certificate_directory.mkdir()
    monkeypatch.setenv('SSL_CERT_DIR', str(certificate_directory))
    client = login_client(monkeypatch, server, server.ca)
    assert (await client.exchange('code'))['openid'] == 'trusted-user'


@pytest.mark.anyio
async def test_verified_connection_does_not_turn_gateway_failure_into_login(tls_servers, monkeypatch):
    server = tls_servers(status=502)
    client = login_client(monkeypatch, server, server.ca)
    with pytest.raises(AppError) as error:
        await client.exchange('private-login-code')
    assert error.value.code == 'WECHAT_LOGIN_FAILED'
    assert 'private' not in error.value.message
    assert len(server.requests) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('failure', ['untrusted', 'hostname', 'missing_platform_ca', 'malformed_platform_ca'])
async def test_invalid_tls_is_rejected_without_leaking_credentials(tls_servers, monkeypatch, tmp_path, failure):
    server = tls_servers('wrong-host.invalid' if failure == 'hostname' else 'localhost')
    platform_ca = server.ca
    if failure == 'untrusted':
        platform_ca = tls_servers().ca
    elif failure == 'missing_platform_ca':
        platform_ca = tmp_path / 'absent.pem'
    elif failure == 'malformed_platform_ca':
        platform_ca = tmp_path / 'invalid.pem'
        platform_ca.write_text('not a certificate', encoding='utf8')
    client = login_client(monkeypatch, server, platform_ca)
    with pytest.raises(AppError) as error:
        await client.exchange('private-login-code')
    assert error.value.code == 'WECHAT_LOGIN_FAILED'
    assert error.value.status == 502
    assert 'private' not in error.value.message
    assert server.requests == []
