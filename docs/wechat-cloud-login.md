# 微信云托管登录证书修复

2026-10-25，云端微信登录返回 `WECHAT_LOGIN_FAILED`。容器内对照检查确认：默认证书和系统证书验证均触发 `SSLCertVerificationError`；显式补充 `/app/cert/certificate.crt` 后，可以建立 HTTPS 连接。

微信官方说明，开放接口服务可能在容器内为 `api.weixin.qq.com` 安装平台自签名证书，部分运行时需要手动信任，见[平台证书说明](https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloudrun/src/guide/weixin/open)。HTTPX 支持通过 `SSLContext` 补充可信 CA，见[HTTPX 0.28.1 SSL 文档](https://github.com/encode/httpx/blob/0.28.1/docs/advanced/ssl.md)。环境变量行为还核对了项目实际安装的 HTTPX 0.28.1 `create_ssl_context` 实现。

## 修复范围

- 仅微信登录客户端在平台证书文件存在时，将其追加到当前可信证书集合。
- 保留 HTTPX 原有 `SSL_CERT_FILE`、`SSL_CERT_DIR`、certifi 的选择优先级；平台证书不存在时沿用原有客户端行为。
- HTTPS、证书链校验和主机名校验继续生效；没有全局修改 SSL，也没有调整其他 API 客户端。
- 平台证书损坏、不可读取或微信返回错误时，继续返回友好的登录失败提示，不返回密钥、临时登录凭证或底层请求 URL。
- 无新增环境变量、依赖或数据库迁移。

## TDD 验证

测试仅连接本机临时 HTTPS 服务，证书由现有 cryptography 依赖临时生成，凭据均为虚构值。

- RED：新增测试在原实现下为 1 失败、7 通过，失败场景准确复现平台证书不受信任时无法完成登录。
- GREEN：证书测试及现有账号基础回归共 25 项通过，其中包含 10 项真实 TLS 场景。
- 覆盖平台 CA、现有可信根和自定义证书存储的保留、非云端登录、证书损坏、不受信任的证书、域名不匹配，以及 HTTPS 已连通但上游仍返回 502 时不得登录成功。

复核命令（在 `backend/` 运行）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wechat_tls.py tests/test_account_foundation.py -q
```

本机 RED/GREEN 原始日志分别位于 `backend/logs/wechat-tls-red-latest.log`、`backend/logs/wechat-tls-green-latest.log`，按现有规则忽略，不提交。

## 云端发布与验收

1. 云托管使用包含本修复的最新 `main` 提交重新构建、发布。目标目录仍为 `backend`，Dockerfile 为 `Dockerfile`，端口为 `8080`。若已有流水线自动发布，先确认其结果，避免重复构建。
2. 发布完成后在新版本实例验证，旧实例中的代码不会随 GitHub 提交自动改变。
3. 在微信开发者工具重新点击微信登录，确认能进入学习页面，再测试出题。

此前补充平台证书后的 HTTP 502 来自对 `https://api.weixin.qq.com/` 根路径的探测，不能代表 `/sns/jscode2session` 登录接口的结果。本次自动测试验证的是 TLS 修复和错误处理；真实云端微信登录仍需发布后验收。

如果发布后仍失败，在新实例终端执行以下诊断。仅发送固定无效测试凭证，输出状态和数字错误码，不创建业务账号、不显示真实密钥：

```sh
cd /app && /opt/venv/bin/python - <<'PY'
import asyncio
import httpx
from app.config import Settings
from app.accounts.wechat import _wechat_verify

async def main():
    try:
        s = Settings()
        async with httpx.AsyncClient(verify=_wechat_verify(), timeout=15) as client:
            r = await client.get("https://api.weixin.qq.com/sns/jscode2session", params={
                "appid": s.wechat_app_id,
                "secret": s.wechat_app_secret.get_secret_value(),
                "js_code": "0" * 32,
                "grant_type": "authorization_code",
            })
        print("HTTP状态:", r.status_code)
        data = r.json()
        code = data.get("errcode") if isinstance(data, dict) else None
        print("微信错误码:", code if isinstance(code, int) else "无标准错误码")
    except Exception as error:
        print("错误类型:", type(error).__name__)

asyncio.run(main())
PY
```

该诊断使用的 code 本身无效，因此不能证明真实微信登录已通过。不要输出整个响应、请求 URL、环境变量或异常全文，也不要将平台证书路径设成所有外部 API 共用的唯一 CA 集合。
