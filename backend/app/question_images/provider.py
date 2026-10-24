"""One bounded synchronous Qwen image HTTP request per question, without retries."""
import asyncio
import json
import re
from urllib.parse import urlsplit
import httpx
from ..errors import AppError


def result_url(value):
    if not isinstance(value,str) or len(value)>4096:
        raise AppError('IMAGE_INVALID_RESPONSE','配图服务返回的图片地址不可用',502)
    try:
        p=urlsplit(value)
        valid=(p.scheme=='https' and p.hostname and p.path and not p.username and not p.password
            and p.port in (None,443) and not p.fragment and not any(c.isspace() for c in value) and '\\' not in value
            and re.fullmatch(r'(?:dashscope-result-[a-z0-9-]+\.oss-[a-z0-9-]+'
                             r'|dashscope-[0-9]{4}\.oss-accelerate)\.aliyuncs\.com',p.hostname))
    except ValueError:
        valid=False
    if not valid:
        raise AppError('IMAGE_INVALID_RESPONSE','配图服务返回的图片地址不可用',502)
    return value


class QwenImages:
    def __init__(self, config, *, transport=None):
        self.config,self.transport=config,transport

    async def generate(self,prompt,*,before_dispatch=None):
        c=self.config
        payload={'model':c.model,'input':{'messages':[{'role':'user','content':[{'text':prompt}]}]},
            'parameters':{'n':1,'size':c.size,'prompt_extend':False,'watermark':False,
                          'negative_prompt':'文字，答案字母，选项标签，模糊，低清晰度，复杂背景'}}
        try:
            async with asyncio.timeout(c.timeout_seconds):
                async with httpx.AsyncClient(transport=self.transport,timeout=c.timeout_seconds,
                        follow_redirects=False,trust_env=False) as client:
                    if before_dispatch:await before_dispatch()
                    async with client.stream('POST',c.base_url+'/services/aigc/multimodal-generation/generation',
                            json=payload,headers={'Authorization':'Bearer '+c.api_key.get_secret_value()}) as response:
                        status=response.status_code
                        if status!=200:
                            code=('IMAGE_AUTH_ERROR' if status in (401,403) else 'IMAGE_RATE_LIMIT' if status==429
                                  else 'IMAGE_REJECTED' if 400<=status<500 else 'IMAGE_UNAVAILABLE')
                            raise AppError(code,'配图服务暂时无法完成请求，本轮仍可文字学习',502)
                        data=bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data)>65536:raise ValueError('oversized image metadata')
                        body=json.loads(data)
            if not isinstance(body,dict) or body.get('code'):raise ValueError('provider failure')
            choices=body['output']['choices']
            if not isinstance(choices,list) or len(choices)!=1:raise ValueError('invalid choices')
            choice=choices[0]
            content=choice['message']['content']
            if (choice.get('finish_reason')!='stop' or choice['message'].get('role')!='assistant'
                    or not isinstance(content,list) or len(content)!=1):raise ValueError('invalid content')
            return result_url(content[0]['image'])
        except (TimeoutError,httpx.TimeoutException):
            raise AppError('IMAGE_TIMEOUT','配图等待超时，本轮仍可文字学习',504) from None
        except httpx.HTTPError:
            raise AppError('IMAGE_UNAVAILABLE','配图服务连接失败，本轮仍可文字学习',502) from None
        except (KeyError,TypeError,ValueError,UnicodeError):
            raise AppError('IMAGE_INVALID_RESPONSE','配图服务返回内容不完整，本轮仍可文字学习',502) from None
