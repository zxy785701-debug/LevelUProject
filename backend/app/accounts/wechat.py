import httpx
from ..errors import AppError


class WeChatClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    async def exchange(self, code: str):
        if not self.settings.wechat_app_id or not self.settings.wechat_app_secret.get_secret_value():
            raise AppError('WECHAT_NOT_CONFIGURED', '请先配置微信小程序登录', 503)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
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
        except (httpx.HTTPError, ValueError, TypeError):
            raise AppError('WECHAT_LOGIN_FAILED', '微信登录暂时失败，请重新登录', 502) from None
