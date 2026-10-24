import io
import json
import httpx
import pytest
from PIL import Image
from app.errors import AppError
from app.question_images.config import ImageSettings

URL='https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/result.png?Expires=123&Signature=temporary'


def config(**values):
    values.setdefault('IMAGE_MIN_REQUEST_INTERVAL_SECONDS',0)
    return ImageSettings(_env_file=None,IMAGE_API_KEY='private-key',IMAGE_BASE_URL='https://workspace.cn-beijing.maas.aliyuncs.com/api/v1',
        COS_SECRET_ID='id',COS_SECRET_KEY='secret',COS_REGION='ap-shanghai',COS_BUCKET='images-12345',COS_PUBLIC_BASE_URL='https://images.example.com',**values)


def png(size=(512,512)):
    data=io.BytesIO()
    Image.new('RGB',size,'blue').save(data,'PNG')
    return data.getvalue()


def response(url=URL):
    return {'output':{'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':[{'image':url}]}}]}}


@pytest.mark.anyio
async def test_qwen_sync_request_and_question_prompt():
    from app.question_images.provider import QwenImages
    from app.question_images.planning import scene_prompt
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(200,json=response())
    prompt=scene_prompt('A single red apple on a pale tabletop.')
    assert 'apple' in prompt and 'tabletop' in prompt
    result=await QwenImages(config(),transport=httpx.MockTransport(handle)).generate(prompt)
    assert result==URL and len(calls)==1
    request=calls[0]
    assert str(request.url).endswith('/services/aigc/multimodal-generation/generation')
    body=json.loads(request.content)
    assert body['model']=='qwen-image-2.0' and body['parameters']['size']=='512*512' and body['parameters']['n']==1
    assert request.headers['Authorization']=='Bearer private-key'
    assert body['input']['messages']==[{'role':'user','content':[{'text':prompt}]}]


@pytest.mark.anyio
@pytest.mark.parametrize('status,code',[(401,'IMAGE_AUTH_ERROR'),(403,'IMAGE_AUTH_ERROR'),(429,'IMAGE_RATE_LIMIT'),(500,'IMAGE_UNAVAILABLE'),(400,'IMAGE_REJECTED')])
async def test_provider_error_is_sanitized_without_paid_retry(status,code):
    from app.question_images.provider import QwenImages
    calls=[]
    def handle(r):
        calls.append(r)
        return httpx.Response(status,json={'message':'secret-provider-payload'})
    with pytest.raises(AppError) as failure:
        await QwenImages(config(),transport=httpx.MockTransport(handle)).generate('apple')
    assert failure.value.code==code and 'secret' not in str(failure.value)
    assert len(calls)==1


@pytest.mark.anyio
@pytest.mark.parametrize('data',[{}, {'code':'invalid','message':'private'}, {'output':{'choices':[]}}, response('http://127.0.0.1/private'),
    response('https://attacker.example/a.png'), response('https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com@evil.example/a.png')])
async def test_malformed_or_untrusted_provider_output(data):
    from app.question_images.provider import QwenImages
    with pytest.raises(AppError):
        await QwenImages(config(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=data))).generate('apple')


@pytest.mark.anyio
async def test_provider_timeout_and_non_json():
    from app.question_images.provider import QwenImages
    def timeout(r):raise httpx.ReadTimeout('private-url',request=r)
    with pytest.raises(AppError) as failure:
        await QwenImages(config(),transport=httpx.MockTransport(timeout)).generate('apple')
    assert failure.value.code=='IMAGE_TIMEOUT'
    with pytest.raises(AppError):
        await QwenImages(config(),transport=httpx.MockTransport(lambda r:httpx.Response(200,text='not-json'))).generate('apple')


@pytest.mark.anyio
async def test_current_official_oss_accelerate_image_url():
    from app.question_images.provider import QwenImages
    from app.question_images.storage import download_png
    url='https://dashscope-0484.oss-accelerate.aliyuncs.com/result.png?Expires=123&Signature=temporary'
    provider=QwenImages(config(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=response(url))))
    assert await provider.generate('apple')==url
    assert download_png(url,config(),reader=lambda *args:(url,png(),'image/png')).startswith(b'\x89PNG')


def test_oss_accelerate_domain_validation_rejects_lookalikes():
    from app.question_images.provider import result_url
    for url in ['http://dashscope-0484.oss-accelerate.aliyuncs.com/a.png',
                'https://dashscope-0484.oss-accelerate.aliyuncs.com.evil.example/a.png',
                'https://dashscope-0484.oss-accelerate.aliyuncs.com@evil.example/a.png',
                'https://other-bucket.oss-accelerate.aliyuncs.com/a.png',
                'https://dashscope-evil.oss-accelerate.aliyuncs.com/a.png',
                'https://dashscope-0484.oss-accelerate.aliyuncs.com:444/a.png']:
        with pytest.raises(AppError):result_url(url)


def test_download_validates_source_bytes_size_and_redirect_target():
    from app.question_images.storage import download_png
    assert download_png(URL,config(),reader=lambda *args:(URL,png(),'image/png')).startswith(b'\x89PNG')
    for final,data,kind in [('https://evil.example/a',png(),'image/png'),(URL,b'invalid','image/png'),
                            (URL,png((32,32)),'image/png'),(URL,png(),'text/html'),(URL,b'x'*10000,'image/png')]:
        with pytest.raises(AppError):
            download_png(URL,config(IMAGE_MAX_BYTES=8192),reader=lambda *args:(final,data,kind))
    with pytest.raises(AppError):
        download_png('https://127.0.0.1/a',config(),reader=lambda *args:pytest.fail('must not request'))


def test_cos_upload_is_bounded_and_returns_permanent_distribution_url(monkeypatch):
    from app.question_images.storage import CosImageStorage
    import qcloud_cos
    settings, requests = [],[]
    class Client:
        def put_object(self,**kwargs):requests.append(kwargs);return {'ETag':'valid'}
        def delete_object(self,**kwargs):requests.append(kwargs)
    monkeypatch.setattr(qcloud_cos,'CosConfig',lambda **kwargs:settings.append(kwargs) or kwargs)
    monkeypatch.setattr(qcloud_cos,'CosS3Client',lambda conf,**kwargs:settings.append(kwargs) or Client())
    storage=CosImageStorage(config())
    key='question-images/'+'a'*32+'.png'
    assert storage.upload(png(),key)=='https://images.example.com/'+key
    assert settings[0]['Scheme']=='https' and settings[0]['Timeout']==15 and settings[1]['retry']==0
    assert requests[0]['Bucket']=='images-12345' and requests[0]['ContentType']=='image/png'
    assert requests[0]['Body']==png() and 'Authorization' not in requests[0]
    storage.delete(key,bucket='old-12345',region='ap-beijing')
    assert requests[-1]=={'Bucket':'old-12345','Key':key}
    with pytest.raises(AppError):storage.upload(png(),'../../private')


def test_cos_failure_does_not_expose_credentials(monkeypatch):
    from app.question_images.storage import CosImageStorage
    import qcloud_cos
    class Client:
        def put_object(self,**kwargs):raise RuntimeError('secret-provider-payload')
    monkeypatch.setattr(qcloud_cos,'CosS3Client',lambda *a,**k:Client())
    with pytest.raises(AppError) as failure:
        CosImageStorage(config()).upload(png(),'question-images/'+'a'*32+'.png')
    assert failure.value.code=='COS_UPLOAD_FAILED' and 'secret' not in str(failure.value)
