import os
import ssl
from pathlib import Path

import certifi
import httpx
from ..errors import AppError


_CLOUD_WECHAT_CA = Path('/app/cert/certificate.crt')


def _wechat_verify() -> ssl.SSLContext | bool:
    """Add the cloud sidecar's CA for this client while retaining normal trust."""
    if not _CLOUD_WECHAT_CA.is_file():
        return True
    # Preserve HTTPX 0.28's existing certificate-store precedence.
    if os.environ.get('SSL_CERT_FILE'):
        context = ssl.create_default_context(cafile=os.environ['SSL_CERT_FILE'])
    elif os.environ.get('SSL_CERT_DIR'):
        context = ssl.create_default_context(capath=os.environ['SSL_CERT_DIR'])
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(_CLOUD_WECHAT_CA))
    return context


class WeChatClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    async def exchange(self, code: str):
        if not self.settings.wechat_app_id or not self.settings.wechat_app_secret.get_secret_value():
            raise AppError('WECHAT_NOT_CONFIGURED', '请先配置微信小程序登录', 503)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10,
                                         verify=_wechat_verify()) as client:
                response = await client.get('https://api.weixin.qq.com/sns/jscode2session', params={
                    'appid': self.settings.wechat_app_id,
                    'secret': self.settings.wechat_app_secret.get_secret_value(),
                    'js_code': code,
                    'grant_type': 'authorization_code',
                })
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict) or data.get('errcode') or not isinstance(data.get('openid'), str) or not data['openid']:
                raise ValueError('Invalid identity')
            return {'openid': data['openid'], 'unionid': data.get('unionid') or None}
        except (httpx.HTTPError, ValueError, TypeError, OSError):
            raise AppError('WECHAT_LOGIN_FAILED', '微信登录暂时失败，请重新登录', 502) from None
